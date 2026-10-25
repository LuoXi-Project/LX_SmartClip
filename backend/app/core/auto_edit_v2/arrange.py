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


def _exceed_clip_quota(*, clip_id: str, clip_counts: dict[str, int], max_events_per_clip: int) -> bool:
    if max_events_per_clip <= 0:
        return False
    return clip_counts.get(clip_id, 0) >= max_events_per_clip


def _touch_clip_quota(*, clip_id: str, clip_counts: dict[str, int]) -> None:
    clip_counts[clip_id] = clip_counts.get(clip_id, 0) + 1


# 节奏档位对应的单镜头时长上下限（秒）：fast 快切 / medium 常速 / slow 长镜
_PACE_SHOT_BOUNDS = {
    "fast": (1.2, 3.5),
    "medium": (1.8, 6.0),
    "slow": (3.0, 10.0),
}

# 相邻多样性：最近 N 个已选片段构成“邻接窗口”，窗口内禁止复用同一素材
_ADJACENCY_WINDOW = 2


def _shot_bounds(dsl: StrategyDSL) -> Tuple[float, float]:
    """解析单镜头时长上下限：显式 constraints 覆盖 > pace 档位默认。"""
    lo, hi = _PACE_SHOT_BOUNDS.get(getattr(dsl.style, "pace", "medium"), (1.8, 6.0))
    c = getattr(dsl, "constraints", None)
    if c is not None:
        if getattr(c, "min_shot_sec", None) is not None:
            lo = max(0.5, float(c.min_shot_sec))
        if getattr(c, "max_shot_sec", None) is not None:
            hi = float(c.max_shot_sec)
    if hi < lo:
        hi = lo
    return lo, hi


def _recently_used(clip_id: str, recent: List[str], *, enabled: bool) -> bool:
    if not enabled or not clip_id:
        return False
    return clip_id in recent[-_ADJACENCY_WINDOW:]


def _clamp_shot_duration(dur: float, bounds: Tuple[float, float]) -> float:
    lo, hi = bounds
    return max(0.5, max(lo, min(hi, dur)))


def _hook_shot_bounds(bounds: Tuple[float, float]) -> Tuple[float, float]:
    """钩子镜头节奏：在全局区间上收紧到「短促」区间，服务前 3 秒完播。"""
    lo, hi = bounds
    h_lo = max(0.9, lo * 0.6)
    h_hi = max(h_lo, min(hi, 3.0))
    return h_lo, h_hi


def _promote_hook_first(items: List[TimelineItem], pool: MergedEventPool) -> List[TimelineItem]:
    """把 hook 角色的事件稳定前移到时间轴开头（完播实践：钩子必须最先出现）。

    仅调整顺序、不增删镜头；事件角色缺失或无 hook 时保持原顺序。
    补齐时长产生的复用条目（event_id 形如 e1#r2_2）按其基础事件判断角色。
    """
    if not items:
        return items
    role_by_event: dict[str, object] = {}
    for e in pool.events:
        eid = getattr(e, "event_id", None)
        if isinstance(eid, str) and eid:
            role_by_event[eid] = getattr(e, "role", None)

    def _is_hook(it: TimelineItem) -> bool:
        base_id = (it.event_id or "").split("#", 1)[0]
        return role_by_event.get(base_id) == "hook"

    hooks = [it for it in items if _is_hook(it)]
    if not hooks or len(hooks) == len(items):
        return items
    rest = [it for it in items if not _is_hook(it)]
    return hooks + rest


