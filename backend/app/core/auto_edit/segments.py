from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

import aiosqlite

from app.api.tts import SynthesizeRequest, SynthesizeResponse, synthesize as tts_synthesize
from app.db.database import DB_PATH
from app.models.auto_edit import Plan, SegmentPlan
from app.models.subtitle import SubtitleSegmentInput

logger = logging.getLogger(__name__)

# 同一 clip 内相邻段「首尾相接」判定容差（秒）：ASR 浮点 / 关键帧对齐
_CONTIGUOUS_EPS_SEC = 0.1


@dataclass
class ClipCandidate:
    id: str
    video_id: str
    start_time: float
    end_time: float
    duration: float


def merge_contiguous_subtitle_segments(
    segments: List[SubtitleSegmentInput],
    eps_sec: float = _CONTIGUOUS_EPS_SEC,
) -> List[SubtitleSegmentInput]:
    """
    将时间轴上连续、且同一主 clip 的相邻段合并为一段，减少重复 -ss/-t / concat 次数。

    条件：相同 clip_id 与 clip_ids、均无独立 TTS 文件、均有正数 duration_sec，
    且下一段 clip 内起点 ≈ 上一段起点 + 时长（容差 eps_sec）。
    """
    if len(segments) <= 1:
        return segments

    def _norm_ids(seg: SubtitleSegmentInput) -> Tuple[str, ...]:
        ids = list(seg.clip_ids or [])
        if not ids and seg.clip_id:
            ids = [seg.clip_id]
        return tuple(dict.fromkeys(ids))

    def _can_merge(a: SubtitleSegmentInput, b: SubtitleSegmentInput) -> bool:
        if a.clip_id != b.clip_id:
            return False
        if _norm_ids(a) != _norm_ids(b):
            return False
        if getattr(a, "tts_filename", None) or getattr(b, "tts_filename", None):
            return False
        da = a.duration_sec
        db = b.duration_sec
        if da is None or db is None or float(da) <= 0 or float(db) <= 0:
            return False
        sa = float(a.clip_start_sec or 0.0)
        sb = float(b.clip_start_sec or 0.0)
        expected = sa + float(da)
        gap = sb - expected
        return abs(gap) <= eps_sec

    def _merge_two(a: SubtitleSegmentInput, b: SubtitleSegmentInput) -> SubtitleSegmentInput:
        ta = (a.copy_text or "").strip()
        tb = (b.copy_text or "").strip()
        merged_text = "\n".join(x for x in (ta, tb) if x)
        da = float(a.duration_sec or 0.0)
        db = float(b.duration_sec or 0.0)
        return SubtitleSegmentInput(
            copy_text=merged_text,
            clip_id=a.clip_id,
            clip_ids=a.clip_ids,
            tts_filename=None,
            clip_start_sec=a.clip_start_sec,
            duration_sec=da + db,
        )

    out: List[SubtitleSegmentInput] = []
    cur = segments[0]
    for nxt in segments[1:]:
        if _can_merge(cur, nxt):
            cur = _merge_two(cur, nxt)
        else:
            out.append(cur)
            cur = nxt
    out.append(cur)
    return out


def collect_plan_clip_ids(plan: Plan) -> List[str]:
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


async def segments_from_plan(
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
    tts_concurrency_raw: str = "3"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT value FROM config WHERE key = ?",
            ("tts_concurrency",),
        ) as cur:
            row = await cur.fetchone()
            if row is not None:
                # sqlite3.Row / aiosqlite.Row 不支持 dict.get
                try:
                    v = row["value"]
                except Exception:
                    v = row[0] if len(row) > 0 else None
                if v is not None:
                    tts_concurrency_raw = str(v)

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

    seg_inputs: List[SubtitleSegmentInput] = []
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
                duration_sec=float(seg.override_duration_sec) if seg.override_duration_sec else None,
                clip_start_sec=float(seg.clip_start_offset_sec) if getattr(seg, "clip_start_offset_sec", None) is not None else None,
            )
        )

    return merge_contiguous_subtitle_segments(seg_inputs)

