"""混剪：多素材分级编排 + 原声/全静音两大模式。"""
from __future__ import annotations

import random
import uuid
from typing import Any, Literal, Sequence

from app.models.auto_edit import (
    BGMPlan,
    ClipRef,
    Constraints,
    Plan,
    PlanKeepFlags,
    SegmentPlan,
    SubtitlePlan,
    TimingHint,
)
from app.core.auto_edit.voiceover_quick_cut import (
    _clip_has_asr,
    _is_meaningful_text,
    _merge_contiguous_asr_rows,
    _parse_asr_segments,
    apply_voiceover_source_timeline_dedupe,
)

ClipTier = Literal["asr_vlm", "asr_only", "vlm_only", "none"]
MixAudioMode = Literal["keep_original", "mute_all_original"]
VoiceMergeStrategy = Literal["strict_single", "same_voice_concat"]
MuteAudioTrack = Literal["ai_tts_asr", "ai_tts_llm", "bgm_only"]

_TIER_PRIORITY: dict[ClipTier, int] = {
    "asr_vlm": 0,
    "asr_only": 1,
    "vlm_only": 2,
    "none": 3,
}

# 无 ASR 画面填充段默认时长（秒）
_MUTE_FILLER_SEC = 1.2
# 严格单路：人声段之间静音过渡（秒）
_STRICT_GAP_SEC = 0.35

# LLM 出入点贴近镜头切分点时的自动吸附（秒，可调）
_SNAP_NEAR_CUT_SEC = 0.5
# 吸附到切分点后向片段内侧偏移，避免落在转场帧（秒）
_SNAP_INSET_SEC = 0.15
# 吸附后再对首尾各内缩，抵消镜头检测边界微偏（秒）
_EDGE_PAD_SEC = 0.1
# 修正后片段最短时长（秒）
_MIN_REFINED_SEGMENT_SEC = 0.25


def _row_vlm(row: Any) -> str | None:
    try:
        v = row["vlm_description"]
        return str(v) if v is not None else None
    except (KeyError, IndexError, TypeError):
        return None


def classify_clip_tier(*, asr_text: str | None, vlm_description: str | None) -> ClipTier:
    has_asr = _clip_has_asr(asr_text)
    has_vlm = bool((vlm_description or "").strip())
    if has_asr and has_vlm:
        return "asr_vlm"
    if has_asr:
        return "asr_only"
    if has_vlm:
        return "vlm_only"
    return "none"


def _tier_label(tier: ClipTier) -> str:
    return {
        "asr_vlm": "ASR+VLM",
        "asr_only": "仅 ASR",
        "vlm_only": "仅 VLM",
        "none": "无标注",
    }[tier]


def _arrange_strategy_label(tier: ClipTier) -> str:
    return {
        "asr_vlm": "语义智能混剪",
        "asr_only": "文本语义编排",
        "vlm_only": "画面语义匹配",
        "none": "纯随机混剪",
    }[tier]


def _format_tier_counts(tier_counts: dict[str, int]) -> str:
    parts = [
        f"{_tier_label(k)}×{v}"
        for k, v in sorted(tier_counts.items(), key=lambda x: _TIER_PRIORITY[x[0]])  # type: ignore[index]
    ]
    return ", ".join(parts)


def _clip_row_to_segment(
    *,
    row: Any,
    order: int,
    audio_mode: Literal["original", "tts", "mute"],
    subtitle_strategy: Literal["auto", "asr", "rewrite", "none"] = "asr",
    subtitle_text: str | None = None,
    subtitle_source: Literal["asr", "llm", "vlm", "user"] = "asr",
) -> SegmentPlan | None:
    cid = str(row["id"])
    vid = str(row["video_id"])
    clip_base = float(row["start_time"] or 0.0)
    clip_dur = float(row["duration"] or 0.0)
    if clip_dur <= 0:
        return None

    text = (subtitle_text or row["asr_text"] or "").strip()
    if audio_mode == "mute":
        text = text or "（画面填充）"
        subtitle_strategy = "none"
        subtitle_source = "vlm" if (_row_vlm(row) or "").strip() else "asr"

    return SegmentPlan(
        id=f"mix_{order:04d}_{cid[:8]}",
        order=order,
        clip_group=[ClipRef(clip_id=cid, video_id=vid, weight=1.0)],
        selected_clip_ids=[cid],
        start_time_sec=clip_base,
        end_time_sec=clip_base + clip_dur,
        override_duration_sec=clip_dur,
        clip_start_offset_sec=0.0,
        audio_mode=audio_mode,
        subtitle=SubtitlePlan(
            strategy=subtitle_strategy,
            text=text or "（画面）",
            source=subtitle_source,
            timing_hint=TimingHint(start=clip_base, end=clip_base + clip_dur),
        ),
    )