def _fill_timeline_by_reuse(
    *,
    items: List[TimelineItem],
    target_duration: float,
    mode: str,
) -> List[TimelineItem]:
    """
    当候选事件不足导致总时长明显短于目标时长，允许复用素材补齐时长。
    规则：
    - 仅在已有 items 时启用
    - 按原有顺序循环补充，保持节奏稳定
    - 最后一段按剩余时长裁剪，避免显著超时
    """
    if target_duration <= 0:
        return items
    if not items:
        return items

    current = float(sum((it.duration_budget_sec or 0.0) for it in items))
    if current >= target_duration * 0.92:
        return items

    # auto/voiceover 以 TTS 字幕为主，不能重复文案；改为“拉长时长预算”而非复制条目。
    if mode in ("auto", "voiceover"):
        # 先按比例整体拉伸，再做轮转微调直至接近目标
        factor = max(1.0, target_duration / max(0.1, current))
        for it in items:
            base = float(it.duration_budget_sec or 3.0)
            it.duration_budget_sec = min(20.0, max(0.5, base * factor))
        current = float(sum((it.duration_budget_sec or 0.0) for it in items))
        i = 0
        while current < target_duration * 0.98 and items:
            idx = i % len(items)
            cur = float(items[idx].duration_budget_sec or 0.0)
            if cur < 24.0:
                step = min(1.0, target_duration - current)
                items[idx].duration_budget_sec = cur + max(0.2, step)
                current += max(0.2, step)
            i += 1
            if i > len(items) * 80:
                break
        return items

    base = list(items)
    cycle = 0
    while current < target_duration and base:
        cycle += 1
        for j, it in enumerate(base, 1):
            if current >= target_duration:
                break
            dur = float(it.duration_budget_sec or 3.0)
            remain = max(0.0, target_duration - current)
            if remain <= 0.0:
                break
            next_dur = dur if remain >= dur else max(0.5, remain)
            items.append(
                TimelineItem(
                    event_id=f"{it.event_id}#r{cycle}_{j}",
                    clip_id=it.clip_id,
                    subtitle_text=it.subtitle_text,
                    audio_mode=it.audio_mode,
                    duration_budget_sec=next_dur,
                )
            )
            current += next_dur
    return items


