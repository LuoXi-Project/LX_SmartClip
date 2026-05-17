"""混剪模式二：为成片片段批量生成 LLM 旁白文案（非 ASR 原文）。"""
from __future__ import annotations

import json
import logging
from typing import Any

import aiosqlite

from app.api.copy_gen import _build_video_context_with_recall
from app.core.auto_edit.duration_hint import resolve_voiceover_target_duration_sec
from app.core.auto_edit.mix_edit_tts_balance import (
    CHARS_PER_SEC_TTS,
    SegmentTtsBudget,
    clamp_script_texts_to_budgets,
    compute_mix_tts_script_budgets,
    estimate_tts_duration_sec,
)
from app.core.llm import LLMClient
from app.core.llm.response_utils import extract_json_object
from app.models.auto_edit import Plan, SegmentPlan, SubtitlePlan

logger = logging.getLogger(__name__)


def _build_segment_manifest_and_brief(
    segments: list[SegmentPlan],
    *,
    target_duration_sec: float | None,
) -> tuple[list[SegmentPlan], str, str, list[SegmentTtsBudget]]:
    active = [s for s in segments if not s.exclude_from_output]
    budgets, meta = compute_mix_tts_script_budgets(
        segments, target_duration_sec=target_duration_sec
    )

    lines: list[str] = []
    for b in budgets:
        hint = ""
        if active[b.index].subtitle and active[b.index].subtitle.text:
            hint = (active[b.index].subtitle.text or "").strip()[:100]
        lines.append(
            f"片段 {b.index}：clip_id={b.clip_id}\n"
            f"  · 画面素材约 {b.video_sec:.1f}s（仅作画面参考，**不决定成片时长**）\n"
            f"  · 旁白字数上限 **{b.max_chars} 字**（TTS 朗读约 ≤{b.max_tts_sec:.1f}s，**成片该段时长≈TTS**）"
            + (f"\n  · 画面摘要：{hint}" if hint else "")
        )
    manifest = "\n\n".join(lines)

    cps = float(meta.get("chars_per_sec_tts") or CHARS_PER_SEC_TTS)
    total_video = float(meta.get("total_video_sec") or 0)
    total_chars = int(meta.get("total_char_budget") or 0)
    total_tts = float(meta.get("total_tts_budget_sec") or 0)
    target = meta.get("target_duration_sec")

    brief_parts = [
        "【成片时长机制 · 必读】",
        "本混剪为 **TTS 配音驱动时间轴**：每条旁白朗读多久，成片该段就是多久。",
        "画面素材比配音短时，系统会循环/定格画面，观感差；**必须通过控制旁白字数控制成片时长**，不能按画面时长写长文案。",
        f"语速估算：约 {cps:.1f} 字/秒（中文口播）。",
    ]
    if target is not None:
        brief_parts.extend(
            [
                f"【用户目标成片总时长】**{float(target):.0f} 秒**（全片 TTS 合计不得超过此值）。",
                f"全片旁白总字数建议 ≤ **{total_chars} 字**（约 {total_tts:.1f}s）。",
            ]
        )
        if meta.get("must_compress_vs_video"):
            ratio = float(meta.get("compress_ratio") or 1.0)
            brief_parts.append(
                f"当前所选画面素材合计约 **{total_video:.0f}s**，高于目标成片；"
                f"文案须压缩至约 **{ratio * 100:.0f}%** 密度，禁止写满画面时长的信息量。"
            )
    else:
        brief_parts.append(
            f"未设目标成片时长：请仍遵守各片段字数上限；全片旁白若写满上限合计约 **{total_tts:.1f}s**。"
        )
    brief_parts.extend(
        [
            "【写作纪律】",
            "1) 每条严格遵守对应片段「旁白字数上限」，宁可更短；",
            "2) 优先 1 句、最多 2 个极短句；",
            "3) 禁止长段落、禁止一条里塞多个卖点；",
            "4) 字数统计含标点，以中文汉字为主。",
        ]
    )
    duration_brief = "\n".join(brief_parts)
    return active, manifest, duration_brief, budgets