def _extract_asr_sentence_segments(row: Any) -> list[tuple[float, float, str]]:
    clip_base = float(row["start_time"] or 0.0)
    clip_dur = float(row["duration"] or 0.0)
    seg_items = _parse_asr_segments(row["asr_segments"])
    if not seg_items:
        if not _clip_has_asr(row["asr_text"]):
            return []
        return [(clip_base, clip_base + clip_dur, (row["asr_text"] or "").strip() or "（口播）")]

    raw_rows: list[tuple[float, float, str]] = []
    for seg in seg_items:
        try:
            st_rel = float(seg.get("start") or 0.0)
            et_rel = float(seg.get("end") or st_rel)
        except Exception:
            continue
        if et_rel <= st_rel:
            continue
        text = str(seg.get("text") or "").strip()
        if not _is_meaningful_text(text):
            continue
        raw_rows.append((clip_base + st_rel, clip_base + et_rel, text))

    raw_rows.sort(key=lambda r: r[0])
    merged = _merge_contiguous_asr_rows(
        [(s - clip_base, e - clip_base, t) for s, e, t in raw_rows]
    )
    return [(clip_base + st, clip_base + et, t) for st, et, t in merged]


def build_shot_boundaries_by_video(rows: Sequence[Any]) -> dict[str, list[float]]:
    """按 video_id 汇总镜头切分点（各 clip 的 start / end，绝对秒）。"""
    acc: dict[str, set[float]] = {}
    for row in rows:
        vid = str(row["video_id"])
        base = float(row["start_time"] or 0.0)
        dur = float(row["duration"] or 0.0)
        acc.setdefault(vid, set()).add(round(base, 4))
        if dur > 0:
            acc[vid].add(round(base + dur, 4))
    return {vid: sorted(ts) for vid, ts in acc.items()}


def _shot_interval(bounds: Sequence[float], t: float) -> tuple[float, float]:
    bs = sorted(float(b) for b in bounds)
    n = len(bs)
    if n == 0:
        return 0.0, 1e9
    if n == 1:
        return bs[0], bs[0] + 1e6
    if t <= bs[0]:
        return bs[0], bs[1]
    for i in range(n - 1):
        if t <= bs[i + 1]:
            return bs[i], bs[i + 1]
    return bs[-2], bs[-1]