def arrange_timeline(
    *,
    pool: MergedEventPool,
    dsl: StrategyDSL,
    mode: str,
    target_duration_sec: Optional[int],
) -> FinalTimeline:
    """
    编排器：
    - template_preset != None：按 slot role 顺序强制取事件（模板剪辑逻辑）
    - 否则：按 tier_budget_ratio 从 Tier1/2/3 选入事件（兼容“一键智能剪辑”旧表现）
    """
    if dsl.template_preset is not None:
        roles_sequence = list(dsl.style.structure or [])
        if not roles_sequence:
            roles_sequence = ["hook", "context", "highlight", "cta"]

        target = float(target_duration_sec or dsl.target_duration_sec or 0.0)
        if target <= 0:
            target = 60.0
        per_slot = target / float(max(1, len(roles_sequence)))

        used_event_ids: Set[str] = set()
        clip_counts: dict[str, int] = {}
        max_events_per_clip = int(getattr(dsl.constraints, "max_events_per_clip", 6) or 6)
        avoid_adjacent = bool(getattr(dsl.constraints, "avoid_adjacent_same_clip", True))
        recent_clips: List[str] = []
        shot_bounds = _shot_bounds(dsl)
        items: List[TimelineItem] = []

        # pool.events 已按 global_rank/score 排序（merge_rank.assign_tiers_and_rank）
        for role in roles_sequence:
            pick = None
            for e in pool.events:
                eid = getattr(e, "event_id", None)
                if not isinstance(eid, str) or not eid or eid in used_event_ids:
                    continue
                if getattr(e, "role", None) != role:
                    continue
                clip_id = str(getattr(e, "clip_id", "") or "")
                if _exceed_clip_quota(
                    clip_id=clip_id,
                    clip_counts=clip_counts,
                    max_events_per_clip=max_events_per_clip,
                ):
                    continue
                if _recently_used(clip_id, recent_clips, enabled=avoid_adjacent):
                    continue
                text = (e.text or "").strip()
                if not text:
                    continue
                pick = e
                break

            # slot 缺失：兜底取任意最高分未使用事件（不检查邻接，保底出片）
            if pick is None:
                for e in pool.events:
                    eid = getattr(e, "event_id", None)
                    if not isinstance(eid, str) or not eid or eid in used_event_ids:
                        continue
                    clip_id = str(getattr(e, "clip_id", "") or "")
                    if _exceed_clip_quota(
                        clip_id=clip_id,
                        clip_counts=clip_counts,
                        max_events_per_clip=max_events_per_clip,
                    ):
                        continue
                    text = (e.text or "").strip()
                    if not text:
                        continue
                    pick = e
                    break

            if pick is None:
                continue

            used_event_ids.add(pick.event_id)
            pick_clip_id = str(pick.clip_id)
            _touch_clip_quota(clip_id=pick_clip_id, clip_counts=clip_counts)
            recent_clips.append(pick_clip_id)
            text = (pick.text or "").strip()
            dur_est = _estimate_item_duration(text, pace=dsl.style.pace)
            dur = _clamp_shot_duration(max(0.5, min(per_slot, dur_est)), shot_bounds)

            items.append(
                TimelineItem(
                    event_id=pick.event_id,
                    clip_id=pick.clip_id,
                    subtitle_text=text,
                    audio_mode="tts" if mode in ("auto", "voiceover") else "original",
                    duration_budget_sec=dur,
                )
            )

        items = _fill_timeline_by_reuse(items=items, target_duration=target, mode=mode)
        total = sum((it.duration_budget_sec or 0.0) for it in items)
        return FinalTimeline(items=items, total_duration_sec_est=total if total > 0 else None)

    # 非模板：保持旧“按 tier 预算选取”编排器逻辑
    items: List[TimelineItem] = []
    clip_counts: dict[str, int] = {}
    max_events_per_clip = int(getattr(dsl.constraints, "max_events_per_clip", 6) or 6)
    adjacency_on = [bool(getattr(dsl.constraints, "avoid_adjacent_same_clip", True))]
    recent_clips: List[str] = []
    shot_bounds = _shot_bounds(dsl)

    target = float(target_duration_sec or dsl.target_duration_sec or 0.0)
    if target <= 0:
        target = 60.0

    ratio = dsl.constraints.tier_budget_ratio
    b1 = target * _safe_float(ratio.tier1, 0.7)
    b2 = target * _safe_float(ratio.tier2, 0.25)
    b3 = max(0.0, target - b1 - b2)
    b3 = max(b3, target * _safe_float(ratio.tier3, 0.05))

    def _pick(events, budget: float) -> None:
        used = 0.0
        for e in events:
            if used >= budget:
                break
            text = (e.text or "").strip()
            if not text:
                continue
            clip_id = str(getattr(e, "clip_id", "") or "")
            if _exceed_clip_quota(
                clip_id=clip_id,
                clip_counts=clip_counts,
                max_events_per_clip=max_events_per_clip,
            ):
                continue
            if _recently_used(clip_id, recent_clips, enabled=adjacency_on[0]):
                continue
            bounds = (
                _hook_shot_bounds(shot_bounds) if getattr(e, "role", None) == "hook" else shot_bounds
            )
            dur = _clamp_shot_duration(
                _estimate_item_duration(text, pace=dsl.style.pace), bounds
            )
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
            _touch_clip_quota(clip_id=clip_id, clip_counts=clip_counts)
            recent_clips.append(clip_id)
            used += dur

    # pool.events 已按 global_rank/score 排序（merge_rank.assign_tiers_and_rank）
    t1 = [e for e in pool.events if e.tier == 1]
    t2 = [e for e in pool.events if e.tier == 2]
    t3 = [e for e in pool.events if e.tier == 3]

    _pick(t1, b1)
    _pick(t2, b2)
    _pick(t3, b3)

    # 素材池被邻接约束耗尽（一个镜头都没选上）：放宽邻接约束保底出片
    if not items and adjacency_on[0]:
        adjacency_on[0] = False
        _pick(t1, b1)
        _pick(t2, b2)
        _pick(t3, b3)

    # 钩子前置：完播实践——前 3 秒必须是最抓人的画面
    items = _promote_hook_first(items, pool)

    items = _fill_timeline_by_reuse(items=items, target_duration=target, mode=mode)
    total = sum((it.duration_budget_sec or 0.0) for it in items)
    return FinalTimeline(items=items, total_duration_sec_est=total if total > 0 else None)


