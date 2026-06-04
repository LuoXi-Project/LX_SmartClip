from __future__ import annotations

import math
import re
import statistics
from typing import List, Optional, Sequence

from app.models.auto_edit import Plan, PlanQualityInsight, PlanQualityScores
from app.models.auto_edit_timeline import FinalTimeline, MergedEventPool, PooledEvent, StrategyDSL


def _clamp01(v: float) -> float:
    if math.isnan(v) or math.isinf(v):
        return 0.0
    return max(0.0, min(1.0, float(v)))


def _safe_float(v: object, default: float = 0.0) -> float:
    try:
        f = float(v)  # type: ignore[arg-type]
    except Exception:
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


def _event_lookup(pool: Optional[MergedEventPool]) -> dict[str, PooledEvent]:
    if pool is None:
        return {}
    out: dict[str, PooledEvent] = {}
    for e in pool.events:
        eid = getattr(e, "event_id", None)
        if isinstance(eid, str) and eid:
            out[eid] = e
    return out


def _resolve_event(event_id: str, lookup: dict[str, PooledEvent]) -> Optional[PooledEvent]:
    if not event_id:
        return None
    if event_id in lookup:
        return lookup[event_id]
    base = event_id.split("#", 1)[0]
    return lookup.get(base)


def _event_score(e: Optional[PooledEvent], attr: str, fallback: float = 0.0) -> float:
    if e is None:
        return fallback
    scores = getattr(e, "scores", None)
    if scores is None:
        return fallback
    val = getattr(scores, attr, None)
    if val is None:
        if attr in ("relevance", "clarity"):
            return _safe_float(getattr(scores, "local_score", fallback), fallback)
        return fallback
    return _safe_float(val, fallback)


def _text_hook_boost(text: str) -> float:
    t = (text or "").strip()
    if not t:
        return 0.0
    boost = 0.0
    if re.search(r"[?？!！]", t[:24]):
        boost += 0.08
    if re.search(r"\d", t[:32]):
        boost += 0.05
    if len(t) <= 28:
        boost += 0.05
    strong = ("竟然", "居然", "千万别", "一定要", "为什么", "如何", "secret", "wow")
    if any(k in t.lower() for k in strong):
        boost += 0.06
    return min(0.2, boost)


def _score_hook(first_event: Optional[PooledEvent], first_text: str) -> float:
    base = (
        0.42 * _event_score(first_event, "relevance")
        + 0.28 * _event_score(first_event, "clarity")
        + 0.2 * _event_score(first_event, "local_score")
        + 0.1 * _event_score(first_event, "emotion")
    )
    role = getattr(first_event, "role", None) if first_event else None
    if role == "hook":
        base += 0.12
    elif role in ("context", "highlight"):
        base *= 0.88
    base += _text_hook_boost(first_text)
    return _clamp01(base)


def _score_info_density(texts: Sequence[str], durations: Sequence[float]) -> float:
    total_chars = sum(len((t or "").strip()) for t in texts)
    total_dur = sum(max(0.1, d) for d in durations)
    if total_chars <= 0:
        return 0.35
    cps = total_chars / total_dur
    # 短视频口播/字幕：约 4~10 字/秒较理想
    if cps < 2.0:
        return _clamp01(cps / 2.0 * 0.55)
    if cps <= 10.0:
        return _clamp01(0.55 + (cps - 2.0) / 8.0 * 0.45)
    return _clamp01(max(0.45, 1.0 - (cps - 10.0) / 12.0))


def _score_emotion_curve(events: Sequence[Optional[PooledEvent]]) -> float:
    vals = [_event_score(e, "emotion") for e in events if e is not None]
    if not vals:
        return 0.45
    if len(vals) == 1:
        return _clamp01(0.35 + vals[0] * 0.45)
    spread = max(vals) - min(vals)
    std = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    avg = sum(vals) / len(vals)
    # 适度波动 + 均值不宜过低
    return _clamp01(0.25 + spread * 0.45 + std * 0.35 + avg * 0.15)


def _score_rhythm(
    durations: Sequence[float],
    events: Sequence[Optional[PooledEvent]],
    dsl: StrategyDSL,
) -> float:
    durs = [max(0.1, d) for d in durations if d > 0]
    if not durs:
        return 0.4
    mean = sum(durs) / len(durs)
    std = statistics.pstdev(durs) if len(durs) > 1 else 0.0
    cv = std / mean if mean > 0 else 0.0

    pace = getattr(dsl.style, "pace", "medium") or "medium"
    target_mean = {"fast": 4.0, "medium": 6.0, "slow": 8.5}.get(pace, 6.0)
    pace_fit = 1.0 - min(1.0, abs(mean - target_mean) / target_mean)

    # 适度节奏变化（完全均匀或极度跳跃都不好）
    cv_fit = 1.0 - min(1.0, abs(cv - 0.28) / 0.35)

    roles = [getattr(e, "role", None) for e in events if e is not None]
    structure_bonus = 0.0
    if "hook" in roles:
        structure_bonus += 0.08
    if "highlight" in roles:
        structure_bonus += 0.06
    if "cta" in roles:
        structure_bonus += 0.06

    return _clamp01(0.45 * pace_fit + 0.35 * cv_fit + structure_bonus)