def refine_abs_time_range(
    st: float,
    et: float,
    *,
    boundaries: Sequence[float],
    clip_lo: float | None = None,
    clip_hi: float | None = None,
    snap_threshold: float = _SNAP_NEAR_CUT_SEC,
    snap_inset: float = _SNAP_INSET_SEC,
    edge_pad: float = _EDGE_PAD_SEC,
    min_dur: float = _MIN_REFINED_SEGMENT_SEC,
) -> tuple[float, float]:
    """
    将 LLM 给出的源片绝对出入点修正到镜头切分点内侧，减少跨镜头抖动。

    - 出入点距切分点 ≤ snap_threshold 时吸附，并向片段内侧偏移 snap_inset
    - 若区间仍横跨切分点，保留占时长更多的一侧
    - 最后再对首尾各内缩 edge_pad
    """
    st_r = float(st)
    et_r = float(et)
    if et_r <= st_r:
        et_r = st_r + min_dur

    bounds = sorted({round(float(b), 4) for b in boundaries})
    if len(bounds) < 2:
        st_r += edge_pad
        et_r -= edge_pad
    else:
        mid = (st_r + et_r) * 0.5
        lo_shot, hi_shot = _shot_interval(bounds, mid)

        for b in bounds:
            if abs(st_r - b) <= snap_threshold:
                st_r = b + snap_inset if mid >= b else max(lo_shot + snap_inset, b - snap_inset)
            if abs(et_r - b) <= snap_threshold:
                et_r = b - snap_inset if mid <= b else min(hi_shot - snap_inset, b + snap_inset)

        for b in bounds:
            if st_r < b < et_r:
                left = b - st_r
                right = et_r - b
                if right >= left:
                    st_r = b + snap_inset
                else:
                    et_r = b - snap_inset

        st_r += edge_pad
        et_r -= edge_pad

        lo_shot, hi_shot = _shot_interval(bounds, (st_r + et_r) * 0.5)
        st_r = max(st_r, lo_shot + snap_inset)
        et_r = min(et_r, hi_shot - snap_inset)

    if clip_lo is not None:
        st_r = max(st_r, float(clip_lo))
    if clip_hi is not None:
        et_r = min(et_r, float(clip_hi))

    if et_r <= st_r + min_dur:
        lo = float(clip_lo) if clip_lo is not None else (bounds[0] if bounds else st_r)
        hi = float(clip_hi) if clip_hi is not None else (bounds[-1] if bounds else et_r)
        st_r = max(lo, min(st_r, hi - min_dur))
        et_r = min(hi, max(st_r + min_dur, et_r))

    return round(st_r, 3), round(et_r, 3)


def _build_voice_segment_from_range(
    *,
    row: Any,
    order: int,
    st_abs: float,
    et_abs: float,
    text: str,
    audio_mode: Literal["original", "tts", "mute"] = "original",
    refine_shot_bounds: bool = False,
    boundaries_by_video: dict[str, list[float]] | None = None,
) -> SegmentPlan:
    cid = str(row["id"])
    vid = str(row["video_id"])
    clip_base = float(row["start_time"] or 0.0)
    clip_dur = float(row["duration"] or 0.0)
    clip_hi = clip_base + clip_dur if clip_dur > 0 else None

    st_use, et_use = float(st_abs), float(et_abs)
    if refine_shot_bounds and boundaries_by_video:
        bounds = boundaries_by_video.get(vid) or []
        if bounds:
            st_use, et_use = refine_abs_time_range(
                st_use,
                et_use,
                boundaries=bounds,
                clip_lo=clip_base,
                clip_hi=clip_hi,
            )

    st_rel = max(0.0, st_use - clip_base)
    et_rel = max(st_rel, et_use - clip_base)
    dur = et_rel - st_rel
    return SegmentPlan(
        id=f"mix_{order:04d}_{cid[:6]}_v",
        order=order,
        clip_group=[ClipRef(clip_id=cid, video_id=vid, weight=1.0)],
        selected_clip_ids=[cid],
        start_time_sec=st_use,
        end_time_sec=et_use,
        override_duration_sec=dur,
        clip_start_offset_sec=st_rel,
        audio_mode=audio_mode,
        subtitle=SubtitlePlan(
            strategy="asr" if audio_mode == "original" else "none",
            text=text,
            source="asr",
            timing_hint=TimingHint(start=st_use, end=et_use),
        ),
    )


def build_segment_from_llm_time_range(
    *,
    row: Any,
    order: int,
    st_abs: float,
    et_abs: float,
    text: str,
    audio_mode: Literal["original", "tts", "mute"] = "tts",
    boundaries_by_video: dict[str, list[float]],
    subtitle_strategy: Literal["auto", "asr", "rewrite", "none"] = "rewrite",
) -> SegmentPlan:
    """由 LLM 给出的源片绝对时间窗构建片段，并自动做镜头切分点修正。"""
    seg = _build_voice_segment_from_range(
        row=row,
        order=order,
        st_abs=st_abs,
        et_abs=et_abs,
        text=text,
        audio_mode=audio_mode,
        refine_shot_bounds=True,
        boundaries_by_video=boundaries_by_video,
    )
    sub = seg.subtitle.model_copy(
        update={
            "strategy": subtitle_strategy,
            "source": "llm",
            "timing_hint": TimingHint(start=seg.start_time_sec, end=seg.end_time_sec),
        }
    )
    return seg.model_copy(update={"subtitle": sub})


