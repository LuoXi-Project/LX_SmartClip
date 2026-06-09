"""方案听感：audio_mode 与 plan.mode 对齐，并生成检查器可读的配音摘要。"""
from __future__ import annotations

from typing import List, Literal, Tuple

from app.models.auto_edit import Plan, PlanAudioSummary, SegmentPlan


def _segment_has_narration(seg: SegmentPlan) -> bool:
    return bool(seg.subtitle and (seg.subtitle.text or "").strip())


def _resolve_audio_mode_for_segment(
    seg: SegmentPlan,
    plan_mode: Literal["auto", "voiceover", "original"],
) -> str:
    """按方案模式推导段落应有的 audio_mode。"""
    if seg.exclude_from_output:
        return seg.audio_mode

    has_text = _segment_has_narration(seg)

    if plan_mode == "voiceover":
        return "tts" if has_text else "mute"

    if plan_mode == "original":
        if seg.audio_mode == "mute" and not has_text:
            return "mute"
        return "original"

    # auto
    if has_text:
        return "tts" if seg.audio_mode != "mute" else "mute"
    return "original" if seg.audio_mode != "mute" else "mute"


def normalize_plan_audio_modes(plan: Plan) -> Tuple[Plan, List[str]]:
    """
    将各段 audio_mode 与 plan.mode 对齐，避免「界面显示配音方案、成片却不调 TTS」。
    返回 (新方案, 修正说明列表)。
    """
    warnings: List[str] = []
    new_segments: List[SegmentPlan] = []

    for seg in plan.segments:
        if seg.exclude_from_output:
            new_segments.append(seg)
            continue

        target = _resolve_audio_mode_for_segment(seg, plan.mode)
        if target != seg.audio_mode:
            warnings.append(
                f"段 {seg.order}（{seg.id}）：audio_mode {seg.audio_mode} → {target}"
            )
            seg = seg.model_copy(update={"audio_mode": target})  # type: ignore[arg-type]
        new_segments.append(seg)

    return plan.model_copy(update={"segments": new_segments}), warnings


def build_plan_audio_summary(plan: Plan) -> dict:
    """生成方案听感摘要（写入 Plan.audio_summary）。"""
    tts_n = original_n = mute_n = 0
    active = 0

    for seg in plan.segments:
        if seg.exclude_from_output:
            continue
        active += 1
        if seg.audio_mode == "tts":
            tts_n += 1
        elif seg.audio_mode == "mute":
            mute_n += 1
        else:
            original_n += 1

    mode = plan.mode
    will_export_tts = tts_n > 0 and mode in ("voiceover", "auto")
    will_keep_original = original_n > 0 and mode == "original"
    mixed = tts_n > 0 and original_n > 0

    if mode == "voiceover":
        if tts_n == active and active > 0:
            label = "全片 AI 配音"
            short = f"{tts_n} 段将合成 TTS 并替换音轨"
        elif tts_n > 0:
            label = "以 AI 配音为主"
            short = f"{tts_n} 段 TTS · {mute_n} 段静音 · {original_n} 段原声"
        else:
            label = "配音方案（无 TTS 段）"
            short = "当前无段落标记为 TTS，成片可能不会配音"
    elif mode == "original":
        if original_n == active and active > 0:
            label = "保留素材原声"
            short = f"{original_n} 段保留现场/同期声，不强制 TTS"
        elif mute_n > 0:
            label = "原声方案（含静音段）"
            short = f"{original_n} 段原声 · {mute_n} 段静音"
        else:
            label = "原声剪辑"
            short = f"{original_n} 段原声"
    else:
        if mixed:
            label = "配音 + 原声混合"
            short = f"{tts_n} 段 TTS · {original_n} 段原声 · {mute_n} 段静音"
        elif tts_n == active and active > 0:
            label = "全片 AI 配音"
            short = f"{tts_n} 段 TTS"
        elif original_n == active and active > 0:
            label = "全片保留原声"
            short = f"{original_n} 段原声"
        else:
            label = "自动混合"
            short = f"{tts_n} 段 TTS · {original_n} 段原声 · {mute_n} 段静音"

    warnings: List[str] = []
    if mode == "voiceover" and tts_n == 0 and active > 0:
        warnings.append("方案为配音模式，但没有段落标记 TTS，成片可能无 AI 配音")
    if mode == "voiceover" and mute_n > 0 and tts_n < active:
        warnings.append(f"{mute_n} 段为静音，成片时这些段落无旁白（仅画面/BGM）")
    if mode == "original" and tts_n > 0:
        warnings.append(f"{tts_n} 段仍标记为 TTS，默认成片会保留原声而非配音")

    return {
        "mode": mode,
        "tts_count": tts_n,
        "original_count": original_n,
        "mute_count": mute_n,
        "active_segment_count": active,
        "will_export_tts": will_export_tts,
        "will_keep_original": will_keep_original or (mode == "original" and original_n > 0),
        "label": label,
        "short": short,
        "warnings": warnings,
    }


def finalize_plan_audio(plan: Plan) -> Plan:
    """归一化 audio_mode 并附加 audio_summary。"""
    normalized, fixes = normalize_plan_audio_modes(plan)
    summary = build_plan_audio_summary(normalized)
    if fixes:
        summary = {**summary, "warnings": [*summary.get("warnings", []), *fixes]}
    return normalized.model_copy(update={"audio_summary": PlanAudioSummary(**summary)})
