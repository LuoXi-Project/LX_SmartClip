"""口播快剪：基于 clips 表片段级 ASR 生成 AutoEdit Plan（原声拼接）。"""
from __future__ import annotations

import uuid
from typing import List, Sequence

import aiosqlite

from app.models.auto_edit import (
    BGMPlan,
    ClipRef,
    Plan,
    PlanKeepFlags,
    SegmentPlan,
    SubtitlePlan,
    TimingHint,
)


def _clip_has_asr(asr_text: str | None) -> bool:
    return bool((asr_text or "").strip())


# 标准快剪：在「前后均有 ASR 的片段」之间，补保留过短的静音/漏识别间隙（无独立能量检测时的工程近似）
_MAX_BRIDGE_CLIP_SEC = 4.0


def _kept_row_indices_standard(rows: Sequence[aiosqlite.Row]) -> List[int]:
    n = len(rows)
    flags = [_clip_has_asr(r["asr_text"]) for r in rows]
    keep = {i for i, f in enumerate(flags) if f}
    for i in range(n):
        if flags[i]:
            continue
        try:
            dur = float(rows[i]["duration"] or 0.0)
        except (TypeError, ValueError):
            dur = 0.0
        if dur <= 0 or dur > _MAX_BRIDGE_CLIP_SEC:
            continue
        prev_asr = next((j for j in range(i - 1, -1, -1) if flags[j]), None)
        next_asr = next((j for j in range(i + 1, n) if flags[j]), None)
        if prev_asr is not None and next_asr is not None:
            keep.add(i)
    return sorted(keep)


async def load_clip_groups_by_videos(
    db: aiosqlite.Connection, video_ids: List[str]
) -> List[List[aiosqlite.Row]]:
    groups: List[List[aiosqlite.Row]] = []
    for vid in video_ids:
        async with db.execute(
            "SELECT id, video_id, start_time, end_time, duration, asr_text, vlm_description "
            "FROM clips WHERE video_id = ? ORDER BY start_time ASC, id ASC",
            (vid,),
        ) as cur:
            rows = await cur.fetchall()
        groups.append(list(rows))
    return groups


def _kept_rows_for_video_group(rows: Sequence[aiosqlite.Row], strategy: str) -> List[aiosqlite.Row]:
    if strategy == "asr_fast":
        return [r for r in rows if _clip_has_asr(r["asr_text"])]
    if strategy == "standard":
        return [rows[i] for i in _kept_row_indices_standard(rows)]
    raise ValueError(f"unsupported strategy: {strategy}")


def build_plan_from_clip_groups(
    *,
    clip_groups: Sequence[Sequence[aiosqlite.Row]],
    strategy: str,
    video_title_hint: str | None,
) -> Plan:
    segments: List[SegmentPlan] = []
    total_sec = 0.0
    order = 0
    for rows in clip_groups:
        kept = _kept_rows_for_video_group(rows, strategy)
        for row in kept:
            cid = str(row["id"])
            vid = str(row["video_id"])
            st = float(row["start_time"] or 0.0)
            et = float(row["end_time"] or st)
            if et < st:
                et = st
            text = (row["asr_text"] or "").strip()
            if not text:
                text = "（间隙/环境声）"
            dur = et - st
            total_sec += max(0.0, dur)
            segments.append(
                SegmentPlan(
                    id=f"vq_{order:04d}_{cid[:8]}",
                    order=order,
                    clip_group=[ClipRef(clip_id=cid, video_id=vid, weight=1.0)],
                    selected_clip_ids=[cid],
                    start_time_sec=st,
                    end_time_sec=et,
                    audio_mode="original",
                    subtitle=SubtitlePlan(
                        strategy="asr",
                        text=text,
                        source="asr",
                        timing_hint=TimingHint(start=st, end=et),
                    ),
                )
            )
            order += 1

    label = "极速" if strategy == "asr_fast" else "标准"
    vt = (video_title_hint or "").strip()
    title = f"口播快剪（{label}）· {vt}" if vt else f"口播快剪（{label}）"
    summary = (
        f"基于片段级 ASR 的{label}快剪：共 {len(segments)} 段素材，"
        f"预估总时长约 {total_sec:.1f}s（成片按整段 clip 拼接）。"
    )

    return Plan(
        plan_id=uuid.uuid4().hex[:8],
        title=title,
        summary=summary,
        video_title=vt or None,
        video_description=None,
        mode="original",
        target_duration_sec=None,
        estimated_duration_sec=round(total_sec, 2) if total_sec > 0 else None,
        segments=segments,
        bgm=BGMPlan(enabled=False),
        constraints=None,
        keep_flags=PlanKeepFlags(clips=False, subtitles=False, transitions=False, bgm=False),
    )
