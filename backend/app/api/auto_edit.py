"""auto_edit.py — 自动一键成片 · Plan 规划接口

Phase 1：仅生成结构化 Plan，不负责实际成片渲染。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

import aiosqlite
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.core.blocking_pool import run_heavy
from app.db.database import DB_PATH
from app.core.llm import LLMClient, LLMConfig
from app.api.copy_gen import _build_video_context_with_recall
from app.models.subtitle import (
    SubtitleSegmentInput,
    SubtitleStyle,
    GenerateSRTRequest,
    BurnSubtitleRequest,
    ExportOriginalRequest,
)
from app.api.subtitle import execute_burn_subtitle, execute_export_original
from app.api.tts import SynthesizeRequest, SynthesizeResponse, synthesize as tts_synthesize
from app.models.auto_edit import (
    AutoEditPlanRequest,
    AutoEditPlanResponse,
    AutoEditPlanSessionResponse,
    AutoEditRealizeRequest,
    AutoEditRealizeResponse,
    Plan,
    SegmentPlan,
)

from app.utils.ffprobe_utils import probe_duration

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/auto-edit", tags=["auto-edit"])

_PLAN_STREAM_SESSIONS: Dict[str, AutoEditPlanRequest] = {}
_PLAN_STREAM_CREATED_AT: Dict[str, float] = {}
_PLAN_STREAM_EXPIRE_SEC = 10 * 60



@dataclass
class ClipCandidate:
    id: str
    video_id: str
    start_time: float
    end_time: float
    duration: float

def _cleanup_expired_plan_sessions() -> None:
    now = time.time()
    expired = [
        sid
        for sid, created_at in _PLAN_STREAM_CREATED_AT.items()
        if now - created_at > _PLAN_STREAM_EXPIRE_SEC
    ]
    for sid in expired:
        _PLAN_STREAM_CREATED_AT.pop(sid, None)
        _PLAN_STREAM_SESSIONS.pop(sid, None)


def _build_sse_event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


SYSTEM_PROMPT = """你是一位专业的视频剪辑规划师。
现在需要你基于给定的视频素材（可能包含 ASR 台词与/或 VLM 画面描述；有些素材可能没有 ASR），
结合用户的创作诉求，生成「自动一键成片」的结构化剪辑方案（Plan）。

重要约束（必须严格遵守）：
- 上文素材列表中，每一行都包含形如 [clip_id=XXXXX] 的片段 ID。
- 你在 Plan.clip_group[*].clip_id 和 Plan.selected_clip_ids 中使用的 clip_id
  必须从这些已有的 clip_id 中“原样拷贝”，绝对禁止凭空创造新的 clip_id，
  比如 "clip_001"、"seg_1" 之类都不允许。

其它要求：
- 你只输出 JSON，不要任何解释或多余文字。
- JSON 顶层结构为 {"plans": [Plan, ...]}，其中 Plan 结构严格遵循下面 schema。
- 所有时间单位均为秒（float）。
- 请确保 segments 能首尾相接，整体时长尽量接近 target_duration_sec。
- 当某些片段缺少 ASR 时，你必须主要依赖 VLM 画面描述进行语义匹配与剪辑（必要时在 constraints.match_strategy 选择 vlm）。
- 如果信息不足，可以适度补全文案，但要与已有 ASR/VLM 内容风格一致。
"""


def _build_user_message(context: str, req: AutoEditPlanRequest) -> str:
    parts: list[str] = []
    parts.append("【用户需求】")
    parts.append(req.user_prompt.strip())
    parts.append("")
    parts.append("【生成要求】")
    parts.append(f"- 模式：{req.mode}")
    if req.target_duration_sec:
        parts.append(f"- 目标时长：约 {req.target_duration_sec} 秒")
    parts.append(f"- 方案数量：{req.num_plans} 个")
    parts.append(f"- 允许跨视频重排：{req.allow_cross_video}")
    parts.append(f"- 字幕策略：{req.subtitle_policy}")
    parts.append(f"- 转场策略：{req.transition_policy}")
    parts.append(f"- BGM 策略：{req.bgm_policy}")
    parts.append("")
    parts.append("【可用素材简要信息】")
    parts.append(context)
    return "\n".join(parts)


SCHEMA_HINT = """
请严格生成符合下述结构的 JSON：