def _score_repetition(clip_ids: Sequence[str], texts: Sequence[str]) -> float:
    """越高表示素材/文案重复越少（新颖度越高）。"""
    clips = [c for c in clip_ids if c]
    texts_norm = [re.sub(r"\s+", "", (t or "").strip().lower()) for t in texts if (t or "").strip()]
    clip_ratio = len(set(clips)) / len(clips) if clips else 1.0
    text_ratio = len(set(texts_norm)) / len(texts_norm) if texts_norm else 1.0
    return _clamp01(0.55 * clip_ratio + 0.45 * text_ratio)


def _score_platform_fit(
    *,
    estimated_duration: float,
    target_duration: Optional[float],
    events: Sequence[Optional[PooledEvent]],
    dsl: StrategyDSL,
    segment_count: int,
) -> float:
    dur = estimated_duration if estimated_duration > 0 else float(target_duration or 0)
    if dur <= 0:
        dur = 45.0

    # 主流竖屏短视频：15~90s，峰值 30~60s
    if dur < 12:
        dur_fit = dur / 12.0 * 0.65
    elif dur <= 60:
        dur_fit = 0.65 + (1.0 - abs(dur - 42.0) / 42.0) * 0.35
    elif dur <= 120:
        dur_fit = max(0.45, 0.85 - (dur - 60.0) / 120.0)
    else:
        dur_fit = 0.35

    roles = {getattr(e, "role", None) for e in events if e is not None}
    structure = 0.0
    if "hook" in roles:
        structure += 0.12
    if "highlight" in roles:
        structure += 0.1
    if "cta" in roles:
        structure += 0.08

    seg_fit = 1.0
    if segment_count < 2:
        seg_fit = 0.45
    elif segment_count > 12:
        seg_fit = max(0.5, 1.0 - (segment_count - 12) * 0.04)

    target_fit = 0.08
    if target_duration and target_duration > 0:
        ratio = dur / float(target_duration)
        target_fit = 0.08 + max(0.0, 0.12 * (1.0 - min(1.0, abs(ratio - 1.0))))

    pace = getattr(dsl.style, "pace", "medium") or "medium"
    pace_bonus = {"fast": 0.06, "medium": 0.04, "slow": 0.02}.get(pace, 0.04)

    return _clamp01(0.5 * dur_fit + structure + 0.18 * seg_fit + target_fit + pace_bonus)


def _overall_score(scores: PlanQualityScores) -> float:
    return _clamp01(
        0.22 * scores.hook
        + 0.16 * scores.info_density
        + 0.14 * scores.emotion_curve
        + 0.16 * scores.rhythm
        + 0.14 * scores.repetition
        + 0.18 * scores.platform_fit
    )


def _grade(overall: float) -> str:
    if overall >= 0.85:
        return "S"
    if overall >= 0.75:
        return "A"
    if overall >= 0.65:
        return "B"
    if overall >= 0.55:
        return "C"
    return "D"


def _pct(v: float) -> str:
    return f"{int(round(v * 100))}%"


def build_recommendation_reasons(scores: PlanQualityScores, events: Sequence[Optional[PooledEvent]]) -> List[str]:
    reasons: List[str] = []

    if scores.hook >= 0.78:
        reasons.append(f"开场 Hook 强（{_pct(scores.hook)}），首 3 秒更易留住划走用户")
    elif scores.hook >= 0.58:
        reasons.append(f"开场具备一定吸引力（Hook {_pct(scores.hook)}），建议预览首段节奏")
    else:
        reasons.append("开场 Hook 偏弱，可考虑替换首段或加强悬念/痛点句")

    if scores.info_density >= 0.72:
        reasons.append(f"信息密度适中（{_pct(scores.info_density)}），短篇幅内要点传递清晰")
    elif scores.info_density >= 0.5:
        reasons.append("信息密度尚可，口播/字幕篇幅与时长匹配度一般")
    else:
        reasons.append("信息密度偏低或过于拥挤，可能影响完播与理解效率")

    if scores.emotion_curve >= 0.68:
        reasons.append(f"情绪曲线有起伏（{_pct(scores.emotion_curve)}），利于制造记忆点")
    elif scores.emotion_curve >= 0.5:
        reasons.append("情绪表达较平，适合知识/说明类；带货/故事类可加强起伏")

    if scores.rhythm >= 0.7:
        reasons.append(f"剪辑节奏与结构较稳（{_pct(scores.rhythm)}），段落切换自然")
    else:
        reasons.append("节奏或结构完整性一般，可关注段落时长是否过于均匀或跳跃")

    if scores.repetition >= 0.82:
        reasons.append(f"素材/文案重复度低（新颖度 {_pct(scores.repetition)}），观感更新鲜")
    elif scores.repetition >= 0.6:
        reasons.append("存在少量素材或文案复用，整体仍可接受")
    else:
        reasons.append("素材或文案重复偏高，可能降低传播新鲜度")

    if scores.platform_fit >= 0.72:
        reasons.append(f"平台适配度较好（{_pct(scores.platform_fit)}），时长与结构贴近短视频传播习惯")
    else:
        reasons.append("平台适配一般，可微调目标时长或补齐 Hook/CTA 结构")

    roles = [getattr(e, "role", None) for e in events if e is not None]
    if roles and roles[0] == "hook" and scores.hook >= 0.65:
        reasons.insert(0, "首段按 Hook 角色编排，符合爆款短视频开场逻辑")

    # 去重并保留前 4 条最有信息量的
    deduped: List[str] = []
    seen = set()
    for r in reasons:
        if r not in seen:
            seen.add(r)
            deduped.append(r)
    return deduped[:4]


