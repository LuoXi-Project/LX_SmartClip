"""Plan 规划相关路由：模板、同步规划、SSE 流式规划。"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Dict, List

import aiosqlite
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from app.api.copy_gen import _build_video_context_with_recall
from app.core.auto_edit.plan_generation import call_llm_for_plans
from app.core.auto_edit_v2.template_config import list_templates
from app.core.llm import LLMConfig
from app.db.database import DB_PATH
from app.models.auto_edit import (
    AutoEditPlanRequest,
    AutoEditPlanResponse,
    AutoEditPlanSessionResponse,
)

from app.api.auto_edit_shared import (
    _PLAN_STREAM_CREATED_AT,
    _PLAN_STREAM_SESSIONS,
    build_sse_event,
    build_video_meta_for_plan,
    cleanup_expired_plan_sessions,
    http_exception_for_llm_upstream,
    load_timeline_long_video_cfg,
    load_video_names,
    router,
)
from app.api.auto_edit_timeline import generate_plans_with_timeline_engine

logger = logging.getLogger(__name__)


@router.get("/templates")
async def list_auto_edit_templates() -> List[Dict[str, str]]:
    return list_templates()


@router.post("/plan", response_model=AutoEditPlanResponse)
async def generate_auto_edit_plan(req: AutoEditPlanRequest) -> AutoEditPlanResponse:
    if not req.video_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个视频")

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cfg = await LLMConfig.get_llm_params_with_defaults(
                db,
                base_url_key="llm_base_url",
                api_key_key="llm_api_key",
                model_key="llm_model",
                fallback_model_key="vlm_model",
                default_temperature=0.7,
                default_max_tokens=20480,
            )
            load_timeline_long_video_cfg(req, cfg)
            logger.info("auto_edit 启用新引擎：正在读取上下文")
            video_names = await load_video_names(db, req.video_ids)
            video_title, video_description = build_video_meta_for_plan(
                video_names=video_names,
                user_prompt=req.user_prompt,
            )
            context = await _build_video_context_with_recall(
                db,
                req.video_ids,
                user_prompt=req.user_prompt,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("auto_edit 读取上下文失败: %s", e)
        raise HTTPException(status_code=500, detail="读取素材上下文失败")

    if getattr(req, "use_timeline_engine", False):
        return await generate_plans_with_timeline_engine(
            req=req,
            cfg=cfg,
            context=context,
            video_title=video_title,
            video_description=video_description,
        )
    return await call_llm_for_plans(cfg, context, req)


@router.post("/plan/session", response_model=AutoEditPlanSessionResponse)
async def create_auto_edit_plan_session(req: AutoEditPlanRequest) -> AutoEditPlanSessionResponse:
    if not req.video_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个视频")
    cleanup_expired_plan_sessions()
    session_id = uuid.uuid4().hex
    _PLAN_STREAM_SESSIONS[session_id] = req
    _PLAN_STREAM_CREATED_AT[session_id] = time.time()
    return AutoEditPlanSessionResponse(
        session_id=session_id,
        stream_url=f"/api/auto-edit/plan/stream?session_id={session_id}",
    )


@router.get("/plan/stream")
async def stream_auto_edit_plan(session_id: str) -> StreamingResponse:
    cleanup_expired_plan_sessions()
    req = _PLAN_STREAM_SESSIONS.get(session_id)
    if req is None:
        raise HTTPException(status_code=404, detail="规划会话不存在或已过期")

    async def event_generator():
        try:
            yield ": ok\n\n"
            yield build_sse_event("progress", {"stage": "init", "message": "开始读取模型配置"})
            await asyncio.sleep(0)
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    db.row_factory = aiosqlite.Row
                    cfg = await LLMConfig.get_llm_params_with_defaults(
                        db,
                        base_url_key="llm_base_url",
                        api_key_key="llm_api_key",
                        model_key="llm_model",
                        fallback_model_key="vlm_model",
                        default_temperature=0.7,
                        default_max_tokens=20480,
                    )
                    load_timeline_long_video_cfg(req, cfg)
                    yield build_sse_event("progress", {"stage": "context", "message": "正在构建素材上下文"})
                    video_names = await load_video_names(db, req.video_ids)
                    video_title, video_description = build_video_meta_for_plan(
                        video_names=video_names,
                        user_prompt=req.user_prompt,
                    )
                    context = await _build_video_context_with_recall(
                        db,
                        req.video_ids,
                        user_prompt=req.user_prompt,
                    )
            except ValueError as e:
                yield build_sse_event("failed", {"message": str(e)})
                return
            except Exception as e:
                logger.error("auto_edit stream 读取上下文失败: %s", e)
                yield build_sse_event("failed", {"message": "读取素材上下文失败"})
                return

            yield build_sse_event("progress", {"stage": "llm", "message": "LLM 正在生成候选方案"})
            try:
                if getattr(req, "use_timeline_engine", False):
                    yield build_sse_event(
                        "progress",
                        {"stage": "timeline", "message": "新引擎：正在生成 DSL/事件池/时间轴并编译为 Plan"},
                    )
                    plan_res = await generate_plans_with_timeline_engine(
                        req=req,
                        cfg=cfg,
                        context=context,
                        video_title=video_title,
                        video_description=video_description,
                    )
                else:
                    plan_res = await call_llm_for_plans(cfg, context, req)
            except HTTPException as e:
                msg = e.detail if isinstance(e.detail, str) else "生成方案失败"
                yield build_sse_event("failed", {"message": msg})
                return
            except Exception as e:
                he = http_exception_for_llm_upstream(e)
                if he is not None:
                    d = he.detail
                    yield build_sse_event(
                        "failed",
                        {"message": d if isinstance(d, str) else "LLM 调用失败"},
                    )
                    return
                logger.error("auto_edit stream 生成方案失败: %s", e)
                yield build_sse_event("failed", {"message": "生成方案失败"})
                return

            yield build_sse_event(
                "progress",
                {"stage": "done", "message": f"生成完成，共 {len(plan_res.plans)} 个方案"},
            )
            yield build_sse_event("result", plan_res.model_dump())
        except HTTPException as e:
            msg = e.detail if isinstance(e.detail, str) else "生成方案失败"
            yield build_sse_event("failed", {"message": msg})
        except Exception as e:
            logger.error("auto_edit stream 未知异常: %s", e)
            yield build_sse_event("failed", {"message": "生成方案失败"})
        finally:
            _PLAN_STREAM_SESSIONS.pop(session_id, None)
            _PLAN_STREAM_CREATED_AT.pop(session_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