def _stable_seed(*parts: str) -> int:
    s = "|".join([p for p in parts if p is not None])
    return int(zlib.crc32(s.encode("utf-8")) & 0xFFFFFFFF)


def _weighted_shuffle(events: Sequence, rng: random.Random, *, diversity: float = 1.0) -> List:
    """
    稳定地制造“有差异但不会太离谱”的候选顺序：
    - 越靠前(rank 越小 / score 越高)的事件更容易在前面
    - 但不同 seed 会带来不同排列，从而生成多方案

    diversity 放大噪声权重（默认 1.0），用于在多方案场景下制造更大差异，
    避免去重后候选方案数量不足。
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
        # 噪声项让不同 seed 产生不同顺序；diversity 越大噪声影响越强，越容易选出不同事件
        noise = rng.random() * diversity
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
    生成多个候选时间轴：
    - template_preset != None：按 slot role 顺序强制取事件（模板剪辑逻辑）
    - 否则：保持旧的 tier 预算 + 加权洗牌差异化逻辑（兼容“一键智能剪辑”旧表现）
    """
    if dsl.template_preset is not None:
        roles_sequence = list(dsl.style.structure or [])
        if not roles_sequence:
            roles_sequence = ["hook", "context", "highlight", "cta"]

        n = int(num_plans or 1)
        n = max(1, min(5, n))

        target = float(target_duration_sec or dsl.target_duration_sec or 0.0)
        if target <= 0:
            target = 60.0
        per_slot = target / float(max(1, len(roles_sequence)))

        timelines: List[FinalTimeline] = []
        base_seed = _stable_seed(dsl.goal or "auto_edit", seed_hint or "", str(len(pool.events)))

        for i in range(n):
            rng = random.Random(base_seed + i * 9973)
            # 第 i 个方案用递增的 diversity，让后续方案更容易选出不同事件，避免去重后数量不足
            cur_diversity = 1.0 + i * 8.0
            used_event_ids: Set[str] = set()
            clip_counts: dict[str, int] = {}
            max_events_per_clip = int(getattr(dsl.constraints, "max_events_per_clip", 6) or 6)
            avoid_adjacent = bool(getattr(dsl.constraints, "avoid_adjacent_same_clip", True))
            recent_clips: List[str] = []
            shot_bounds = _shot_bounds(dsl)
            items: List[TimelineItem] = []

            for role in roles_sequence:
                role_events = [
                    e
                    for e in pool.events
                    if getattr(e, "role", None) == role and (e.text or "").strip()
                ]
                shuffled_role = _weighted_shuffle(role_events, rng, diversity=cur_diversity)

                pick = None
                for e in shuffled_role:
                    eid = getattr(e, "event_id", None)
                    if not isinstance(eid, str) or not eid or eid in used_event_ids:
                        continue
                    clip_id = str(getattr(e, "clip_id", "") or "")
                    if _exceed_clip_quota(
                        clip_id=clip_id,
                        clip_counts=clip_counts,
                        max_events_per_clip=max_events_per_clip,
                    ):
                        continue
                    if _recently_used(clip_id, recent_clips, enabled=avoid_adjacent):
                        continue
                    text = (e.text or "").strip()
                    if not text:
                        continue
                    pick = e
                    break

                # slot 缺失兜底：取任意未使用高分事件（不检查邻接，保底出片）
                if pick is None:
                    shuffled_any = _weighted_shuffle(pool.events, rng, diversity=cur_diversity)
                    for e in shuffled_any:
                        eid = getattr(e, "event_id", None)
                        if not isinstance(eid, str) or not eid or eid in used_event_ids:
                            continue
                        clip_id = str(getattr(e, "clip_id", "") or "")
                        if _exceed_clip_quota(
                            clip_id=clip_id,
                            clip_counts=clip_counts,
                            max_events_per_clip=max_events_per_clip,
                        ):
                            continue
                        text = (e.text or "").strip()
                        if not text:
                            continue
                        pick = e
                        break

                if pick is None:
                    continue

                used_event_ids.add(pick.event_id)
                pick_clip_id = str(pick.clip_id)
                _touch_clip_quota(clip_id=pick_clip_id, clip_counts=clip_counts)
                recent_clips.append(pick_clip_id)
                text = (pick.text or "").strip()
                dur_est = _estimate_item_duration(text, pace=dsl.style.pace)
                bounds = _hook_shot_bounds(shot_bounds) if getattr(pick, "role", None) == "hook" else shot_bounds
                dur = _clamp_shot_duration(max(0.5, min(per_slot, dur_est)), bounds)

                items.append(
                    TimelineItem(
                        event_id=pick.event_id,
                        clip_id=pick.clip_id,
                        subtitle_text=text,
                        audio_mode="tts" if mode in ("auto", "voiceover") else "original",
                        duration_budget_sec=dur,
                    )
                )

            items = _fill_timeline_by_reuse(items=items, target_duration=target, mode=mode)
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

        # 去重后数量不足目标：用更大 diversity 追加编排，尽量凑够 num_plans 个差异方案。
        # 仅当事件池足够丰富（每个 slot 有≥2 候选）时才可能造出差异；否则保留已有方案。
        retry = 0
        while len(uniq) < n and retry < n * 3:
            retry += 1
            rng = random.Random(base_seed + 99999 + retry * 7919)
            big_div = 15.0 + retry * 10.0
            used_event_ids: Set[str] = set()
            clip_counts: dict[str, int] = {}
            max_events_per_clip = int(getattr(dsl.constraints, "max_events_per_clip", 6) or 6)
            avoid_adjacent = bool(getattr(dsl.constraints, "avoid_adjacent_same_clip", True))
            recent_clips: List[str] = []
            shot_bounds = _shot_bounds(dsl)
            items: List[TimelineItem] = []
            for role in roles_sequence:
                role_events = [
                    e
                    for e in pool.events
                    if getattr(e, "role", None) == role and (e.text or "").strip()
                ]
                shuffled_role = _weighted_shuffle(role_events, rng, diversity=big_div)
                pick = None
                for e in shuffled_role:
                    eid = getattr(e, "event_id", None)
                    if not isinstance(eid, str) or not eid or eid in used_event_ids:
                        continue
                    clip_id = str(getattr(e, "clip_id", "") or "")
                    if _exceed_clip_quota(
                        clip_id=clip_id,
                        clip_counts=clip_counts,
                        max_events_per_clip=max_events_per_clip,
                    ):
                        continue
                    if _recently_used(clip_id, recent_clips, enabled=avoid_adjacent):
                        continue
                    text = (e.text or "").strip()
                    if not text:
                        continue
                    pick = e
                    break
                if pick is None:
                    shuffled_any = _weighted_shuffle(pool.events, rng, diversity=big_div)
                    for e in shuffled_any:
                        eid = getattr(e, "event_id", None)
                        if not isinstance(eid, str) or not eid or eid in used_event_ids:
                            continue
                        clip_id = str(getattr(e, "clip_id", "") or "")
                        if _exceed_clip_quota(
                            clip_id=clip_id,
                            clip_counts=clip_counts,
                            max_events_per_clip=max_events_per_clip,
                        ):
                            continue
                        text = (e.text or "").strip()
                        if not text:
                            continue
                        pick = e
                        break
                if pick is None:
                    continue
                used_event_ids.add(pick.event_id)
                pick_clip_id = str(pick.clip_id)
                _touch_clip_quota(clip_id=pick_clip_id, clip_counts=clip_counts)
                recent_clips.append(pick_clip_id)
                text = (pick.text or "").strip()
                dur_est = _estimate_item_duration(text, pace=dsl.style.pace)
                bounds = _hook_shot_bounds(shot_bounds) if getattr(pick, "role", None) == "hook" else shot_bounds
                dur = _clamp_shot_duration(max(0.5, min(per_slot, dur_est)), bounds)
                items.append(
                    TimelineItem(
                        event_id=pick.event_id,
                        clip_id=pick.clip_id,
                        subtitle_text=text,
                        audio_mode="tts" if mode in ("auto", "voiceover") else "original",
                        duration_budget_sec=dur,
                    )
                )
            if not items:
                continue
            items = _fill_timeline_by_reuse(items=items, target_duration=target, mode=mode)
            sig = tuple(f"{it.clip_id}:{(it.subtitle_text or '').strip()}" for it in items)
            if sig and sig not in seen:
                seen.add(sig)
                total = sum((it.duration_budget_sec or 0.0) for it in items)
                uniq.append(FinalTimeline(items=items, total_duration_sec_est=total if total > 0 else None))

        return uniq if uniq else timelines[:1]

    # 非模板：保持旧 tier 预算 + 加权洗牌差异化逻辑
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

    shot_bounds = _shot_bounds(dsl)
    adjacency_on = [bool(getattr(dsl.constraints, "avoid_adjacent_same_clip", True))]

    def _pick(events, budget: float, *, rng: random.Random, used_event_ids: Set[str], recent_clips: List[str]) -> List[TimelineItem]:
        items: List[TimelineItem] = []
        used = 0.0
        max_events_per_clip = int(getattr(dsl.constraints, "max_events_per_clip", 6) or 6)
        for e in events:
            if used >= budget:
                break
            eid = getattr(e, "event_id", None)
            if isinstance(eid, str) and eid in used_event_ids:
                continue
            text = (getattr(e, "text", "") or "").strip()
            if not text:
                continue
            bounds = (
                _hook_shot_bounds(shot_bounds) if getattr(e, "role", None) == "hook" else shot_bounds
            )
            dur = _clamp_shot_duration(
                _estimate_item_duration(text, pace=dsl.style.pace), bounds
            )
            if used + dur > budget and used > 0:
                break
            clip_id = getattr(e, "clip_id", "")
            if _exceed_clip_quota(
                clip_id=str(clip_id),
                clip_counts=clip_counts,
                max_events_per_clip=max_events_per_clip,
            ):
                continue
            if _recently_used(str(clip_id), recent_clips, enabled=adjacency_on[0]):
                continue
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
            _touch_clip_quota(clip_id=str(clip_id), clip_counts=clip_counts)
            recent_clips.append(str(clip_id))
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
        clip_counts: dict[str, int] = {}
        recent_clips: List[str] = []

        s1 = _weighted_shuffle(t1, rng)
        s2 = _weighted_shuffle(t2, rng)
        s3 = _weighted_shuffle(t3, rng)

        items: List[TimelineItem] = []
        items.extend(_pick(s1, b1, rng=rng, used_event_ids=used_event_ids, recent_clips=recent_clips))
        items.extend(_pick(s2, b2, rng=rng, used_event_ids=used_event_ids, recent_clips=recent_clips))
        items.extend(_pick(s3, b3, rng=rng, used_event_ids=used_event_ids, recent_clips=recent_clips))

        # 素材池被邻接约束耗尽：放宽后重试保底
        if not items and adjacency_on[0]:
            adjacency_on[0] = False
            clip_counts = {}
            items.extend(_pick(s1, b1, rng=rng, used_event_ids=used_event_ids, recent_clips=recent_clips))
            items.extend(_pick(s2, b2, rng=rng, used_event_ids=used_event_ids, recent_clips=recent_clips))
            items.extend(_pick(s3, b3, rng=rng, used_event_ids=used_event_ids, recent_clips=recent_clips))
            adjacency_on[0] = True

        # 钩子前置：完播实践——前 3 秒必须是最抓人的画面
        items = _promote_hook_first(items, pool)

        items = _fill_timeline_by_reuse(items=items, target_duration=target, mode=mode)
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