def compute_timeline_quality(
    *,
    timeline: FinalTimeline,
    dsl: StrategyDSL,
    pool: Optional[MergedEventPool] = None,
) -> PlanQualityInsight:
    lookup = _event_lookup(pool)
    texts: List[str] = []
    durations: List[float] = []
    clip_ids: List[str] = []
    events: List[Optional[PooledEvent]] = []

    for item in timeline.items:
        text = (item.subtitle_text or "").strip()
        dur = _safe_float(item.duration_budget_sec, 3.0)
        texts.append(text)
        durations.append(max(0.1, dur))
        clip_ids.append(str(item.clip_id or ""))
        events.append(_resolve_event(str(item.event_id or ""), lookup))

    first_text = texts[0] if texts else ""
    first_event = events[0] if events else None
    est = float(timeline.total_duration_sec_est or sum(durations))

    scores = PlanQualityScores(
        hook=_score_hook(first_event, first_text),
        info_density=_score_info_density(texts, durations),
        emotion_curve=_score_emotion_curve(events),
        rhythm=_score_rhythm(durations, events, dsl),
        repetition=_score_repetition(clip_ids, texts),
        platform_fit=_score_platform_fit(
            estimated_duration=est,
            target_duration=float(dsl.target_duration_sec) if dsl.target_duration_sec else None,
            events=events,
            dsl=dsl,
            segment_count=len(timeline.items),
        ),
    )
    overall = _overall_score(scores)
    reasons = build_recommendation_reasons(scores, events)
    summary = (
        f"综合 {_pct(overall)}（{_grade(overall)}），"
        f"Hook {_pct(scores.hook)} · 平台适配 {_pct(scores.platform_fit)}"
    )
    return PlanQualityInsight(
        scores=scores,
        overall=overall,
        grade=_grade(overall),
        summary=summary,
        reasons=reasons,
    )


def compute_plan_quality_from_segments(
    plan: Plan,
    dsl: Optional[StrategyDSL] = None,
) -> PlanQualityInsight:
    """无事件池时，基于 Plan.segments 做启发式评分（LLM 直出 / V0 回退方案）。"""
    from app.core.auto_edit_v2.plan_compile import build_v0_dsl_from_request

    if dsl is None:
        dsl = build_v0_dsl_from_request(plan.summary or "auto_edit", plan.mode, None)

    texts: List[str] = []
    durations: List[float] = []
    clip_ids: List[str] = []
    t = 0.0
    for seg in plan.segments or []:
        if getattr(seg, "exclude_from_output", False):
            continue
        text = (getattr(getattr(seg, "subtitle", None), "text", "") or "").strip()
        start = _safe_float(getattr(seg, "start_time_sec", t), t)
        end = _safe_float(getattr(seg, "end_time_sec", start + 3.0), start + 3.0)
        dur = max(0.1, end - start)
        texts.append(text)
        durations.append(dur)
        cid = (seg.selected_clip_ids or [None])[0]
        clip_ids.append(str(cid or ""))
        t = end

    fake_events: List[Optional[PooledEvent]] = [None] * len(texts)
    est = _safe_float(plan.estimated_duration_sec, sum(durations))

    scores = PlanQualityScores(
        hook=_score_hook(None, texts[0] if texts else "") * 0.92,
        info_density=_score_info_density(texts, durations),
        emotion_curve=_score_emotion_curve(fake_events),
        rhythm=_score_rhythm(durations, fake_events, dsl),
        repetition=_score_repetition(clip_ids, texts),
        platform_fit=_score_platform_fit(
            estimated_duration=est,
            target_duration=_safe_float(plan.target_duration_sec, 0.0) or None,
            events=fake_events,
            dsl=dsl,
            segment_count=len(texts),
        ),
    )
    overall = _overall_score(scores)
    reasons = build_recommendation_reasons(scores, fake_events)
    summary = (
        f"综合 {_pct(overall)}（{_grade(overall)}），"
        f"Hook {_pct(scores.hook)} · 平台适配 {_pct(scores.platform_fit)}"
    )
    return PlanQualityInsight(
        scores=scores,
        overall=overall,
        grade=_grade(overall),
        summary=summary,
        reasons=reasons,
    )


def sort_plans_by_quality(plans: Sequence[Plan]) -> List[Plan]:
    """按综合分降序排列，便于前端默认展示最优方案。"""
    return sorted(
        list(plans),
        key=lambda p: _safe_float(getattr(getattr(p, "quality", None), "overall", 0.0), 0.0),
        reverse=True,
    )