def _build_llm_system_prompt(*, segment_count: int) -> str:
    return (
        "你是短视频混剪配音文案师。成片时间轴由 **TTS 朗读时长** 决定，不是由画面镜头时长决定。\n"
        "你的任务：为每个画面片段写 **极短** 旁白，使朗读时长落在给定的字数/秒数预算内。\n"
        "硬性规则：\n"
        "- 每条旁白字数 **不得超过** 清单中的「旁白字数上限」；\n"
        "- 全片旁白 TTS 总时长 **不得超过** 用户目标成片时长（若已给出）；\n"
        "- 勿因画面较长而写长文案；画面短于配音时成片会循环画面，必须缩短文案；\n"
        "- 口语化、适合 TTS，勿照抄 ASR，可重组信息与情绪；\n"
        "- 只输出 JSON，不要解释。\n"
        '格式：{"scripts":[{"index":0,"text":"旁白"}, ...]}\n'
        f"scripts 长度必须恰好为 {segment_count}，index 从 0 到 {segment_count - 1} 连续。"
    )


async def apply_llm_scripts_to_mute_plan(
    *,
    plan: Plan,
    db: aiosqlite.Connection,
    video_ids: list[str],
    user_prompt: str,
    llm_cfg: dict[str, Any],
    target_duration_sec: float | None = None,
) -> Plan:
    """
    为 mute_all + AI 配音（生成文案）模式填充每段 subtitle.text。
    要求 user_prompt 非空；失败时抛出 RuntimeError。
    """
    up = (user_prompt or "").strip()
    if not up:
        raise ValueError("AI 生成文案需要填写剪辑诉求")

    resolved_target = resolve_voiceover_target_duration_sec(
        explicit_sec=target_duration_sec if target_duration_sec is not None else plan.target_duration_sec,
        user_prompt=up,
    )

    active, manifest, duration_brief, budgets = _build_segment_manifest_and_brief(
        plan.segments,
        target_duration_sec=resolved_target,
    )
    n = len(active)
    if n == 0:
        return plan

    context = await _build_video_context_with_recall(db, video_ids, user_prompt=up)

    llm = LLMClient(
        base_url=llm_cfg["base_url"],
        api_key=llm_cfg["api_key"],
        model=llm_cfg["model"],
        temperature=float(llm_cfg.get("temperature") or 0.65),
        max_tokens=min(int(llm_cfg.get("max_tokens") or 8192), 65536),
        timeout=3600,
    )
    sys = _build_llm_system_prompt(segment_count=n)
    user = (
        f"{duration_brief}\n\n"
        f"【用户诉求】\n{up}\n\n"
        f"【素材识别内容】\n{context}\n\n"
        f"【成片片段清单（按播放顺序；字数上限为硬约束）】\n{manifest}\n\n"
        f"请为以上 {n} 个片段各写一条旁白。"
        "务必使全片 TTS 总时长不超过目标成片时长，且每条不超过对应字数上限。"
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

    texts = clamp_script_texts_to_budgets(
        texts, budgets, target_duration_sec=resolved_target
    )

    est_total_tts = round(sum(estimate_tts_duration_sec(t) for t in texts), 2)
    target_note = (
        f"目标成片 {resolved_target:.0f}s，"
        if resolved_target is not None
        else ""
    )

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
        + f" 配音文案：AI 生成 {active_idx} 段旁白（TTS 预估合计约 {est_total_tts}s，"
        f"{target_note}按字数预算控制，非画面时长）。"
    )
    updates: dict[str, Any] = {"segments": new_segments, "summary": summary}
    if resolved_target is not None:
        updates["target_duration_sec"] = resolved_target
        updates["estimated_duration_sec"] = est_total_tts
    return plan.model_copy(update=updates)
