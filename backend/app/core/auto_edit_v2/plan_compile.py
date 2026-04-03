from __future__ import annotations

import math
from typing import List, Optional

from app.models.auto_edit import (
    BGMPlan,
    ClipRef,
    Constraints,
    Plan,
    PlanKeepFlags,
    SegmentPlan,
    SubtitlePlan,
    TransitionPlan,
)
from app.models.auto_edit_timeline import FinalTimeline, StrategyDSL, TimelineItem
from app.core.auto_edit_v2.template_config import get_template_style_hint, normalize_template_preset


def _clamp_float(v: Optional[float], default: float, min_v: float, max_v: float) -> float:
    if v is None:
        return default
    try:
        fv = float(v)
    except Exception:
        return default
    if math.isnan(fv) or math.isinf(fv):
        return default
    return max(min_v, min(max_v, fv))


def compile_timeline_to_plan(
    *,
    timeline: FinalTimeline,
    dsl: StrategyDSL,
    plan_id: str,
    title: str,
    summary: str,
    video_title: Optional[str] = None,
    video_description: Optional[str] = None,
    mode: str,
    allow_cross_video: bool,
) -> Plan:
    """
    把 FinalTimeline（事件级、有序、有预算）编译为现有 Plan.segments。

    低侵入原则：
    - 生成的 Plan 必须满足现有 Pydantic 校验
    - 不引入新字段（未来需要可解释性时，再通过可选 meta/日志落盘实现）
    """
    segments: List[SegmentPlan] = []

    # 给 SegmentPlan.start/end 生成一个“首尾相接”的时间窗（用于现有 fallback 选段）
    t = 0.0
    for idx, item in enumerate(timeline.items, 1):
        dur = _clamp_float(item.duration_budget_sec, default=3.0, min_v=0.5, max_v=60.0)
        start = t
        end = t + dur
        t = end

        sub = SubtitlePlan(
            strategy="auto",
            text=item.subtitle_text or "",
            source="llm",
            timing_hint=None,
        )

        seg = SegmentPlan(
            id=f"seg_{idx}",
            chapter_id=None,
            order=idx,
            # video_id 在现有 Plan schema 中是必填；V0 编译器不依赖 video_id，
            # 这里用占位符保证校验通过。落地阶段的候选池构造主要依赖 selected_clip_ids 的有效性。
            clip_group=[ClipRef(clip_id=item.clip_id, video_id="unknown", weight=1.0)],
            selected_clip_ids=[item.clip_id],
            start_time_sec=float(start),
            end_time_sec=float(end),
            audio_mode=item.audio_mode,
            subtitle=sub,
            transition=TransitionPlan(type="hard_cut", duration_sec=0.3),
        )
        segments.append(seg)

    constraints = Constraints(
        max_clip_per_segment=3,
        match_strategy="asr+vlm",
        respect_user_video_order=not allow_cross_video,
    )

    keep_flags = PlanKeepFlags(clips=False, subtitles=False, transitions=False, bgm=False)

    # BGM：V0 不做复杂决策，保持关闭；后续可根据 DSL 或请求策略开启
    bgm = BGMPlan(enabled=False, source="library")

    target = dsl.target_duration_sec
    est = float(t) if segments else 0.0

    return Plan(
        plan_id=plan_id,
        title=title,
        summary=summary,
        video_title=video_title,
        video_description=video_description,
        mode=mode,  # type: ignore[arg-type]
        target_duration_sec=target,
        estimated_duration_sec=est,
        chapters=[],
        segments=segments,
        bgm=bgm,
        constraints=constraints,
        keep_flags=keep_flags,
    )


def build_v0_dsl_from_request(
    user_prompt: str,
    mode: str,
    target_duration_sec: Optional[int],
    template_preset: Optional[str] = None,
) -> StrategyDSL:
    """
    V0：不调用 LLM 生成 DSL，直接用请求生成一个可用的 StrategyDSL。
    目的：先跑通“新引擎的骨架 + 编译回 Plan”。
    """
    preset = normalize_template_preset(template_preset)
    if preset:
        style_hint = get_template_style_hint(preset)
        return StrategyDSL(
            goal=user_prompt.strip() if user_prompt else "auto_edit",
            mode_hint=mode,  # type: ignore[arg-type]
            target_duration_sec=target_duration_sec,
            style=style_hint,  # type: ignore[arg-type]
            template_preset=preset,
        )

    return StrategyDSL(
        goal=user_prompt.strip() if user_prompt else "auto_edit",
        mode_hint=mode,  # type: ignore[arg-type]
        target_duration_sec=target_duration_sec,
    )


