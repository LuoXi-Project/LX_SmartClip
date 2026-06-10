"""Timeline 引擎：DSL → Events → Arrange → Plan 编译。"""
from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException

from app.core.auto_edit.plan_generation import call_llm_for_plans
from app.core.auto_edit_v2.arrange import arrange_timeline_variants
from app.core.auto_edit_v2.dsl_generation import call_llm_for_strategy_dsl
from app.core.auto_edit_v2.events_generation import call_llm_for_events_all
from app.core.auto_edit_v2.merge_rank import assign_tiers_and_rank, merge_batches
from app.core.auto_edit_v2.plan_compile import (
    build_v0_dsl_from_request,
    build_v0_timelines_from_context,
    compile_timeline_to_plan,
)
from app.core.auto_edit_v2.plan_quality import sort_plans_by_quality
from app.core.auto_edit_v2.template_config import normalize_template_preset
from app.models.auto_edit import AutoEditPlanRequest, AutoEditPlanResponse, Plan
from app.models.auto_edit_timeline import FinalTimeline, StrategyDSL

from app.api.auto_edit_shared import (
    call_llm_for_final_video_meta,
    compose_plan_summary,
    compose_plan_title,
    expand_timeline_with_llm_copy_if_needed,
    http_exception_for_llm_upstream,
)

logger = logging.getLogger(__name__)


async def _compile_timelines_to_plans(
    *,
    timelines: list[FinalTimeline],
    dsl: StrategyDSL,
    cfg: dict,
    req: AutoEditPlanRequest,
    context: str,
    video_title: str | None,
    video_description: str | None,
    pool,
    engine_summary: str,
) -> list[Plan]:
    final_title, final_desc = await call_llm_for_final_video_meta(
        cfg=cfg,
        context=context,
        user_prompt=req.user_prompt,
        mode=req.mode,
        target_duration_sec=req.target_duration_sec,
    )
    plans: list[Plan] = []
    for i, tl in enumerate(timelines[: max(1, req.num_plans)], 1):
        tl = await expand_timeline_with_llm_copy_if_needed(
            cfg=cfg,
            timeline=tl,
            dsl=dsl,
            mode=req.mode,
            target_duration_sec=req.target_duration_sec,
            user_prompt=req.user_prompt,
            context=context,
        )
        plans.append(
            compile_timeline_to_plan(
                timeline=tl,
                dsl=dsl,
                plan_id=uuid.uuid4().hex[:8],
                title=(final_title or compose_plan_title(plan_index=i, video_title=video_title)),
                summary=(final_desc or compose_plan_summary(
                    engine_summary=engine_summary,
                    video_description=video_description,
                )),
                video_title=(final_title or video_title),
                video_description=(final_desc or video_description),
                mode=req.mode,
                allow_cross_video=req.allow_cross_video,
                pool=pool,
            )
        )
    return plans


async def generate_plans_with_timeline_engine(
    *,
    req: AutoEditPlanRequest,
    cfg: dict,
    context: str,
    video_title: str | None,
    video_description: str | None,
) -> AutoEditPlanResponse:
    """V1 timeline 引擎；失败回退 V0，再失败回退 LLM 直出 Plan。"""
    template_preset = normalize_template_preset(getattr(req, "template_preset", None))
    try:
        if template_preset:
            logger.info("auto_edit 启用新引擎：模板预设存在，使用 V0 DSL(结构强制)")
            dsl = build_v0_dsl_from_request(
                req.user_prompt,
                req.mode,
                req.target_duration_sec,
                template_preset=template_preset,
            )
        else:
            logger.info("auto_edit 启用新引擎：正在生成 DSL")
            dsl = await call_llm_for_strategy_dsl(
                cfg=cfg,
                user_prompt=req.user_prompt,
                mode_hint=req.mode,
                target_duration_sec=req.target_duration_sec,
            )
    except Exception:
        dsl = build_v0_dsl_from_request(
            req.user_prompt, req.mode, req.target_duration_sec, template_preset=template_preset
        )

    pool = None
    try:
        logger.info("auto_edit 启用新引擎：正在生成事件池")
        batches = await call_llm_for_events_all(
            cfg=cfg,
            context=context,
            template_preset=template_preset,
        )
        merged_events = merge_batches(batches)
        pool = assign_tiers_and_rank(merged_events)
        timelines = arrange_timeline_variants(
            pool=pool,
            dsl=dsl,
            mode=req.mode,
            target_duration_sec=req.target_duration_sec,
            num_plans=req.num_plans,
            seed_hint=req.user_prompt,
        )
        timelines = [tl for tl in timelines if tl.items]
        if not timelines:
            raise RuntimeError("timeline empty")
        plans = await _compile_timelines_to_plans(
            timelines=timelines,
            dsl=dsl,
            cfg=cfg,
            req=req,
            context=context,
            video_title=video_title,
            video_description=video_description,
            pool=pool,
            engine_summary="由事件级时间轴编译生成（V1）",
        )
        return AutoEditPlanResponse(plans=sort_plans_by_quality(plans))
    except HTTPException:
        raise
    except Exception as e:
        he = http_exception_for_llm_upstream(e)
        if he is not None:
            raise he
        logger.warning("auto_edit 新引擎 V1 失败，回退 V0 规则时间轴: %s", e)
        timelines = build_v0_timelines_from_context(
            context=context,
            dsl=dsl,
            mode=req.mode,
            num_plans=req.num_plans,
        )
        timelines = [tl for tl in timelines if tl.items]
        if timelines:
            plans = await _compile_timelines_to_plans(
                timelines=timelines,
                dsl=dsl,
                cfg=cfg,
                req=req,
                context=context,
                video_title=video_title,
                video_description=video_description,
                pool=None,
                engine_summary="由事件级时间轴编译生成（V0 回退）",
            )
            return AutoEditPlanResponse(plans=sort_plans_by_quality(plans))
        return await call_llm_for_plans(cfg, context, req)
