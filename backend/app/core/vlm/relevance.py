"""VLM 画面相关性校验（文本检索之后的「眼睛」）。

检索与 LLM 精排都只看文本表征（ASR/VLM 描述），无法确认候选片段的
画面真正支撑旁白语义。本模块从 storage 抽帧送给 VLM，对「文案 ↔ 画面」
打 0-10 分，低分候选在推荐列表中被降序/替换，消灭「驴唇不对马嘴」的画面。

帧目录布局与 splitter 一致：storage/<素材id>/frames/<片段stem>/frame_%03d.jpg。
所有函数为同步实现（同步 OpenAI 客户端），供线程池调用；失败静默降级，
绝不影响原有匹配结果。
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Dict, List, Mapping, Optional, Sequence

from app.core.llm.response_utils import extract_json_object

logger = logging.getLogger(__name__)

# 单次 VLM 调用的上限：候选数 × 每候选帧数（避免图片 token 爆炸）
_MAX_CANDIDATES_PER_CALL = 4
_MAX_FRAMES_PER_CLIP = 2

_VERIFY_PROMPT = (
    "你是视频画面审核员。下面给出一条旁白文案和若干候选片段的采样帧"
    "（每个候选前有 [候选N] 标记）。\n"
    "请逐个判断：该候选的画面内容能否支撑这句旁白的语义？\n"
    "- 10 分：画面直接呈现旁白描述的主体/动作/情绪；\n"
    "- 6~9 分：画面与旁白主题相关、可搭配使用；\n"
    "- 3~5 分：只有抽象关联（如同类氛围/空镜）；\n"
    "- 0~2 分：画面与旁白语义无关或明显冲突。\n"
    "只输出 JSON：{\"scores\":[{\"idx\":1,\"score\":8,\"reason\":\"一句话理由\"}, ...]}，"
    "idx 为候选编号，score 为 0~10 的数字，必须覆盖每个候选。"
)


def _even_sample(items: List[str], n: int) -> List[str]:
    """等间隔采样 n 个（保持时间顺序）。"""
    if n <= 0 or len(items) <= n:
        return items
    step = len(items) / n
    return [items[min(len(items) - 1, int(i * step))] for i in range(n)]


def _candidate_frame_dirs(clip_path: str, video_id: Optional[str]) -> List[str]:
    """由 clip_path 推导候选帧目录：storage/<vid>/frames/<stem>。

    抽帧目录名会剥掉文件名开头的素材 id 前缀，而 clip 文件名可能带前缀，
    因此两种 stem 都尝试（stripped 优先，与抽帧行为一致）。
    """
    if not clip_path:
        return []
    clip_dir = os.path.dirname(clip_path)
    # clip 位于 storage/<vid>/clips/ 下，帧目录为其同级 frames/
    frames_root = os.path.join(os.path.dirname(clip_dir), "frames")
    basename = os.path.basename(clip_path)
    stems = [os.path.splitext(basename)[0]]
    if video_id:
        try:
            from app.utils.storage_dedupe import strip_leading_material_id_from_clip_basename

            stripped = strip_leading_material_id_from_clip_basename(str(video_id), basename)
            stripped_stem = os.path.splitext(stripped)[0]
            if stripped_stem != stems[0]:
                stems.insert(0, stripped_stem)
        except Exception:
            pass
    return [os.path.join(frames_root, s) for s in stems]


def find_clip_frames(clip: Mapping, *, max_frames: int = _MAX_FRAMES_PER_CLIP) -> List[str]:
    """找到该 clip 在 storage 下的采样帧路径（等间隔取 max_frames 张）。

    clip 需含 clip_path；video_id 可选（用于兼容剥离素材 id 前缀的帧目录名）。
    找不到帧（未抽帧/文件被清理）返回 []，调用方跳过 VLM 校验。
    """
    clip_path = str(clip.get("clip_path") or "")
    video_id = clip.get("video_id")
    frames: List[str] = []
    for d in _candidate_frame_dirs(clip_path, video_id if video_id else None):
        if not os.path.isdir(d):
            continue
        jpgs = sorted(
            os.path.join(d, f)
            for f in os.listdir(d)
            if f.lower().endswith((".jpg", ".jpeg", ".png")) and f.startswith("frame_")
        )
        if jpgs:
            frames = jpgs
            break
    return _even_sample(frames, max(1, max_frames))


def _encode_image_b64(path: str) -> Optional[Dict[str, str]]:
    try:
        with open(path, "rb") as f:
            data = base64.standard_b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logger.warning("[VLMRelevance] 读取帧失败 %s: %s", path, e)
        return None
    ext = os.path.splitext(path)[1].lower().lstrip(".") or "jpg"
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png"}.get(ext, "jpeg")
    return {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{data}"}}


def score_candidates_sync(
    vlm_cfg: Mapping,
    narration: str,
    candidates: Sequence[Mapping],
    *,
    frames_per_clip: int = _MAX_FRAMES_PER_CLIP,
    call_fn: Optional[object] = None,
) -> Dict[str, Dict[str, object]]:
    """一次 VLM 调用为多个候选打「画面 ↔ 文案」相关度分。

    vlm_cfg 需含 base_url / api_key / model。
    call_fn: 可注入的调用函数 (content: list) -> str，便于测试。
    返回 {clip_id: {"vlm_score": float, "vlm_reason": str}}；
    无帧可用的候选不会出现在结果里（调用方保持其原顺序）。
    """
    narration = (narration or "").strip()
    if not narration or not candidates:
        return {}

    # 预取帧：只保留有帧的候选，按每候选帧数上限组装
    prepared: List[Dict[str, object]] = []
    for c in candidates[:_MAX_CANDIDATES_PER_CALL]:
        frame_paths = find_clip_frames(c, max_frames=frames_per_clip)
        if not frame_paths:
            continue
        prepared.append({"clip": c, "frames": frame_paths})
    if not prepared:
        return {}

    content: List[Dict[str, object]] = [
        {"type": "text", "text": _VERIFY_PROMPT},
        {"type": "text", "text": f"【旁白文案】\n{narration}"},
    ]
    for i, item in enumerate(prepared, 1):
        cid = str(item["clip"].get("clip_id") or "")
        content.append({"type": "text", "text": f"[候选{i} clip_id={cid}]"})
        for p in item["frames"]:  # type: ignore[union-attr]
            img = _encode_image_b64(str(p))
            if img:
                content.append(img)

    try:
        if call_fn is not None:
            raw = call_fn(content)  # type: ignore[operator]
        else:
            from openai import OpenAI

            client = OpenAI(
                api_key=vlm_cfg["api_key"],
                base_url=vlm_cfg["base_url"],
                timeout=float(vlm_cfg.get("timeout", 90) or 90),
            )
            resp = client.chat.completions.create(
                model=vlm_cfg["model"],
                messages=[{"role": "user", "content": content}],  # type: ignore[list-item]
                temperature=0.1,
                max_tokens=1024,
            )
            raw = str(resp.choices[0].message.content or "")
    except Exception as e:
        logger.warning("[VLMRelevance] VLM 调用失败，跳过画面校验: %s", e)
        return {}

    return _parse_scores(raw, prepared)


def _parse_scores(raw: str, prepared: List[Mapping]) -> Dict[str, Dict[str, object]]:
    if not raw or not raw.strip():
        return {}
    cleaned = extract_json_object(raw)
    import json

    try:
        data = json.loads(cleaned)
    except Exception:
        from json_repair import repair_json

        try:
            data = json.loads(repair_json(cleaned))
        except Exception as e:
            logger.warning("[VLMRelevance] 打分 JSON 解析失败: %s", e)
            return {}

    rows = data.get("scores") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return {}

    out: Dict[str, Dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("idx"))
        except (TypeError, ValueError):
            continue
        if not (1 <= idx <= len(prepared)):
            continue
        try:
            score = float(row.get("score"))
        except (TypeError, ValueError):
            continue
        # 非法分数直接丢弃，宁缺毋滥
        if score < 0 or score > 10:
            continue
        clip = prepared[idx - 1]["clip"]  # type: ignore[index]
        cid = str(clip.get("clip_id") or "")
        if not cid:
            continue
        reason = str(row.get("reason") or "").strip()[:120]
        out[cid] = {"vlm_score": round(score, 1), "vlm_reason": reason}
    return out


def apply_vlm_rerank(
    recommended: List[dict],
    vlm_results: Mapping[str, Mapping[str, object]],
    *,
    w_text: float = 0.55,
    w_vlm: float = 0.45,
) -> List[dict]:
    """用 VLM 分数对推荐列表重排并回填标注字段（原地补充，返回新顺序）。

    - 现有 score 是 0~10 尺度（LLM 精排），vlm_score 同为 0~10；
    - 无 VLM 分数的候选按 w_text * score 参与，保持在有分候选之后不丢失；
    - 仅重排顺序，不删除任何候选（宁滥勿缺由前端阈值兜底）。
    """
    if not recommended or not vlm_results:
        return recommended

    def _text_score(c: dict) -> float:
        try:
            s = float(c.get("score", 0) or 0)
        except (TypeError, ValueError):
            s = 0.0
        return max(0.0, min(10.0, s))

    def _combined(c: dict) -> float:
        text = _text_score(c)
        res = vlm_results.get(str(c.get("clip_id") or ""))
        if res is None:
            return w_text * text
        vlm = float(res.get("vlm_score", 0) or 0)
        return w_text * text + w_vlm * vlm

    for c in recommended:
        res = vlm_results.get(str(c.get("clip_id") or ""))
        if res is not None:
            c["vlm_score"] = float(res.get("vlm_score", 0) or 0)
            reason = str(res.get("vlm_reason") or "").strip()
            c["reason"] = (f"{c.get('reason') or ''}；VLM画面相关度 {c['vlm_score']}/10"
                           + (f"（{reason}）" if reason else "")).lstrip("；")

    return sorted(recommended, key=_combined, reverse=True)
