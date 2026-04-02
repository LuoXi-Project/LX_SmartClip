from __future__ import annotations

import math
from typing import List, Optional

from app.models.auto_edit_timeline import FinalTimeline, MergedEventPool, StrategyDSL, TimelineItem


def _safe_float(v: object, default: float) -> float:
    try:
        f = float(v)  # type: ignore[arg-type]
    except Exception:
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


def _estimate_item_duration(text: str, *, pace: str) -> float:
    """
    粗估时长（V1 简化）：
    - fast: 3~5s
    - medium: 4~7s
    - slow: 6~10s
    """
    t = (text or "").strip()
    n = max(1, len(t))
    if pace == "fast":
        base = 2.5 + n / 18.0
        return max(2.5, min(6.0, base))
    if pace == "slow":
        base = 5.0 + n / 12.0
        return max(4.5, min(12.0, base))
    base = 3.5 + n / 15.0
    return max(3.0, min(9.0, base))


def arrange_timeline(
    *,
    pool: MergedEventPool,
    dsl: StrategyDSL,
    mode: str,
    target_duration_sec: Optional[int],
) -> FinalTimeline:
    """
    编排器（V1 简化版，规则优先）：
    - 按 tier_budget_ratio 从 Tier1/2/3 选入时间线
    - 每个事件生成 1 个 TimelineItem（可被编译为 SegmentPlan）
    """
    items: List[TimelineItem] = []

    target = float(target_duration_sec or dsl.target_duration_sec or 0.0)
    if target <= 0:
        target = 60.0

    ratio = dsl.constraints.tier_budget_ratio
    b1 = target * _safe_float(ratio.tier1, 0.7)
    b2 = target * _safe_float(ratio.tier2, 0.25)
    b3 = max(0.0, target - b1 - b2)
    b3 = max(b3, target * _safe_float(ratio.tier3, 0.05))

    def _pick(events, budget: float):
        nonlocal items
        used = 0.0
        for e in events:
            if used >= budget:
                break
            text = (e.text or "").strip()
            if not text:
                # V1：进入成片的事件必须有文案，否则跳过
                continue
            dur = _estimate_item_duration(text, pace=dsl.style.pace)
            if used + dur > budget and used > 0:
                break
            items.append(
                TimelineItem(
                    event_id=e.event_id,
                    clip_id=e.clip_id,
                    subtitle_text=text,
                    audio_mode="tts" if mode in ("auto", "voiceover") else "original",
                    duration_budget_sec=dur,
                )
            )
            used += dur

    # pool.events 已按 global_rank 排序（merge_rank.assign_tiers_and_rank）
    t1 = [e for e in pool.events if e.tier == 1]
    t2 = [e for e in pool.events if e.tier == 2]
    t3 = [e for e in pool.events if e.tier == 3]

    _pick(t1, b1)
    _pick(t2, b2)
    _pick(t3, b3)

    total = sum((it.duration_budget_sec or 0.0) for it in items)
    return FinalTimeline(items=items, total_duration_sec_est=total if total > 0 else None)