def apply_shot_boundary_refine_to_plan(plan: Plan, clip_rows: Sequence[Any]) -> Plan:
    """对方案中已含 LLM 源时间轴的片段批量做镜头切分点修正。"""
    boundaries = build_shot_boundaries_by_video(clip_rows)
    if not boundaries:
        return plan

    row_by_id = {str(r["id"]): r for r in clip_rows}
    new_segments: list[SegmentPlan] = []
    for seg in plan.segments:
        if seg.exclude_from_output:
            new_segments.append(seg)
            continue
        sub = seg.subtitle
        if sub is None or sub.source != "llm":
            new_segments.append(seg)
            continue
        cid = seg.selected_clip_ids[0] if seg.selected_clip_ids else None
        if not cid or cid not in row_by_id:
            new_segments.append(seg)
            continue
        row = row_by_id[cid]
        vid = str(row["video_id"])
        bounds = boundaries.get(vid)
        if not bounds:
            new_segments.append(seg)
            continue

        clip_base = float(row["start_time"] or 0.0)
        clip_dur = float(row["duration"] or 0.0)
        clip_hi = clip_base + clip_dur if clip_dur > 0 else None
        st0 = float(seg.start_time_sec)
        et0 = float(seg.end_time_sec)
        st1, et1 = refine_abs_time_range(
            st0,
            et0,
            boundaries=bounds,
            clip_lo=clip_base,
            clip_hi=clip_hi,
        )
        if abs(st1 - st0) < 1e-6 and abs(et1 - et0) < 1e-6:
            new_segments.append(seg)
            continue

        st_rel = max(0.0, st1 - clip_base)
        et_rel = max(st_rel, et1 - clip_base)
        dur = et_rel - st_rel
        hint = sub.timing_hint
        new_hint = (
            TimingHint(start=st1, end=et1)
            if hint is None
            else hint.model_copy(update={"start": st1, "end": et1})
        )
        new_segments.append(
            seg.model_copy(
                update={
                    "start_time_sec": st1,
                    "end_time_sec": et1,
                    "clip_start_offset_sec": st_rel,
                    "override_duration_sec": dur,
                    "subtitle": sub.model_copy(update={"timing_hint": new_hint}),
                }
            )
        )

    return plan.model_copy(update={"segments": new_segments})


def _sort_clips_by_tier(rows: Sequence[Any], *, shuffle_none: bool) -> list[Any]:
    tiered: dict[ClipTier, list[Any]] = {t: [] for t in _TIER_PRIORITY}
    for row in rows:
        tier = classify_clip_tier(
            asr_text=row["asr_text"],
            vlm_description=_row_vlm(row),
        )
        tiered[tier].append(row)

    ordered: list[Any] = []
    for tier in ("asr_vlm", "asr_only", "vlm_only", "none"):
        bucket = tiered[tier]
        if tier == "none" and shuffle_none and len(bucket) > 1:
            bucket = list(bucket)
            random.shuffle(bucket)
        ordered.extend(bucket)
    return ordered


