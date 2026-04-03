"""口播快剪：基于 clips.asr_segments（句子级）生成原声 Plan。"""
from __future__ import annotations

import json
import uuid
from typing import Any, List, Sequence

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


def _parse_asr_segments(asr_segments_json: str | None) -> list[dict[str, Any]]:
    if not asr_segments_json:
        return []
    try:
        data = json.loads(asr_segments_json)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        # 允许 whisper/openai 结果里字段名稍有差异，但本项目约定为 start/end/text
        out.append(item)
    return out


def _is_meaningful_text(text: str | None) -> bool:
    if not text:
        return False
    t = str(text).strip()
    if not t:
        return False
    if t in ("…", "……", "..."):
        return False

    # 过滤“全是标点/符号”的单位，保留至少一个字母/数字/CJK 字
    meaningful = "".join(
        ch
        for ch in t
        if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff")
    )
    return bool(meaningful)


async def load_clip_groups_by_videos(
    db: aiosqlite.Connection, video_ids: List[str]
) -> List[List[aiosqlite.Row]]:
    groups: List[List[aiosqlite.Row]] = []
    for vid in video_ids:
        async with db.execute(
            "SELECT id, video_id, start_time, duration, asr_text, asr_segments "
            "FROM clips WHERE video_id = ? ORDER BY start_time ASC, id ASC",
            (vid,),
        ) as cur:
            rows = await cur.fetchall()
        groups.append(list(rows))
    return groups


def build_plan_from_clip_groups(
    *,
    clip_groups: Sequence[Sequence[aiosqlite.Row]],
    strategy: str,
    video_title_hint: str | None,
) -> Plan:
    if strategy not in ("asr_fast", "standard"):
        raise ValueError(f"unsupported strategy: {strategy}")

    # MVP：standard 暂时与 asr_fast 等价（均用 clips.asr_segments 精确裁剪）。
    label = "极速" if strategy == "asr_fast" else "标准"

    segments: List[SegmentPlan] = []
    total_sec = 0.0
    order = 0

    for rows in clip_groups:
        for row in rows:
            cid = str(row["id"])
            vid = str(row["video_id"])

            clip_base = float(row["start_time"] or 0.0)
            clip_dur = float(row["duration"] or 0.0)
            asr_segments_json = row["asr_segments"]
            seg_items = _parse_asr_segments(asr_segments_json)

            # 回退：没有 segments，就按整段 clip（仍可通过 override_duration_sec=clip_dur 移除尾部静音，若 clips.duration 已裁剪对齐）
            if not seg_items:
                if not _clip_has_asr(row["asr_text"]):
                    continue
                st_rel = 0.0
                et_rel = clip_dur if clip_dur > 0 else st_rel + 1.0
                text = (row["asr_text"] or "").strip() or "（间隙/环境声）"
                dur = max(0.0, et_rel - st_rel)
                if dur <= 0:
                    continue
                total_sec += dur
                segments.append(
                    SegmentPlan(
                        id=f"vq_{order:04d}_{cid[:8]}",
                        order=order,
                        clip_group=[ClipRef(clip_id=cid, video_id=vid, weight=1.0)],
                        selected_clip_ids=[cid],
                        start_time_sec=clip_base + st_rel,
                        end_time_sec=clip_base + et_rel,
                        override_duration_sec=dur,
                        clip_start_offset_sec=st_rel,
                        audio_mode="original",
                        subtitle=SubtitlePlan(
                            strategy="asr",
                            text=text,
                            source="asr",
                            timing_hint=TimingHint(
                                start=clip_base + st_rel, end=clip_base + et_rel
                            ),
                        ),
                    )
                )
                order += 1
                continue

            for idx, seg in enumerate(seg_items):
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

                dur = et_rel - st_rel
                if dur <= 0:
                    continue
                total_sec += dur

                st_abs = clip_base + st_rel
                et_abs = clip_base + et_rel
                segments.append(
                    SegmentPlan(
                        id=f"vq_{order:04d}_{cid[:6]}_{idx:03d}",
                        order=order,
                        clip_group=[ClipRef(clip_id=cid, video_id=vid, weight=1.0)],
                        selected_clip_ids=[cid],
                        # start/end 使用“绝对时间”，便于前端展示/预览；裁剪偏移用 clip_start_offset_sec 表示 clip 内起点
                        start_time_sec=st_abs,
                        end_time_sec=et_abs,
                        override_duration_sec=dur,
                        clip_start_offset_sec=st_rel,
                        audio_mode="original",
                        subtitle=SubtitlePlan(
                            strategy="asr",
                            text=text,
                            source="asr",
                            timing_hint=TimingHint(start=st_abs, end=et_abs),
                        ),
                    )
                )
                order += 1

    vt = (video_title_hint or "").strip()
    title = f"口播快剪（{label}）· {vt}" if vt else f"口播快剪（{label}）"
    summary = (
        f"基于 ASR 句子级 segments 的{label}快剪：共 {len(segments)} 段，"
        f"预估总时长约 {total_sec:.1f}s（按句子区间 -ss/-t 精确裁剪）。"
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
        keep_flags=PlanKeepFlags(
            clips=False, subtitles=False, transitions=False, bgm=False
        ),
    )
