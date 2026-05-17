"""混剪 TTS 配音：文案长度与画面时长平衡（拆句 + 多素材匹配）。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal, Sequence

from app.core.auto_edit.mix_edit import (
    _clip_row_to_segment,
    _sort_clips_by_tier,
)
from app.core.subtitle.timeline import (
    split_long_text_at_punctuation,
    split_text_units_by_sentence_and_newline,
)
from app.models.auto_edit import ClipRef, Plan, SegmentPlan, SubtitlePlan, TimingHint
from app.models.subtitle import ClipTrimPart

# 中文 TTS 粗估语速（字/秒），略保守以减少「配音长于画面」
_CHARS_PER_SEC_TTS = 4.2
CHARS_PER_SEC_TTS = _CHARS_PER_SEC_TTS
# 目标：预估配音时长 ≤ 画面时长 × 该比例（留一点余量）
_TTS_VIDEO_FILL_RATIO = 0.9
# 单段画面过短时的最短可接受时长（秒）
_MIN_CLIP_USABLE_SEC = 0.35


def segment_video_duration_sec(seg: SegmentPlan) -> float:
    od = seg.override_duration_sec
    if od is not None and od > 0:
        return float(od)
    return max(0.0, float(seg.end_time_sec) - float(seg.start_time_sec))


def estimate_tts_duration_sec(text: str) -> float:
    t = (text or "").strip()
    if not t:
        return 0.5
    return max(0.8, len(t) / _CHARS_PER_SEC_TTS)


def max_chars_for_video_duration(video_sec: float) -> int:
    sec = max(_MIN_CLIP_USABLE_SEC, float(video_sec or 0.0))
    return max(8, int(sec * _CHARS_PER_SEC_TTS * _TTS_VIDEO_FILL_RATIO))


def max_chars_for_target_tts_duration(tts_sec: float) -> int:
    """按目标 TTS 秒数反推字数上限。"""
    sec = max(0.5, float(tts_sec or 0.0))
    return max(6, int(sec * _CHARS_PER_SEC_TTS * _TTS_VIDEO_FILL_RATIO))


@dataclass(frozen=True)
class SegmentTtsBudget:
    index: int
    clip_id: str
    video_sec: float
    max_chars: int
    max_tts_sec: float


def compute_mix_tts_script_budgets(
    segments: list[SegmentPlan],
    *,
    target_duration_sec: float | None = None,
) -> tuple[list[SegmentTtsBudget], dict[str, Any]]:
    """
    为 LLM 旁白生成计算每段字数/秒数预算。

    成片时长由 TTS 朗读时长决定（非画面 clip 时长）；有目标成片时长时按目标分配总字数。
    """
    active = [s for s in segments if not s.exclude_from_output]
    if not active:
        return [], {}

    video_secs = [segment_video_duration_sec(s) for s in active]
    total_video = sum(video_secs)
    per_clip_cap = [max_chars_for_video_duration(vs) for vs in video_secs]

    target = float(target_duration_sec) if target_duration_sec and target_duration_sec > 0 else None
    n = len(active)

    if target is not None:
        total_char_cap = max(6 * n, int(target * _CHARS_PER_SEC_TTS * _TTS_VIDEO_FILL_RATIO))
        if total_video > 0:
            alloc: list[int] = []
            for i, vs in enumerate(video_secs):
                share = vs / total_video
                want = max(6, int(total_char_cap * share))
                alloc.append(min(per_clip_cap[i], want))
            while sum(alloc) > total_char_cap and max(alloc) > 6:
                j = alloc.index(max(alloc))
                alloc[j] -= 1
        else:
            alloc = [min(per_clip_cap[i], max(6, total_char_cap // n)) for i in range(n)]
    else:
        alloc = list(per_clip_cap)
        total_char_cap = sum(alloc)

    budgets: list[SegmentTtsBudget] = []
    for i, seg in enumerate(active):
        cid = seg.selected_clip_ids[0] if seg.selected_clip_ids else "?"
        mc = alloc[i]
        budgets.append(
            SegmentTtsBudget(
                index=i,
                clip_id=cid,
                video_sec=video_secs[i],
                max_chars=mc,
                max_tts_sec=round(mc / _CHARS_PER_SEC_TTS, 2),
            )
        )

    total_tts_est = sum(b.max_chars for b in budgets) / _CHARS_PER_SEC_TTS

    meta: dict[str, Any] = {
        "target_duration_sec": target,
        "total_video_sec": round(total_video, 2),
        "total_char_budget": sum(b.max_chars for b in budgets),
        "total_tts_budget_sec": round(total_tts_est, 2),
        "chars_per_sec_tts": _CHARS_PER_SEC_TTS,
        "segment_count": n,
    }
    if target is not None and total_video > target + 0.5:
        meta["must_compress_vs_video"] = True
        meta["compress_ratio"] = round(target / total_video, 3)
    return budgets, meta


def clamp_script_texts_to_budgets(
    texts: list[str],
    budgets: list[SegmentTtsBudget],
    *,
    target_duration_sec: float | None = None,
) -> list[str]:
    """LLM 返回后的硬兜底：单段不超字数，全片不超目标 TTS 时长。"""
    if not texts or not budgets:
        return texts

    out: list[str] = []
    for i, b in enumerate(budgets):
        raw = (texts[i] if i < len(texts) else "").strip()
        if not raw:
            out.append(raw)
            continue
        if len(raw) <= b.max_chars:
            out.append(raw)
            continue
        parts = split_long_text_at_punctuation(raw, b.max_chars)
        out.append((parts[0] if parts else raw[: b.max_chars]).strip())

    target = float(target_duration_sec) if target_duration_sec and target_duration_sec > 0 else None
    if target is None:
        return out

    def _total_est() -> float:
        return sum(estimate_tts_duration_sec(t) for t in out)

    guard = 0
    while _total_est() > target + 0.15 and guard < 500:
        guard += 1
        idx = max(range(len(out)), key=lambda j: len(out[j] or ""))
        t = out[idx]
        if not t or len(t) <= 4:
            break
        shorter = split_long_text_at_punctuation(t, max(4, len(t) - 2))
        out[idx] = (shorter[0] if shorter else t[: max(4, len(t) - 2)]).strip()

    return out


def split_narration_to_fit_video(text: str, video_sec: float) -> list[str]:
    """按画面时长将旁白拆成多条，优先在句读/标点处切分。"""
    raw = (text or "").strip()
    if not raw:
        return []
    max_chars = max_chars_for_video_duration(video_sec)
    units = split_text_units_by_sentence_and_newline(raw)
    if not units:
        units = [raw]

    chunks: list[str] = []
    buf = ""
    for u in units:
        u = u.strip()
        if not u:
            continue
        if not buf:
            candidate = u
        else:
            candidate = buf + u

        if len(candidate) <= max_chars:
            buf = candidate
            continue

        if buf:
            chunks.append(buf)
            buf = ""

        if len(u) <= max_chars:
            buf = u
        else:
            chunks.extend(split_long_text_at_punctuation(u, max_chars))

    if buf:
        chunks.append(buf)

    # 仍超长则按字数硬切
    out: list[str] = []
    for c in chunks:
        c = c.strip()
        if not c:
            continue
        if len(c) <= max_chars:
            out.append(c)
        else:
            out.extend(split_long_text_at_punctuation(c, max_chars))

    if not out:
        out = [raw[:max_chars].strip()] if raw else []
    return [x for x in out if x]


def _needs_tts_rebalance(text: str, video_sec: float) -> bool:
    if video_sec < _MIN_CLIP_USABLE_SEC:
        return False
    return estimate_tts_duration_sec(text) > video_sec * _TTS_VIDEO_FILL_RATIO


def _merge_chunks_to_count(chunks: list[str], target: int) -> list[str]:
    if target <= 0 or not chunks:
        return chunks
    while len(chunks) > target and len(chunks) > 1:
        # 合并最短相邻对
        best_i = 0
        best_len = len(chunks[0]) + len(chunks[1])
        for i in range(len(chunks) - 1):
            n = len(chunks[i]) + len(chunks[i + 1])
            if n < best_len:
                best_len = n
                best_i = i
        chunks[best_i] = chunks[best_i] + chunks[best_i + 1]
        del chunks[best_i + 1]
    return chunks


def _segment_from_row_copy(
    *,
    row: Any,
    order: int,
    text: str,
    audio_mode: Literal["tts", "mute"] = "tts",
    subtitle_strategy: Literal["auto", "asr", "rewrite", "none"] = "rewrite",
    subtitle_source: Literal["asr", "llm", "vlm", "user"] = "llm",
) -> SegmentPlan | None:
    seg = _clip_row_to_segment(
        row=row,
        order=order,
        audio_mode=audio_mode,
        subtitle_strategy=subtitle_strategy,
        subtitle_text=text,
        subtitle_source=subtitle_source,
    )
    if seg is None:
        return None
    clip_base = float(row["start_time"] or 0.0)
    clip_dur = float(row["duration"] or 0.0)
    return seg.model_copy(
        update={
            "subtitle": SubtitlePlan(
                strategy=subtitle_strategy,
                text=text,
                source=subtitle_source,
                timing_hint=TimingHint(start=clip_base, end=clip_base + clip_dur),
            ),
        }
    )


def _segment_with_clip_trims(
    *,
    rows: Sequence[Any],
    order: int,
    text: str,
    subtitle_strategy: Literal["auto", "asr", "rewrite", "none"] = "rewrite",
    subtitle_source: Literal["asr", "llm", "vlm", "user"] = "llm",
) -> SegmentPlan | None:
    if not rows:
        return None
    trims: list[ClipTrimPart] = []
    group: list[ClipRef] = []
    total = 0.0
    for row in rows:
        cid = str(row["id"])
        vid = str(row["video_id"])
        dur = max(_MIN_CLIP_USABLE_SEC, float(row["duration"] or 0.0))
        trims.append(ClipTrimPart(clip_id=cid, clip_start_sec=0.0, duration_sec=dur))
        group.append(ClipRef(clip_id=cid, video_id=vid, weight=1.0))
        total += dur

    primary = rows[0]
    base = float(primary["start_time"] or 0.0)
    cid0 = str(primary["id"])
    vid0 = str(primary["video_id"])

    return SegmentPlan(
        id=f"mix_{order:04d}_{cid0[:8]}_m",
        order=order,
        clip_group=group,
        selected_clip_ids=[t.clip_id for t in trims],
        start_time_sec=base,
        end_time_sec=base + float(primary["duration"] or 0.0),
        override_duration_sec=total,
        clip_start_offset_sec=0.0,
        clip_trims=trims,
        audio_mode="tts",
        subtitle=SubtitlePlan(
            strategy=subtitle_strategy,
            text=text,
            source=subtitle_source,
            timing_hint=TimingHint(start=base, end=base + total),
        ),
    )


def rebalance_mix_tts_voiceover_plan(
    plan: Plan,
    clip_rows: Sequence[Any],
    *,
    mute_audio_track: Literal["ai_tts_asr", "ai_tts_llm", "ai_tts", "bgm_only"],
) -> Plan:
    """
    将「过长 TTS 文案 + 过短画面」拆成多段，并串联后续素材，降低成片时画面循环次数。

    - 优先：拆文案 + 每段匹配一个 clip（按分级编排顺序取后续素材）
    - 次选：单条文案仍偏长时，用 clip_trims 顺序拼接 2~3 个素材
    """
    if mute_audio_track not in ("ai_tts_asr", "ai_tts_llm", "ai_tts"):
        return plan

    rows = list(clip_rows)
    if not rows:
        return plan

    arranged = _sort_clips_by_tier(rows, shuffle_none=True)
    row_by_id = {str(r["id"]): r for r in arranged}
    id_order = [str(r["id"]) for r in arranged]

    sub_strategy: Literal["auto", "asr", "rewrite", "none"] = (
        "rewrite" if mute_audio_track == "ai_tts_llm" else "asr"
    )
    sub_source: Literal["asr", "llm", "vlm", "user"] = (
        "llm" if mute_audio_track == "ai_tts_llm" else "asr"
    )

    expanded: list[SegmentPlan] = []
    split_count = 0
    order = 0
    pool_idx = 0

    def _row_at_pool(i: int) -> Any | None:
        if i < 0 or i >= len(arranged):
            return None
        return arranged[i]

    for seg in plan.segments:
        if seg.exclude_from_output:
            expanded.append(seg.model_copy(update={"order": order}))
            order += 1
            continue
        if seg.audio_mode != "tts":
            expanded.append(seg.model_copy(update={"order": order}))
            order += 1
            continue

        text = (seg.subtitle.text if seg.subtitle else "").strip()
        if not text or text.startswith("（"):
            expanded.append(seg.model_copy(update={"order": order}))
            order += 1
            continue

        cid = seg.selected_clip_ids[0] if seg.selected_clip_ids else None
        if not cid or cid not in row_by_id:
            expanded.append(seg.model_copy(update={"order": order}))
            order += 1
            continue

        try:
            pool_idx = max(pool_idx, id_order.index(cid))
        except ValueError:
            pool_idx = 0

        row0 = row_by_id[cid]
        vid_sec = segment_video_duration_sec(seg)

        if not _needs_tts_rebalance(text, vid_sec):
            expanded.append(seg.model_copy(update={"order": order}))
            order += 1
            pool_idx = max(pool_idx, id_order.index(cid)) + 1
            continue

        chunks = split_narration_to_fit_video(text, vid_sec)

        available = max(1, len(arranged) - pool_idx)
        if len(chunks) > available:
            chunks = _merge_chunks_to_count(chunks, available)

        if len(chunks) <= 1:
            expanded.append(seg.model_copy(update={"order": order}))
            order += 1
            pool_idx = max(pool_idx, id_order.index(cid)) + 1
            continue

        split_count += len(chunks) - 1
        for ci, chunk in enumerate(chunks):
            ri = pool_idx + ci
            row = _row_at_pool(ri)
            if row is None:
                break
            piece = _segment_from_row_copy(
                row=row,
                order=order,
                text=chunk,
                subtitle_strategy=sub_strategy,
                subtitle_source=sub_source,
            )
            if piece:
                expanded.append(piece)
                order += 1
        pool_idx = pool_idx + len(chunks)

    if split_count == 0:
        return plan

    orig_n = sum(
        1
        for s in plan.segments
        if not s.exclude_from_output and s.audio_mode == "tts"
    )
    new_n = sum(1 for s in expanded if not s.exclude_from_output)
    note = [f"配音段 {orig_n}→{new_n}"]
    if split_count:
        note.append(f"拆句 {split_count} 次")
    summary = (plan.summary or "") + " TTS 平衡：" + "，".join(note) + "。"
    return plan.model_copy(
        update={
            "segments": expanded,
            "summary": summary,
            "plan_id": plan.plan_id or uuid.uuid4().hex[:8],
        }
    )