def build_mix_edit_plan(
    *,
    clip_rows: Sequence[Any],
    mix_audio_mode: MixAudioMode,
    voice_merge_strategy: VoiceMergeStrategy = "strict_single",
    mute_audio_track: MuteAudioTrack = "ai_tts",
    video_title_hint: str | None = None,
    target_duration_sec: float | None = None,
) -> Plan:
    """
    混剪方案生成：
    - keep_original + strict_single：人声分段接力、不重叠；无 ASR 静音画面
    - keep_original + same_voice_concat：带 ASR 素材原声全开；无 ASR 静音
    - mute_all_original：全静音 + 按素材等级编排；音轨 ai_tts / bgm_only
    """
    rows = list(clip_rows)
    if not rows:
        raise ValueError("所选视频下没有可用 clip")

    tier_counts: dict[str, int] = {}
    for row in rows:
        t = classify_clip_tier(
            asr_text=row["asr_text"],
            vlm_description=_row_vlm(row),
        )
        tier_counts[t] = tier_counts.get(t, 0) + 1

    arranged = _sort_clips_by_tier(rows, shuffle_none=(mix_audio_mode == "mute_all_original"))
    segments: list[SegmentPlan] = []
    order = 0
    arrange_notes: list[str] = []

    if mix_audio_mode == "mute_all_original":
        use_tts = mute_audio_track in ("ai_tts_asr", "ai_tts_llm")
        seg_audio: Literal["tts", "mute"] = "tts" if use_tts else "mute"
        for row in arranged:
            tier = classify_clip_tier(
                asr_text=row["asr_text"],
                vlm_description=_row_vlm(row),
            )
            arrange_notes.append(f"{_tier_label(tier)}→{_arrange_strategy_label(tier)}")
            has_asr = _clip_has_asr(row["asr_text"])
            if mute_audio_track == "ai_tts_llm":
                sub_strategy: Literal["auto", "asr", "rewrite", "none"] = "rewrite"
                sub_source: Literal["asr", "llm", "vlm", "user"] = "llm"
                sub_text = "（待 AI 生成旁白）"
            elif has_asr:
                sub_strategy = "asr"
                sub_source = "asr"
                sub_text = (row["asr_text"] or "").strip() or None
            else:
                sub_strategy = "none"
                sub_source = "vlm"
                sub_text = (_row_vlm(row) or "").strip()[:200] or "（画面）"
            seg = _clip_row_to_segment(
                row=row,
                order=order,
                audio_mode=seg_audio,
                subtitle_strategy=sub_strategy,
                subtitle_text=sub_text,
                subtitle_source=sub_source,
            )
            if seg:
                segments.append(seg)
                order += 1

        plan_mode: Literal["auto", "voiceover", "original"] = (
            "voiceover" if use_tts else "auto"
        )
        if mute_audio_track == "ai_tts_llm":
            audio_desc = "AI 生成文案 + TTS 配音"
        elif mute_audio_track == "ai_tts_asr":
            audio_desc = "沿用 ASR 原文 + TTS 配音"
        else:
            audio_desc = "仅 BGM（素材全静音）"
        title = f"混剪·关闭原声（{audio_desc}）"
        summary = (
            f"模式二：全部素材静音；按等级编排（{' / '.join(arrange_notes[:6])}"
            f"{'…' if len(arrange_notes) > 6 else ''}）；"
            f"共 {len(segments)} 段，音轨：{audio_desc}。"
            f" 分级统计：{_format_tier_counts(tier_counts)}."
        )
        bgm = BGMPlan(enabled=(mute_audio_track == "bgm_only"), volume_db=-10.0)

    elif voice_merge_strategy == "same_voice_concat":
        for row in arranged:
            tier = classify_clip_tier(
                asr_text=row["asr_text"],
                vlm_description=_row_vlm(row),
            )
            has_asr = tier in ("asr_vlm", "asr_only")
            if has_asr:
                ranges = _extract_asr_sentence_segments(row)
                if ranges:
                    for st, et, text in ranges:
                        segments.append(
                            _build_voice_segment_from_range(
                                row=row, order=order, st_abs=st, et_abs=et, text=text
                            )
                        )
                        order += 1
                else:
                    seg = _clip_row_to_segment(
                        row=row, order=order, audio_mode="original"
                    )
                    if seg:
                        segments.append(seg)
                        order += 1
            else:
                seg = _clip_row_to_segment(
                    row=row,
                    order=order,
                    audio_mode="mute",
                    subtitle_strategy="none",
                    subtitle_text="（无 ASR·画面填充）",
                )
                if seg:
                    dur = float(seg.override_duration_sec or _MUTE_FILLER_SEC)
                    seg = seg.model_copy(
                        update={"override_duration_sec": min(dur, _MUTE_FILLER_SEC)}
                    )
                    segments.append(seg)
                    order += 1

        plan_mode = "original"
        title = "混剪·保留原声（同人声自由拼接）"
        summary = (
            f"模式一·策略二：带 ASR 素材原声全开、可穿插拼接；无 ASR 静音画面填充。"
            f" 共 {len(segments)} 段。"
            f" 分级：{_format_tier_counts(tier_counts)}."
        )
        bgm = BGMPlan(enabled=False)

    else:
        # strict_single：仅 ASR 人声段顺序接力；无 ASR 静音填充；成片时间轴不重叠
        voice_queue: list[tuple[Any, float, float, str]] = []
        mute_fillers: list[Any] = []
        for row in arranged:
            tier = classify_clip_tier(
                asr_text=row["asr_text"],
                vlm_description=_row_vlm(row),
            )
            if tier in ("asr_vlm", "asr_only"):
                for st, et, text in _extract_asr_sentence_segments(row):
                    voice_queue.append((row, st, et, text))
            else:
                mute_fillers.append(row)

        # 按源视频顺序 + 源内时间排序，保证「接力」稳定
        voice_queue.sort(key=lambda x: (str(x[0]["video_id"]), x[1]))

        timeline_cursor = 0.0
        filler_idx = 0
        for row, st, et, text in voice_queue:
            dur = max(0.05, et - st)
            if filler_idx < len(mute_fillers) and timeline_cursor > 0:
                filler = mute_fillers[filler_idx]
                filler_idx += 1
                fseg = _clip_row_to_segment(
                    row=filler,
                    order=order,
                    audio_mode="mute",
                    subtitle_strategy="none",
                    subtitle_text="（静音过渡）",
                )
                if fseg:
                    fdur = min(
                        float(fseg.override_duration_sec or _MUTE_FILLER_SEC),
                        _MUTE_FILLER_SEC,
                    )
                    fseg = fseg.model_copy(update={"override_duration_sec": fdur})
                    segments.append(fseg)
                    order += 1
                    timeline_cursor += fdur

            segments.append(
                _build_voice_segment_from_range(
                    row=row, order=order, st_abs=st, et_abs=et, text=text
                )
            )
            order += 1
            timeline_cursor += dur

        while filler_idx < len(mute_fillers):
            filler = mute_fillers[filler_idx]
            filler_idx += 1
            fseg = _clip_row_to_segment(
                row=filler,
                order=order,
                audio_mode="mute",
                subtitle_strategy="none",
                subtitle_text="（无 ASR·画面填充）",
            )
            if fseg:
                fseg = fseg.model_copy(
                    update={
                        "override_duration_sec": min(
                            float(fseg.override_duration_sec or _MUTE_FILLER_SEC),
                            _MUTE_FILLER_SEC,
                        )
                    }
                )
                segments.append(fseg)
                order += 1

        plan_mode = "original"
        title = "混剪·保留原声（严格单路人声）"
        summary = (
            f"模式一·策略一：时间轴任意时刻仅一段人声、顺序接力；"
            f"无 ASR 素材静音填充。人声段 {len(voice_queue)}，画面填充 {filler_idx}。"
            f" 分级：{_format_tier_counts(tier_counts)}."
        )
        bgm = BGMPlan(enabled=False)

    total = sum(
        float(s.override_duration_sec or max(0.0, s.end_time_sec - s.start_time_sec))
        for s in segments
    )
    plan = Plan(
        plan_id=uuid.uuid4().hex[:8],
        title=title,
        summary=summary,
        video_title=(video_title_hint or "").strip() or None,
        mode=plan_mode,
        target_duration_sec=target_duration_sec,
        estimated_duration_sec=round(total, 2) if total > 0 else None,
        segments=segments,
        bgm=bgm,
        constraints=Constraints(
            match_strategy="asr+vlm",
            respect_user_video_order=True,
        ),
        keep_flags=PlanKeepFlags(
            clips=False, subtitles=False, transitions=False, bgm=False
        ),
    )

    if mix_audio_mode == "keep_original" and voice_merge_strategy == "strict_single":
        plan = apply_voiceover_source_timeline_dedupe(plan, allow_overlaps=False)
    elif mix_audio_mode == "keep_original" and voice_merge_strategy == "same_voice_concat":
        plan = apply_voiceover_source_timeline_dedupe(plan, allow_overlaps=True)

    if target_duration_sec and plan.estimated_duration_sec:
        if plan.estimated_duration_sec > target_duration_sec * 1.5:
            plan = plan.model_copy(
                update={
                    "summary": plan.summary
                    + f" 提示：预估 {plan.estimated_duration_sec:.0f}s，高于目标 {target_duration_sec:.0f}s，可删减素材后重试。"
                }
            )

    return plan