def build_v0_timeline_from_context(
    *,
    context: str,
    dsl: StrategyDSL,
    mode: str,
) -> FinalTimeline:
    """
    V0：规则生成 timeline（不做分批 LLM）。

    策略：
    - 从 context 中尽力提取 clip_id 列表（只做“有序选取”）
    - 每个 clip 生成一个 timeline item，文本先用 DSL.goal 兜底
    - 时长预算按 target_duration_sec 平均分配
    """
    import re

    clip_ids = re.findall(r"\[clip_id=([^\]]+)\]", context or "")
    clip_ids = list(dict.fromkeys([c.strip() for c in clip_ids if c and c.strip()]))
    if not clip_ids:
        # 兜底：没有 clip_id 时返回空 timeline（上游应当回退旧逻辑或报错）
        return FinalTimeline(items=[], total_duration_sec_est=0.0)

    target = float(dsl.target_duration_sec or 0) if dsl.target_duration_sec else None
    n = len(clip_ids)
    per = None
    if target and target > 0 and n > 0:
        per = max(1.5, min(10.0, target / n))

    items: List[TimelineItem] = []
    for i, cid in enumerate(clip_ids, 1):
        items.append(
            TimelineItem(
                event_id=f"e_{i}",
                clip_id=cid,
                subtitle_text=dsl.goal if dsl.goal else "",
                audio_mode="tts" if mode in ("auto", "voiceover") else "original",
                duration_budget_sec=per,
            )
        )

    total_est = float(sum((it.duration_budget_sec or 0.0) for it in items))
    return FinalTimeline(items=items, total_duration_sec_est=total_est if total_est > 0 else None)


def build_v0_timelines_from_context(
    *,
    context: str,
    dsl: StrategyDSL,
    mode: str,
    num_plans: int,
) -> List[FinalTimeline]:
    """
    V0：生成多个候选 timeline 的低成本方式（用于“新引擎失败后的回退”）：
    - 从 context 抽取 clip_id 列表
    - 通过“旋转起点 + 步进采样”生成 n 条不同的顺序
    """
    import re

    n = int(num_plans or 1)
    n = max(1, min(5, n))

    clip_ids = re.findall(r"\[clip_id=([^\]]+)\]", context or "")
    clip_ids = list(dict.fromkeys([c.strip() for c in clip_ids if c and c.strip()]))
    if not clip_ids:
        return [FinalTimeline(items=[], total_duration_sec_est=0.0)]

    target = float(dsl.target_duration_sec or 0) if dsl.target_duration_sec else 0.0
    per = None
    if target and target > 0:
        per = max(1.5, min(10.0, target / max(1, len(clip_ids))))

    timelines: List[FinalTimeline] = []
    m = len(clip_ids)
    for i in range(n):
        start = i % m
        step = 1 + (i % 3)  # 1,2,3 循环，制造差异但不至于太跳
        ordered = []
        idx = start
        seen = set()
        for _ in range(m):
            cid = clip_ids[idx]
            if cid not in seen:
                ordered.append(cid)
                seen.add(cid)
            idx = (idx + step) % m

        items: List[TimelineItem] = []
        for j, cid in enumerate(ordered, 1):
            items.append(
                TimelineItem(
                    event_id=f"e_{i+1}_{j}",
                    clip_id=cid,
                    subtitle_text=dsl.goal if dsl.goal else "",
                    audio_mode="tts" if mode in ("auto", "voiceover") else "original",
                    duration_budget_sec=per,
                )
            )
        total_est = float(sum((it.duration_budget_sec or 0.0) for it in items))
        timelines.append(FinalTimeline(items=items, total_duration_sec_est=total_est if total_est > 0 else None))

    return timelines