{
  "plans": [
    {
      "plan_id": "string",
      "title": "string",
      "summary": "string",
      "mode": "auto | voiceover | original",
      "target_duration_sec": 60,
      "estimated_duration_sec": 61.2,
      "chapters": [],
      "segments": [
        {
          "id": "seg_1",
          "chapter_id": null,
          "order": 1,
          "clip_group": [
            { "clip_id": "xxx", "video_id": "v1", "weight": 0.8 }
          ],
          "selected_clip_ids": ["xxx"],
          "start_time_sec": 0.0,
          "end_time_sec": 3.2,
          "audio_mode": "original | tts | mute",
          "subtitle": {
            "strategy": "auto | asr | rewrite | none",
            "text": "本段对应的文案",
            "source": "asr | asr+vlm | llm | vlm | user",
            "timing_hint": { "start": 0.0, "end": 3.2 }
          },
          "transition": {
            "type": "hard_cut | cross_dissolve | fade_in | fade_out",
            "duration_sec": 0.3
          }
        }
      ],
      "bgm": {
        "enabled": true,
        "source": "library | user | ai",
        "track_id": "bgm_001",
        "volume_db": -12.0,
        "loop": true,
        "fade_in_sec": 0.8,
        "fade_out_sec": 1.0
      },
      "constraints": {
        "max_clip_per_segment": 3,
        "match_strategy": "asr+vlm | asr | vlm",
        "respect_user_video_order": false
      },
      "keep_flags": {
        "clips": false,
        "subtitles": false,
        "transitions": false,
        "bgm": false
      }
    }
  ]
}
"""


def _extract_json_array(raw: str) -> str:
    """从可能含有思维链/Markdown 的返回中，提取 JSON 文本。"""
    import re

    raw = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
    if "```" in raw:
        parts = raw.split("```")
        # 取中间部分作为代码块
        if len(parts) > 1:
            candidate = parts[1]
            if candidate.lstrip().startswith("json"):
                candidate = candidate.split("\n", 1)[1] if "\n" in candidate else ""
            raw = candidate.strip() or raw
    # 兜底：从第一个 { 到最后一个 } 的范围
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start : end + 1]
    return raw


async def _call_llm_for_plans(
    cfg: dict,
    context: str,
    req: AutoEditPlanRequest,
) -> AutoEditPlanResponse:
    llm = LLMClient(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        temperature=cfg["temperature"],
        max_tokens=cfg["max_tokens"],
        timeout=3600,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _build_user_message(context, req) + "\n\n" + SCHEMA_HINT,
        },
    ]

    raw = await llm.chat(messages)
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=502, detail="LLM 返回内容为空")
    logger.debug("auto_edit raw LLM output: %s", raw[:500])
    cleaned = _extract_json_array(raw)

    # 尝试直接解析 JSON
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # 尝试使用 json_repair 做一次修复
        try:
            from json_repair import repair_json

            data = json.loads(repair_json(cleaned))
            logger.warning("auto_edit LLM JSON 修复成功")
        except Exception as e:
            logger.error("auto_edit JSON 解析失败: %s", e)
            raise HTTPException(status_code=502, detail="LLM 返回的 JSON 无法解析")

    try:
        return AutoEditPlanResponse(**data)
    except ValidationError as e:
        logger.error("auto_edit Plan 验证失败: %s", e)
        raise HTTPException(status_code=502, detail="LLM 返回的 Plan 结构不符合预期")


@router.post("/plan", response_model=AutoEditPlanResponse)
async def generate_auto_edit_plan(req: AutoEditPlanRequest) -> AutoEditPlanResponse:
    """
    基于已处理完成的视频素材（clips + ASR + VLM），生成自动成片的结构化方案（Plan）。

    当前阶段：
    - 不做转场与 BGM 的真实渲染，仅在 Plan 中占位。
    - 不支持复杂的 keep_flags/prev_plan 逻辑，只做最简单的全量新方案。
    """
    if not req.video_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个视频")

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cfg = await LLMConfig.get_llm_params_with_defaults(
                db,
                base_url_key="llm_base_url",
                api_key_key="llm_api_key",
                model_key="llm_model",
                fallback_model_key="vlm_model",
                default_temperature=0.7,
                default_max_tokens=20480,
            )
            context = await _build_video_context_with_recall(
                db,
                req.video_ids,
                user_prompt=req.user_prompt,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("auto_edit 读取上下文失败: %s", e)
        raise HTTPException(status_code=500, detail="读取素材上下文失败")

    return await _call_llm_for_plans(cfg, context, req)


@router.post("/plan/session", response_model=AutoEditPlanSessionResponse)
async def create_auto_edit_plan_session(req: AutoEditPlanRequest) -> AutoEditPlanSessionResponse:
    if not req.video_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个视频")
    _cleanup_expired_plan_sessions()
    session_id = uuid.uuid4().hex
    _PLAN_STREAM_SESSIONS[session_id] = req
    _PLAN_STREAM_CREATED_AT[session_id] = time.time()
    return AutoEditPlanSessionResponse(
        session_id=session_id,
        stream_url=f"/api/auto-edit/plan/stream?session_id={session_id}",
    )


@router.get("/plan/stream")
async def stream_auto_edit_plan(session_id: str) -> StreamingResponse:
    _cleanup_expired_plan_sessions()
    # 注意：SSE(EventSource) 在网络抖动时会自动重连；如果这里立刻 pop 掉 session，
    # 重连会直接 404，前端会误以为“转发/连接不正常”。
    # 因此改为：流结束（或异常结束）后再清理 session。
    req = _PLAN_STREAM_SESSIONS.get(session_id)
    if req is None:
        raise HTTPException(status_code=404, detail="规划会话不存在或已过期")

    async def event_generator():
        try:
            # 发送一个轻量事件帮助部分代理/浏览器尽快 flush headers
            yield ": ok\n\n"
            yield _build_sse_event("progress", {"stage": "init", "message": "开始读取模型配置"})
            await asyncio.sleep(0)
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    db.row_factory = aiosqlite.Row
                    cfg = await LLMConfig.get_llm_params_with_defaults(
                        db,
                        base_url_key="llm_base_url",
                        api_key_key="llm_api_key",
                        model_key="llm_model",
                        fallback_model_key="vlm_model",
                        default_temperature=0.7,
                        default_max_tokens=20480,
                    )
                    yield _build_sse_event("progress", {"stage": "context", "message": "正在构建素材上下文"})
                    context = await _build_video_context_with_recall(
                        db,
                        req.video_ids,
                        user_prompt=req.user_prompt,
                    )
            except ValueError as e:
                yield _build_sse_event("failed", {"message": str(e)})
                return
            except Exception as e:
                logger.error("auto_edit stream 读取上下文失败: %s", e)
                yield _build_sse_event("failed", {"message": "读取素材上下文失败"})
                return

            yield _build_sse_event("progress", {"stage": "llm", "message": "LLM 正在生成候选方案"})
            plan_res = await _call_llm_for_plans(cfg, context, req)
            yield _build_sse_event(
                "progress",
                {"stage": "done", "message": f"生成完成，共 {len(plan_res.plans)} 个方案"},
            )
            yield _build_sse_event("result", plan_res.model_dump())
        except HTTPException as e:
            msg = e.detail if isinstance(e.detail, str) else "生成方案失败"
            yield _build_sse_event("failed", {"message": msg})
        except Exception as e:
            logger.error("auto_edit stream 未知异常: %s", e)
            yield _build_sse_event("failed", {"message": "生成方案失败"})
        finally:
            _PLAN_STREAM_SESSIONS.pop(session_id, None)
            _PLAN_STREAM_CREATED_AT.pop(session_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # 让反向代理不要缓冲 SSE（即使你以后上了 Nginx/Caddy 也更稳）
            "X-Accel-Buffering": "no",
        },
    )


# ────────────────────────────────────────────────────────────
# Plan 实现：转换为字幕成片管线
# ────────────────────────────────────────────────────────────

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_BURNED_VIDEOS_DIR = os.path.join(_BACKEND_DIR, "storage", "burned_videos")
_BGM_LIBRARY_DIR = os.path.join(_BACKEND_DIR, "storage", "bgm")
_BGM_MANIFEST_PATH = os.path.join(_BGM_LIBRARY_DIR, "bgm_manifest.json")
_BGM_EXTENSIONS = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")


def _run_ffmpeg(args: List[str], desc: str = "") -> None:
    cmd = ["ffmpeg", "-y"] + args
    logger.info("FFmpeg%s: %s", f" [{desc}]" if desc else "", " ".join(cmd))
    res = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=3600,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"FFmpeg 失败 [{desc}]\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stderr: {res.stderr.decode(errors='replace')[-2000:]}"
        )


def _resolve_bgm_path(track_id: Optional[str]) -> Optional[str]:
    if not track_id:
        return None
    raw = track_id.strip()
    if not raw:
        return None

    candidates: List[str] = []
    # 1) 绝对路径
    if os.path.isabs(raw):
        candidates.append(raw)
    # 2) 相对 backend 根目录
    candidates.append(os.path.join(_BACKEND_DIR, raw))
    # 3) 约定目录 storage/bgm
    candidates.append(os.path.join(_BGM_LIBRARY_DIR, raw))

    for p in candidates:
        ap = os.path.abspath(p)
        if os.path.isfile(ap):
            return ap
    return None


def _list_local_bgm_files() -> List[str]:
    if not os.path.isdir(_BGM_LIBRARY_DIR):
        return []
    bgm_files: List[str] = []
    for root, _, files in os.walk(_BGM_LIBRARY_DIR):
        for name in files:
            if name.lower().endswith(_BGM_EXTENSIONS):
                bgm_files.append(os.path.join(root, name))
    return sorted(bgm_files)


def _load_bgm_manifest() -> List[dict]:
    if not os.path.isfile(_BGM_MANIFEST_PATH):
        return []
    try:
        with open(_BGM_MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict) and isinstance(data.get("tracks"), list):
            return [x for x in data["tracks"] if isinstance(x, dict)]
    except Exception as e:
        logger.warning("BGM manifest 解析失败: %s", e)
    return []


def _mood_keywords() -> Dict[str, List[str]]:
    return {
        "happy": ["搞笑", "轻快", "欢乐", "活泼", "轻松", "funny", "happy", "vlog"],
        "calm": ["治愈", "温柔", "舒缓", "安静", "平静", "calm", "soft", "chill"],
        "epic": ["燃", "震撼", "史诗", "热血", "高潮", "epic", "power", "cinematic"],
        "sad": ["伤感", "遗憾", "催泪", "低落", "sad", "melancholy", "piano"],
        "tech": ["科技", "未来", "数码", "赛博", "tech", "electro", "synth"],
    }


def _plan_text(plan: Plan) -> str:
    parts: List[str] = [plan.title or "", plan.summary or ""]
    for seg in plan.segments:
        if seg.subtitle and seg.subtitle.text:
            parts.append(seg.subtitle.text)
    return " ".join(parts).lower()


def _detect_target_mood(text: str) -> Tuple[str, int]:
    mood_keywords = _mood_keywords()
    mood_score: Dict[str, int] = {k: 0 for k in mood_keywords.keys()}
    for mood, words in mood_keywords.items():
        for w in words:
            if w in text:
                mood_score[mood] += 1
    target_mood = max(mood_score, key=lambda k: mood_score[k])
    return target_mood, mood_score[target_mood]


def _normalize_mood(mood: str) -> str:
    raw = (mood or "").strip().lower()
    mapping = {
        "欢乐": "happy",
        "轻快": "happy",
        "治愈": "calm",
        "平静": "calm",
        "燃": "epic",
        "史诗": "epic",
        "伤感": "sad",
        "科技": "tech",
    }
    return mapping.get(raw, raw)


def _choose_bgm_from_manifest(plan: Plan) -> Optional[str]:
    manifest = _load_bgm_manifest()
    if not manifest:
        return None

    text = _plan_text(plan)
    target_mood, mood_signal = _detect_target_mood(text)
    preferred_bpm: Optional[float] = None
    # 根据风格粗略推断目标 BPM（可后续做成配置）
    if target_mood == "happy":
        preferred_bpm = 120
    elif target_mood == "epic":
        preferred_bpm = 132
    elif target_mood == "calm":
        preferred_bpm = 85
    elif target_mood == "sad":
        preferred_bpm = 78
    elif target_mood == "tech":
        preferred_bpm = 128

    best_score = -10**9
    best_path: Optional[str] = None
    mood_keywords = _mood_keywords()
    for item in manifest:
        path_val = str(item.get("path") or "").strip()
        if not path_val:
            continue
        resolved = _resolve_bgm_path(path_val)
        if not resolved:
            continue

        score = 0
        title = str(item.get("title") or "").lower()
        tags = [str(t).lower() for t in (item.get("tags") or []) if str(t).strip()]
        mood = _normalize_mood(str(item.get("mood") or ""))
        bpm_raw = item.get("bpm")
        bpm = None
        try:
            bpm = float(bpm_raw) if bpm_raw is not None else None
        except Exception:
            bpm = None

        # 情绪字段强匹配
        if mood and mood == target_mood:
            score += 12
        # tags/title 命中情绪关键词
        if mood_signal > 0:
            for token in mood_keywords.get(target_mood, []):
                tk = token.lower()
                if tk and (tk in title or any(tk in t for t in tags)):
                    score += 4
        # 文本 token 与 tags/title 的宽松匹配
        text_tokens = [t for t in re.split(r"[^a-z0-9\u4e00-\u9fff]+", text) if len(t) >= 2]
        for tk in text_tokens[:30]:
            if tk in title or any(tk in t for t in tags):
                score += 1
        # BPM 接近度奖励
        if preferred_bpm is not None and bpm is not None:
            score += max(0, int(8 - abs(preferred_bpm - bpm) / 8))

        if score > best_score:
            best_score = score
            best_path = resolved

    return best_path


def _choose_auto_bgm_track(plan: Plan) -> Optional[str]:
    """
    最小可用自动选曲：
    - 从 storage/bgm 扫描本地音频
    - 根据 plan 标题/摘要/字幕文本关键词做简单打分
    - 选最高分；无关键词命中则回退第一个文件
    """
    # 优先使用 manifest 元数据选曲
    from_manifest = _choose_bgm_from_manifest(plan)
    if from_manifest:
        return from_manifest

    candidates = _list_local_bgm_files()
    if not candidates:
        return None

    text = _plan_text(plan)
    target_mood, mood_signal = _detect_target_mood(text)
    mood_keywords = _mood_keywords()
    has_signal = mood_signal > 0

    ranked: List[Tuple[int, str]] = []
    for p in candidates:
        name = os.path.basename(p).lower()
        name_tokens = set(re.split(r"[^a-z0-9\u4e00-\u9fff]+", name))
        score = 0
        if has_signal:
            for token in mood_keywords.get(target_mood, []):
                if token and token.lower() in name:
                    score += 3
        # 通用 token 命中（标题摘要词）
        for token in re.split(r"[^a-z0-9\u4e00-\u9fff]+", text):
            if token and len(token) >= 2 and token in name_tokens:
                score += 1
        ranked.append((score, p))
    ranked.sort(key=lambda x: x[0], reverse=True)

    best_score, best_path = ranked[0]
    if best_score <= 0:
        return candidates[0]
    return best_path


def _mix_bgm_for_video(
    video_path: str,
    bgm_path: str,
    volume_db: float,
    loop: bool,
    fade_in_sec: float,
    fade_out_sec: float,
) -> str:
    video_dur = probe_duration(video_path)
    if video_dur <= 0:
        raise RuntimeError("无法探测成片时长，跳过 BGM 混音")

    fade_in = max(0.0, float(fade_in_sec or 0.0))
    fade_out = max(0.0, float(fade_out_sec or 0.0))
    fade_out_start = max(0.0, video_dur - fade_out)

    out_filename = f"{os.path.splitext(os.path.basename(video_path))[0]}_bgm_{uuid.uuid4().hex[:6]}.mp4"
    out_path = os.path.join(_BURNED_VIDEOS_DIR, out_filename)

    # BGM 音轨处理：音量 + 淡入 + 淡出（按总时长）
    bgm_filter_parts = [f"volume={float(volume_db):.2f}dB"]
    if fade_in > 0:
        bgm_filter_parts.append(f"afade=t=in:st=0:d={fade_in:.3f}")
    if fade_out > 0:
        bgm_filter_parts.append(f"afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}")
    bgm_filter = ",".join(bgm_filter_parts)

    if loop:
        # loop 背景音乐到视频时长，再与原声混合
        filter_complex = (
            f"[1:a]{bgm_filter},aloop=loop=-1:size=2000000000,atrim=0:{video_dur:.3f}[bgm];"
            f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        args = [
            "-i",
            video_path,
            "-i",
            bgm_path,
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            out_path,
        ]
    else:
        # 不 loop 时，BGM 按原长度参与混音
        filter_complex = (
            f"[1:a]{bgm_filter}[bgm];"
            f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        args = [
            "-i",
            video_path,
            "-i",
            bgm_path,
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            out_path,
        ]

    _run_ffmpeg(args, desc="auto-edit mix bgm")
    return out_path


def _apply_bgm_postprocess_if_needed(plan: Plan, filename: str, url: str) -> Tuple[str, str]:
    bgm = plan.bgm
    if not bgm or not bgm.enabled:
        return filename, url

    src_video_path = os.path.join(_BURNED_VIDEOS_DIR, filename)
    if not os.path.isfile(src_video_path):
        logger.warning("BGM 混音跳过：成片文件不存在 %s", src_video_path)
        return filename, url

    bgm_path = _resolve_bgm_path(bgm.track_id)
    if not bgm_path and bgm.source in ("library", "ai"):
        bgm_path = _choose_auto_bgm_track(plan)
        if bgm_path:
            logger.info("BGM 自动选曲命中: %s", bgm_path)
    if not bgm_path:
        logger.warning("BGM 混音跳过：无法解析 track_id=%s", bgm.track_id)
        return filename, url

    try:
        mixed_path = _mix_bgm_for_video(
            video_path=src_video_path,
            bgm_path=bgm_path,
            volume_db=bgm.volume_db,
            loop=bgm.loop,
            fade_in_sec=bgm.fade_in_sec,
            fade_out_sec=bgm.fade_out_sec,
        )
    except Exception as e:
        logger.error("BGM 混音失败，已回退原成片: %s", e)
        return filename, url

    mixed_filename = os.path.basename(mixed_path)
    return mixed_filename, f"/storage/burned_videos/{mixed_filename}"


def _collect_plan_clip_ids(plan: Plan) -> List[str]:
    ids: List[str] = []
    for seg in plan.segments:
        ids.extend([cid for cid in seg.selected_clip_ids if cid])
        ids.extend([ref.clip_id for ref in seg.clip_group if ref.clip_id])
    return list(dict.fromkeys(ids))


def _pick_fallback_clip(
    seg: SegmentPlan,
    preferred_video_ids: List[str],
    candidates_by_video: Dict[str, List[ClipCandidate]],
    all_candidates: List[ClipCandidate],
) -> Optional[str]:
    target_start = float(seg.start_time_sec or 0.0)
    target_end = float(seg.end_time_sec or target_start)
    if target_end <= target_start:
        target_end = target_start + 1.0

    pool: List[ClipCandidate] = []
    for vid in preferred_video_ids:
        pool.extend(candidates_by_video.get(vid, []))
    if not pool:
        pool = all_candidates
    if not pool:
        return None

    target_center = (target_start + target_end) / 2.0

    def _score(c: ClipCandidate) -> Tuple[float, float]:
        overlap = max(0.0, min(c.end_time, target_end) - max(c.start_time, target_start))
        cand_center = (c.start_time + c.end_time) / 2.0
        center_distance = abs(cand_center - target_center)
        # 先最大化 overlap，再最小化中心点距离
        return overlap, -center_distance

    chosen = max(pool, key=_score)
    return chosen.id


async def _segments_from_plan(
    plan: Plan,
    valid_clip_ids: Set[str],
    candidates_by_video: Dict[str, List[ClipCandidate]],
    all_candidates: List[ClipCandidate],
) -> List[SubtitleSegmentInput]:
    """
    将 Plan.segments 转换为现有 SubtitleSegmentInput 列表。
    规则（Phase 2 最小版）：
    - 只取每个 segment.selected_clip_ids 的第一个 clip 作为主 clip_id
    - 如果为空，则回退到 clip_group[0].clip_id
    - 若 audio_mode == 'tts'，直接用段落文案调用一次 TTS 合成
    - 若 selected_clip_ids 无效，则按 segment 时间窗自动回退到最接近的素材片段
    """
    seg_inputs: List[SubtitleSegmentInput] = []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT value FROM config WHERE key = ?", ("tts_concurrency",)) as cur:
            row = await cur.fetchone()
        tts_concurrency_raw = (row["value"] if row else "3") if isinstance(row, aiosqlite.Row) else (row[0] if row else "3")

    def _parse_positive_int(raw: str, default: int, min_v: int = 1, max_v: int = 64) -> int:
        try:
            v = int(str(raw or "").strip())
        except Exception:
            v = default
        v = max(min_v, v)
        v = min(max_v, v)
        return v

    tts_concurrency = _parse_positive_int(str(tts_concurrency_raw), default=3, min_v=1, max_v=16)
    sem = asyncio.Semaphore(tts_concurrency)

    async def _maybe_tts(seg: SegmentPlan) -> Optional[str]:
        if seg.audio_mode != "tts" or not seg.subtitle or not seg.subtitle.text:
            return None
        async with sem:
            tts_req = SynthesizeRequest(text=seg.subtitle.text)
            tts_res: SynthesizeResponse = await tts_synthesize(tts_req)
            return tts_res.filename

    tts_filenames = await asyncio.gather(*[_maybe_tts(seg) for seg in plan.segments])

    for seg, tts_filename in zip(plan.segments, tts_filenames):
        selected_valid = [cid for cid in seg.selected_clip_ids if cid in valid_clip_ids]
        group_valid = [ref.clip_id for ref in seg.clip_group if ref.clip_id in valid_clip_ids]
        preferred_video_ids = list(
            dict.fromkeys([ref.video_id for ref in seg.clip_group if ref.video_id])
        )

        primary_clip = (selected_valid[0] if selected_valid else None) or (
            group_valid[0] if group_valid else None
        )
        if not primary_clip:
            primary_clip = _pick_fallback_clip(
                seg=seg,
                preferred_video_ids=preferred_video_ids,
                candidates_by_video=candidates_by_video,
                all_candidates=all_candidates,
            )
        if not primary_clip:
            logger.warning("segment %s 缺少可用 clip，跳过", seg.id)
            continue

        seg_inputs.append(
            SubtitleSegmentInput(
                copy_text=seg.subtitle.text if seg.subtitle and seg.subtitle.text else "",
                clip_id=primary_clip,
                clip_ids=selected_valid or group_valid or [primary_clip],
                tts_filename=tts_filename,
            )
        )
    return seg_inputs


@router.post("/realize", response_model=AutoEditRealizeResponse)
async def realize_auto_edit_plan(
    req: AutoEditRealizeRequest,
    request: Request,
) -> AutoEditRealizeResponse:
    """
    将一个 Plan 实际转为成片：
    - voiceover 模式：TTS + 字幕 + burn 管线
    - original 模式：保留原声，按段落平均切字幕，调用 export_original

    当前版本：
    - 忽略 Plan.keep_flags / BGM / transition，仅打通基础链路。
    """
    if await request.is_disconnected():
        raise HTTPException(status_code=400, detail="客户端已断开连接")
    plan = req.plan
    if not plan.segments:
        raise HTTPException(status_code=400, detail="Plan 中没有任何 segments")

    requested_clip_ids = _collect_plan_clip_ids(plan)
    valid_clip_ids: Set[str] = set()
    clip_id_to_video: Dict[str, str] = {}
    candidate_videos: Set[str] = set()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # 1) clip_id 预检：友好返回无效 ID 列表
        if requested_clip_ids:
            placeholders = ",".join(["?"] * len(requested_clip_ids))
            async with db.execute(
                f"SELECT id, video_id FROM clips WHERE id IN ({placeholders})",
                requested_clip_ids,
            ) as cur:
                rows = await cur.fetchall()
            for row in rows:
                cid = str(row["id"])
                valid_clip_ids.add(cid)
                clip_id_to_video[cid] = str(row["video_id"])

        invalid_clip_ids = [cid for cid in requested_clip_ids if cid not in valid_clip_ids]

        # 2) 构造回退候选池（优先 segment.clip_group 的 video_id，其次已命中 clip 的 video_id）
        for seg in plan.segments:
            for ref in seg.clip_group:
                if ref.video_id:
                    candidate_videos.add(ref.video_id)
        for cid in valid_clip_ids:
            vid = clip_id_to_video.get(cid)
            if vid:
                candidate_videos.add(vid)

        candidates: List[ClipCandidate] = []
        candidates_by_video: Dict[str, List[ClipCandidate]] = {}
        if candidate_videos:
            placeholders = ",".join(["?"] * len(candidate_videos))
            async with db.execute(
                f"SELECT id, video_id, start_time, end_time, duration FROM clips "
                f"WHERE video_id IN ({placeholders})",
                list(candidate_videos),
            ) as cur:
                rows = await cur.fetchall()
            for row in rows:
                cand = ClipCandidate(
                    id=str(row["id"]),
                    video_id=str(row["video_id"]),
                    start_time=float(row["start_time"] or 0.0),
                    end_time=float(row["end_time"] or 0.0),
                    duration=float(row["duration"] or 0.0),
                )
                candidates.append(cand)
                candidates_by_video.setdefault(cand.video_id, []).append(cand)

    seg_inputs = await _segments_from_plan(
        plan=plan,
        valid_clip_ids=valid_clip_ids,
        candidates_by_video=candidates_by_video,
        all_candidates=candidates,
    )
    if not seg_inputs:
        detail = {
            "message": "Plan 转换后没有有效片段，请检查计划中的 clip_id 是否有效。",
            "invalid_clip_ids": invalid_clip_ids,
        }
        raise HTTPException(status_code=400, detail=detail)

    if invalid_clip_ids:
        logger.warning("realize 检测到无效 clip_id，已尝试自动回退: %s", invalid_clip_ids)

    project_name = req.project_name or f"auto_edit_{plan.plan_id}"

    # 字幕样式：优先使用前端传入，否则回退默认值
    style = req.style or SubtitleStyle()

    # voiceover / auto -> 统一走配音管线（若某段未生成 TTS，会回落到 clip 时长）
    if plan.mode in ("auto", "voiceover"):
        from app.api.subtitle import generate_srt as generate_srt_route

        if req.include_subtitle:
            if await request.is_disconnected():
                raise HTTPException(status_code=400, detail="客户端已断开连接")
            srt_req = GenerateSRTRequest(segments=seg_inputs, style=style, use_tts_timing=True)
            srt_res = await generate_srt_route(srt_req)
            burn_req = BurnSubtitleRequest(
                segments=seg_inputs,
                srt_content=srt_res.srt_content,
                style=style,
                project_name=project_name,
            )
            burn_res = await execute_burn_subtitle(burn_req)
        else:
            if await request.is_disconnected():
                raise HTTPException(status_code=400, detail="客户端已断开连接")
            export_req = ExportOriginalRequest(
                segments=seg_inputs,
                style=style,
                project_name=project_name,
                include_subtitle=False,
                normalize_audio=True,
            )
            export_res = await execute_export_original(export_req)
            burn_res = {
                "filename": export_res.get("filename"),
                "url": export_res.get("url"),
            }
        if await request.is_disconnected():
            raise HTTPException(status_code=400, detail="客户端已断开连接")
        final_filename, final_url = await run_heavy(
            _apply_bgm_postprocess_if_needed,
            plan,
            burn_res["filename"],
            burn_res["url"],
        )
        return AutoEditRealizeResponse(mode="voiceover", filename=final_filename, url=final_url)

    export_req = ExportOriginalRequest(
        segments=seg_inputs,
        style=style,
        project_name=project_name,
        include_subtitle=req.include_subtitle,
        normalize_audio=True,
    )
    if await request.is_disconnected():
        raise HTTPException(status_code=400, detail="客户端已断开连接")
    res = await execute_export_original(export_req)
    if await request.is_disconnected():
        raise HTTPException(status_code=400, detail="客户端已断开连接")
    final_filename, final_url = await run_heavy(
        _apply_bgm_postprocess_if_needed,
        plan,
        res.get("filename") or "",
        res.get("url") or "",
    )
    return AutoEditRealizeResponse(mode="original", filename=final_filename, url=final_url)

