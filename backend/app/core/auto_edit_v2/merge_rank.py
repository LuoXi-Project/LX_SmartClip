from __future__ import annotations

import hashlib
import math
from typing import Iterable, List, Optional, Tuple

from app.models.auto_edit_timeline import ClipEventsBatch, MergedEventPool, PooledEvent


def _safe_float(v: object, default: float = 0.0) -> float:
    try:
        f = float(v)  # type: ignore[arg-type]
    except Exception:
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


def _sig(clip_id: str, text: str, start: Optional[float], end: Optional[float]) -> str:
    base = f"{clip_id}|{(text or '').strip()}|{start or ''}|{end or ''}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()[:12]


def _global_score(e: PooledEvent) -> float:
    s = e.scores
    local = _safe_float(getattr(s, "local_score", 0.0), 0.0)
    rel = _safe_float(getattr(s, "relevance", None), local)
    clr = _safe_float(getattr(s, "clarity", None), local)
    emo = _safe_float(getattr(s, "emotion", None), 0.0)
    # 简单加权：先让 relevance/clarity 主导，emotion 轻权重
    score = 0.45 * rel + 0.35 * clr + 0.15 * local + 0.05 * emo
    return max(0.0, min(1.0, score))


def merge_batches(batches: Iterable[ClipEventsBatch]) -> List[PooledEvent]:
    """
    批间汇总（V1 简化版）：
    - 事件去重：按 clip_id + (text/time_range) 签名
    - 分数合并：同签名取 max(global_score)
    """
    merged: dict[str, PooledEvent] = {}
    for b in batches:
        for ev in b.events:
            tr = ev.time_range
            s = _sig(ev.clip_id, ev.text, getattr(tr, "start_sec", None) if tr else None, getattr(tr, "end_sec", None) if tr else None)
            pe = PooledEvent(**ev.model_dump())
            pe.global_score = _global_score(pe)
            pe.event_id = pe.event_id or f"e_{s}"
            old = merged.get(s)
            if old is None or (pe.global_score or 0.0) > (old.global_score or 0.0):
                merged[s] = pe
    return list(merged.values())


def assign_tiers_and_rank(events: List[PooledEvent]) -> MergedEventPool:
    """
    Tier 划分（V1 简化版）：
    - 先按 global_score 降序排序
    - top 20% => Tier1, next 30% => Tier2, rest => Tier3
    """
    items = list(events)
    items.sort(key=lambda e: float(e.global_score or 0.0), reverse=True)
    n = len(items)
    if n == 0:
        return MergedEventPool(events=[])
    t1 = max(1, int(round(n * 0.2)))
    t2 = max(t1 + 1, int(round(n * 0.5)))
    for i, e in enumerate(items, 1):
        e.global_rank = i
        if i <= t1:
            e.tier = 1
        elif i <= t2:
            e.tier = 2
        else:
            e.tier = 3
    return MergedEventPool(events=items)


def split_by_tier(pool: MergedEventPool) -> Tuple[List[PooledEvent], List[PooledEvent], List[PooledEvent]]:
    t1, t2, t3 = [], [], []
    for e in pool.events:
        if e.tier == 1:
            t1.append(e)
        elif e.tier == 2:
            t2.append(e)
        else:
            t3.append(e)
    return t1, t2, t3

