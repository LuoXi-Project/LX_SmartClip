"""混剪模式二：为成片片段批量生成 LLM 旁白文案（非 ASR 原文）。"""
from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite

from app.api.copy_gen import _build_video_context_with_recall
from app.core.llm import LLMClient
from app.core.llm.response_utils import extract_json_object
from app.models.auto_edit import Plan, SegmentPlan, SubtitlePlan

logger = logging.getLogger(__name__)


def _segment_duration_sec(seg: SegmentPlan) -> float:
    od = seg.override_duration_sec
    if od is not None and od > 0:
        return float(od)
    return max(0.0, float(seg.end_time_sec) - float(seg.start_time_sec))


def _build_segment_manifest(segments: list[SegmentPlan]) -> tuple[list[SegmentPlan], str]:
    active = [s for s in segments if not s.exclude_from_output]
    lines: list[str] = []
    for i, seg in enumerate(active):
        cid = seg.selected_clip_ids[0] if seg.selected_clip_ids else "?"
        dur = _segment_duration_sec(seg)
        hint = (seg.subtitle.text or "").strip()[:120] if seg.subtitle else ""
        lines.append(
            f"片段 {i}：clip_id={cid}，画面时长约 {dur:.1f}s"
            + (f"，素材摘要：{hint}" if hint else "")
        )
    return active, "\n".join(lines)


async def apply_llm_scripts_to_mute_plan(
    *,
    plan: Plan,
    db: aiosqlite.Connection,
    video_ids: list[str],
    user_prompt: str,
    llm_cfg: dict[str, Any],
) -> Plan:
    """
    为 mute_all + AI 配音（生成文案）模式填充每段 subtitle.text。
    要求 user_prompt 非空；失败时抛出 RuntimeError。
    """
    up = (user_prompt or "").strip()
    if not up:
        raise ValueError("AI 生成文案需要填写剪辑诉求")

    active, manifest = _build_segment_manifest(plan.segments)
    n = len(active)
    if n == 0:
        return plan

    context = await _build_video_context_with_recall(db, video_ids, user_prompt=up)

    llm = LLMClient(
        base_url=llm_cfg["base_url"],
        api_key=llm_cfg["api_key"],
        model=llm_cfg["model"],
        temperature=float(llm_cfg.get("temperature") or 0.75),
        max_tokens=min(int(llm_cfg.get("max_tokens") or 8192), 65536),
        timeout=3600,
    )
    sys = (
        "你是短视频混剪配音文案师。根据素材 ASR/VLM 与用户诉求，为每个成片画面片段撰写独立旁白。"
        "旁白需自然口语化、适合 TTS 朗读，勿照抄 ASR 原句，可重组信息与情绪。"
        "只输出 JSON，不要解释。格式："
        '{"scripts":[{"index":0,"text":"旁白句"}, ...]}'
        f"scripts 长度必须恰好为 {n}，index 从 0 到 {n - 1} 连续。"
    )
    user = (
        f"【用户诉求】\n{up}\n\n"
        f"【素材识别内容】\n{context}\n\n"
        f"【成片片段清单（按播放顺序）】\n{manifest}\n\n"
        f"请为以上 {n} 个片段各写一句旁白（可略长，系统会按画面时长对齐 TTS）。"
    )
    raw = await llm.chat([{"role": "system", "content": sys}, {"role": "user", "content": user}])
    cleaned = extract_json_object(raw if isinstance(raw, str) else "")
    try:
        data = json.loads(cleaned)
    except Exception as e:
        raise RuntimeError(f"LLM 返回的文案 JSON 无法解析: {e}") from e

    scripts_raw = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts_raw, list) or not scripts_raw:
        raise RuntimeError("LLM 未返回有效的 scripts 数组")

    by_index: dict[int, str] = {}
    fallback_lines: list[str] = []
    for item in scripts_raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        if "index" in item:
            try:
                by_index[int(item["index"])] = text
            except (TypeError, ValueError):
                fallback_lines.append(text)
        else:
            fallback_lines.append(text)

    texts: list[str] = []
    for i in range(n):
        if i in by_index:
            texts.append(by_index[i])
        elif i < len(fallback_lines):
            texts.append(fallback_lines[i])
        elif fallback_lines:
            texts.append(fallback_lines[i % len(fallback_lines)])
        else:
            texts.append(active[i].subtitle.text if active[i].subtitle else "（旁白）")

    if len(texts) < n and fallback_lines:
        while len(texts) < n:
            texts.append(fallback_lines[len(texts) % len(fallback_lines)])

    new_segments: list[SegmentPlan] = []
    active_idx = 0
    for seg in plan.segments:
        if seg.exclude_from_output:
            new_segments.append(seg)
            continue
        text = texts[active_idx] if active_idx < len(texts) else (seg.subtitle.text or "（旁白）")
        active_idx += 1
        sub = seg.subtitle.model_copy(
            update={
                "text": text,
                "strategy": "rewrite",
                "source": "llm",
            }
        )
        new_segments.append(
            seg.model_copy(
                update={
                    "audio_mode": "tts",
                    "subtitle": sub,
                }
            )
        )

    summary = (
        (plan.summary or "")
        + f" 配音文案：AI 根据诉求生成 {active_idx} 段旁白（非 ASR 原文）。"
    )
    return plan.model_copy(update={"segments": new_segments, "summary": summary})
