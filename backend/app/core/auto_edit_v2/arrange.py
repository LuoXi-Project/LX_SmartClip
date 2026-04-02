from __future__ import annotations

import math
import random
import zlib
from typing import List, Optional, Sequence, Set, Tuple

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


def _stable_seed(*parts: str) -> int:
    s = "|".join([p for p in parts if p is not None])
    return int(zlib.crc32(s.encode("utf-8")) & 0xFFFFFFFF)


def _weighted_shuffle(events: Sequence, rng: random.Random) -> List:
    """
    稳定地制造“有差异但不会太离谱”的候选顺序：
    - 越靠前(rank 越小 / score 越高)的事件更容易在前面
    - 但不同 seed 会带来不同排列，从而生成多方案
    """
    scored: List[Tuple[float, object]] = []
    for e in events:
        gs = getattr(e, "global_score", None)
        gr = getattr(e, "global_rank", None)
        base = 0.0
        if isinstance(gs, (int, float)) and not math.isnan(float(gs)) and not math.isinf(float(gs)):
            base += float(gs) * 1.5
        if isinstance(gr, int) and gr > 0:
            base += 1.0 / (1.0 + float(gr))
        # 噪声项让不同 seed 产生不同顺序；base 越大，越不容易被噪声拉走
        noise = rng.random()
        key = -(base * 10.0 + noise)
        scored.append((key, e))
    scored.sort(key=lambda x: x[0])
    return [e for _, e in scored]


def arrange_timeline_variants(
    *,
    pool: MergedEventPool,
    dsl: StrategyDSL,
    mode: str,
    target_duration_sec: Optional[int],
    num_plans: int,
    seed_hint: Optional[str] = None,
) -> List[FinalTimeline]:
    """
    生成多个候选时间轴（V1 简化版）：
    - 同一事件池下，通过 seed 变化 + 加权洗牌 + 轻微预算扰动，生成 n 个不同 timeline
    - 保留原有 `arrange_timeline` 的“规则优先”取用逻辑与时长估算
    """
    n = int(num_plans or 1)
    n = max(1, min(5, n))

    target = float(target_duration_sec or dsl.target_duration_sec or 0.0)
    if target <= 0:
        target = 60.0

    ratio = dsl.constraints.tier_budget_ratio
    base_b1 = target * _safe_float(ratio.tier1, 0.7)
    base_b2 = target * _safe_float(ratio.tier2, 0.25)
    base_b3 = max(0.0, target - base_b1 - base_b2)
    base_b3 = max(base_b3, target * _safe_float(ratio.tier3, 0.05))

    t1 = [e for e in pool.events if e.tier == 1]
    t2 = [e for e in pool.events if e.tier == 2]
    t3 = [e for e in pool.events if e.tier == 3]

    def _pick(events, budget: float, *, rng: random.Random, used_event_ids: Set[str]) -> List[TimelineItem]:
        items: List[TimelineItem] = []
        used = 0.0
        for e in events:
            if used >= budget:
                break
            eid = getattr(e, "event_id", None)
            if isinstance(eid, str) and eid in used_event_ids:
                continue
            text = (getattr(e, "text", "") or "").strip()
            if not text:
                continue
            dur = _estimate_item_duration(text, pace=dsl.style.pace)
            if used + dur > budget and used > 0:
                break
            clip_id = getattr(e, "clip_id", "")
            event_id = getattr(e, "event_id", "") or f"e_{rng.randint(1, 10**9)}"
            items.append(
                TimelineItem(
                    event_id=event_id,
                    clip_id=str(clip_id),
                    subtitle_text=text,
                    audio_mode="tts" if mode in ("auto", "voiceover") else "original",
                    duration_budget_sec=dur,
                )
            )
            if isinstance(eid, str) and eid:
                used_event_ids.add(eid)
            used += dur
        return items

    timelines: List[FinalTimeline] = []
    base_seed = _stable_seed(dsl.goal or "auto_edit", seed_hint or "", str(len(pool.events)))
    for i in range(n):
        rng = random.Random(base_seed + i * 9973)

        # 轻微扰动 tier budget，保证“更像不同方案”，但不会偏离 DSL 太远
        jitter = (rng.random() - 0.5) * 0.12  # [-0.06, +0.06]
        b1 = max(0.0, base_b1 * (1.0 + jitter))
        b2 = max(0.0, base_b2 * (1.0 - jitter * 0.7))
        b3 = max(0.0, target - b1 - b2)
        b3 = max(b3, base_b3 * (1.0 + jitter * 0.4))

        used_event_ids: Set[str] = set()

        s1 = _weighted_shuffle(t1, rng)
        s2 = _weighted_shuffle(t2, rng)
        s3 = _weighted_shuffle(t3, rng)

        items: List[TimelineItem] = []
        items.extend(_pick(s1, b1, rng=rng, used_event_ids=used_event_ids))
        items.extend(_pick(s2, b2, rng=rng, used_event_ids=used_event_ids))
        items.extend(_pick(s3, b3, rng=rng, used_event_ids=used_event_ids))

        total = sum((it.duration_budget_sec or 0.0) for it in items)
        timelines.append(FinalTimeline(items=items, total_duration_sec_est=total if total > 0 else None))

    # 去重：如果 seed 导致完全相同，至少保留 1 个
    uniq: List[FinalTimeline] = []
    seen: Set[Tuple[str, ...]] = set()
    for tl in timelines:
        sig = tuple(f"{it.clip_id}:{(it.subtitle_text or '').strip()}" for it in tl.items)
        if sig and sig not in seen:
            seen.add(sig)
            uniq.append(tl)
    return uniq if uniq else timelines[:1]

