"""auto_edit.py — 自动一键成片 · Plan 规划接口

Phase 1：仅生成结构化 Plan，不负责实际成片渲染。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Dict, List, Set

import aiosqlite
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.blocking_pool import run_heavy
from app.db.database import DB_PATH
from app.core.llm import LLMConfig
from app.core.auto_edit.plan_generation import call_llm_for_plans
from app.core.auto_edit.segments import ClipCandidate, collect_plan_clip_ids, segments_from_plan
from app.core.auto_edit_v2.plan_compile import (
    build_v0_dsl_from_request,
    build_v0_timeline_from_context,
    compile_timeline_to_plan,
)
from app.core.auto_edit_v2.dsl_generation import call_llm_for_strategy_dsl
from app.core.auto_edit_v2.events_generation import call_llm_for_events_all
from app.core.auto_edit_v2.merge_rank import assign_tiers_and_rank, merge_batches
from app.core.auto_edit_v2.arrange import arrange_timeline
from app.core.bgm.auto_bgm import apply_bgm_postprocess_if_needed
from app.api.copy_gen import _build_video_context_with_recall
from app.models.subtitle import (
    SubtitleStyle,
    GenerateSRTRequest,
    BurnSubtitleRequest,
    ExportOriginalRequest,
)
from app.api.subtitle import execute_burn_subtitle, execute_export_original
from app.models.auto_edit import (
    AutoEditPlanRequest,
    AutoEditPlanResponse,
    AutoEditPlanSessionResponse,
    AutoEditRealizeRequest,
    AutoEditRealizeResponse,
)

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/auto-edit", tags=["auto-edit"])

_PLAN_STREAM_SESSIONS: Dict[str, AutoEditPlanRequest] = {}
_PLAN_STREAM_CREATED_AT: Dict[str, float] = {}
_PLAN_STREAM_EXPIRE_SEC = 10 * 60

def _cleanup_expired_plan_sessions() -> None:
    now = time.time()
    expired = [
        sid
        for sid, created_at in _PLAN_STREAM_CREATED_AT.items()
        if now - created_at > _PLAN_STREAM_EXPIRE_SEC
    ]
    for sid in expired:
        _PLAN_STREAM_CREATED_AT.pop(sid, None)
        _PLAN_STREAM_SESSIONS.pop(sid, None)


def _build_sse_event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/plan", response_model=AutoEditPlanResponse)
async def generate_auto_edit_plan(req: AutoEditPlanRequest) -> AutoEditPlanResponse:
    """
    基于已处理完成的视频素材（clips + ASR + VLM），生成自动成片的结构化方案（Plan）。

    当前阶段：
    - 不做转场与 BGM 的真实渲染，仅在 Plan 中占位。
    - 不支持复杂的 keep_flags/prev_plan 逻辑，只做最简单的全量新方案。
    """
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
            logger.info("auto_edit 启用新引擎：正在读取上下文")
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

    # 低侵入升级：启用新引擎时，先走“规则 timeline → 编译回 Plan”（V0 骨架），保持 response_model 不变
    if getattr(req, "use_timeline_engine", False):
        # V1：优先走 DSL(LLM) → Events(LLM 分批) → Merge/Tier → Arrange → Compile
        # 失败则回退 V0（规则 timeline），再失败回退旧逻辑（LLM 直出 Plan）
        try:
            logger.info("auto_edit 启用新引擎：正在生成 DSL")
            dsl = await call_llm_for_strategy_dsl(
                cfg=cfg,
                user_prompt=req.user_prompt,
                mode_hint=req.mode,
                target_duration_sec=req.target_duration_sec,
            )
        except Exception:
            dsl = build_v0_dsl_from_request(req.user_prompt, req.mode, req.target_duration_sec)

        try:
            logger.info("auto_edit 启用新引擎：正在生成事件池")
            batches = await call_llm_for_events_all(cfg=cfg, context=context)
            logger.info("auto_edit 启用新引擎：正在合并事件池")
            merged_events = merge_batches(batches)
            logger.info("auto_edit 启用新引擎：正在分配事件池")
            pool = assign_tiers_and_rank(merged_events)
            logger.info("auto_edit 启用新引擎：正在编排事件池")
            timeline = arrange_timeline(
                pool=pool,
                dsl=dsl,
                mode=req.mode,
                target_duration_sec=req.target_duration_sec,
            )
            if not timeline.items:
                raise RuntimeError("timeline empty")
            logger.info("auto_edit 启用新引擎：正在编译时间轴为 Plan")
            plan = compile_timeline_to_plan(
                timeline=timeline,
                dsl=dsl,
                plan_id=uuid.uuid4().hex[:8],
                title="智能剪辑（Timeline Engine）",
                summary="由事件级时间轴编译生成（V1）",
                mode=req.mode,
                allow_cross_video=req.allow_cross_video,
            )
            return AutoEditPlanResponse(plans=[plan])
        except Exception:
            timeline = build_v0_timeline_from_context(context=context, dsl=dsl, mode=req.mode)
            if timeline.items:
                plan = compile_timeline_to_plan(
                    timeline=timeline,
                    dsl=dsl,
                    plan_id=uuid.uuid4().hex[:8],
                    title="智能剪辑（Timeline Engine）",
                    summary="由事件级时间轴编译生成（V0 回退）",
                    mode=req.mode,
                    allow_cross_video=req.allow_cross_video,
                )
                return AutoEditPlanResponse(plans=[plan])

            # 最终兜底：回退旧逻辑，避免新引擎缺信息直接失败
            return await call_llm_for_plans(cfg, context, req)

    return await call_llm_for_plans(cfg, context, req)


@router.post("/plan/session", response_model=AutoEditPlanSessionResponse)
async def create_auto_edit_plan_session(req: AutoEditPlanRequest) -> AutoEditPlanSessionResponse:
    if not req.video_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个视频")
    _cleanup_expired_plan_sessions()
    session_id = uuid.uuid4().hex
    _PLAN_STREAM_SESSIONS[session_id] = req
    _PLAN_STREAM_CREATED_AT[session_id] = time.time()
    return AutoEditPlanSessionResponse(
        session_id=session_id,
        stream_url=f"/api/auto-edit/plan/stream?session_id={session_id}",
    )


@router.get("/plan/stream")
async def stream_auto_edit_plan(session_id: str) -> StreamingResponse:
    _cleanup_expired_plan_sessions()
    # 注意：SSE(EventSource) 在网络抖动时会自动重连；如果这里立刻 pop 掉 session，
    # 重连会直接 404，前端会误以为“转发/连接不正常”。
    # 因此改为：流结束（或异常结束）后再清理 session。
    req = _PLAN_STREAM_SESSIONS.get(session_id)
    if req is None:
        raise HTTPException(status_code=404, detail="规划会话不存在或已过期")

    async def event_generator():
        try:
            # 发送一个轻量事件帮助部分代理/浏览器尽快 flush headers
            yield ": ok\n\n"
            yield _build_sse_event("progress", {"stage": "init", "message": "开始读取模型配置"})
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
                    yield _build_sse_event("progress", {"stage": "context", "message": "正在构建素材上下文"})
                    context = await _build_video_context_with_recall(
                        db,
                        req.video_ids,
                        user_prompt=req.user_prompt,
                    )
            except ValueError as e:
                yield _build_sse_event("failed", {"message": str(e)})
                return
            except Exception as e:
                logger.error("auto_edit stream 读取上下文失败: %s", e)
                yield _build_sse_event("failed", {"message": "读取素材上下文失败"})
                return

            yield _build_sse_event("progress", {"stage": "llm", "message": "LLM 正在生成候选方案"})
            if getattr(req, "use_timeline_engine", False):
                yield _build_sse_event(
                    "progress",
                    {"stage": "timeline", "message": "新引擎：正在生成 DSL/事件池/时间轴并编译为 Plan"},
                )
                try:
                    dsl = await call_llm_for_strategy_dsl(
                        cfg=cfg,
                        user_prompt=req.user_prompt,
                        mode_hint=req.mode,
                        target_duration_sec=req.target_duration_sec,
                    )
                except Exception:
                    dsl = build_v0_dsl_from_request(req.user_prompt, req.mode, req.target_duration_sec)

                try:
                    batches = await call_llm_for_events_all(cfg=cfg, context=context)
                    merged_events = merge_batches(batches)
                    pool = assign_tiers_and_rank(merged_events)
                    timeline = arrange_timeline(
                        pool=pool,
                        dsl=dsl,
                        mode=req.mode,
                        target_duration_sec=req.target_duration_sec,
                    )
                    if not timeline.items:
                        raise RuntimeError("timeline empty")
                    plan = compile_timeline_to_plan(
                        timeline=timeline,
                        dsl=dsl,
                        plan_id=uuid.uuid4().hex[:8],
                        title="智能剪辑（Timeline Engine）",
                        summary="由事件级时间轴编译生成（V1）",
                        mode=req.mode,
                        allow_cross_video=req.allow_cross_video,
                    )
                    plan_res = AutoEditPlanResponse(plans=[plan])
                except Exception:
                    timeline = build_v0_timeline_from_context(context=context, dsl=dsl, mode=req.mode)
                    if timeline.items:
                        plan = compile_timeline_to_plan(
                            timeline=timeline,
                            dsl=dsl,
                            plan_id=uuid.uuid4().hex[:8],
                            title="智能剪辑（Timeline Engine）",
                            summary="由事件级时间轴编译生成（V0 回退）",
                            mode=req.mode,
                            allow_cross_video=req.allow_cross_video,
                        )
                        plan_res = AutoEditPlanResponse(plans=[plan])
                    else:
                        plan_res = await call_llm_for_plans(cfg, context, req)
            else:
                plan_res = await call_llm_for_plans(cfg, context, req)
            yield _build_sse_event(
                "progress",
                {"stage": "done", "message": f"生成完成，共 {len(plan_res.plans)} 个方案"},
            )
            yield _build_sse_event("result", plan_res.model_dump())
        except HTTPException as e:
            msg = e.detail if isinstance(e.detail, str) else "生成方案失败"
            yield _build_sse_event("failed", {"message": msg})
        except Exception as e:
            logger.error("auto_edit stream 未知异常: %s", e)
            yield _build_sse_event("failed", {"message": "生成方案失败"})
        finally:
            _PLAN_STREAM_SESSIONS.pop(session_id, None)
            _PLAN_STREAM_CREATED_AT.pop(session_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # 让反向代理不要缓冲 SSE（即使你以后上了 Nginx/Caddy 也更稳）
            "X-Accel-Buffering": "no",
        },
    )


 
 
@router.post("/realize", response_model=AutoEditRealizeResponse)
async def realize_auto_edit_plan(
    req: AutoEditRealizeRequest,
    request: Request,
) -> AutoEditRealizeResponse:
    """
    将一个 Plan 实际转为成片：
    - voiceover 模式：TTS + 字幕 + burn 管线
    - original 模式：保留原声，按段落平均切字幕，调用 export_original

    当前版本：
    - 忽略 Plan.keep_flags / BGM / transition，仅打通基础链路。
    """
    if await request.is_disconnected():
        raise HTTPException(status_code=400, detail="客户端已断开连接")
    plan = req.plan
    if not plan.segments:
        raise HTTPException(status_code=400, detail="Plan 中没有任何 segments")

    requested_clip_ids = collect_plan_clip_ids(plan)
    valid_clip_ids: Set[str] = set()
    clip_id_to_video: Dict[str, str] = {}
    candidate_videos: Set[str] = set()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # 1) clip_id 预检：友好返回无效 ID 列表
        if requested_clip_ids:
            placeholders = ",".join(["?"] * len(requested_clip_ids))
            async with db.execute(
                f"SELECT id, video_id FROM clips WHERE id IN ({placeholders})",
                requested_clip_ids,
            ) as cur:
                rows = await cur.fetchall()
            for row in rows:
                cid = str(row["id"])
                valid_clip_ids.add(cid)
                clip_id_to_video[cid] = str(row["video_id"])

        invalid_clip_ids = [cid for cid in requested_clip_ids if cid not in valid_clip_ids]

        # 2) 构造回退候选池（优先 segment.clip_group 的 video_id，其次已命中 clip 的 video_id）
        for seg in plan.segments:
            for ref in seg.clip_group:
                if ref.video_id:
                    candidate_videos.add(ref.video_id)
        for cid in valid_clip_ids:
            vid = clip_id_to_video.get(cid)
            if vid:
                candidate_videos.add(vid)

        candidates: List[ClipCandidate] = []
        candidates_by_video: Dict[str, List[ClipCandidate]] = {}
        if candidate_videos:
            placeholders = ",".join(["?"] * len(candidate_videos))
            async with db.execute(
                f"SELECT id, video_id, start_time, end_time, duration FROM clips "
                f"WHERE video_id IN ({placeholders})",
                list(candidate_videos),
            ) as cur:
                rows = await cur.fetchall()
            for row in rows:
                cand = ClipCandidate(
                    id=str(row["id"]),
                    video_id=str(row["video_id"]),
                    start_time=float(row["start_time"] or 0.0),
                    end_time=float(row["end_time"] or 0.0),
                    duration=float(row["duration"] or 0.0),
                )
                candidates.append(cand)
                candidates_by_video.setdefault(cand.video_id, []).append(cand)

    seg_inputs = await segments_from_plan(
        plan=plan,
        valid_clip_ids=valid_clip_ids,
        candidates_by_video=candidates_by_video,
        all_candidates=candidates,
    )
    if not seg_inputs:
        detail = {
            "message": "Plan 转换后没有有效片段，请检查计划中的 clip_id 是否有效。",
            "invalid_clip_ids": invalid_clip_ids,
        }
        raise HTTPException(status_code=400, detail=detail)

    if invalid_clip_ids:
        logger.warning("realize 检测到无效 clip_id，已尝试自动回退: %s", invalid_clip_ids)

    project_name = req.project_name or f"auto_edit_{plan.plan_id}"

    # 字幕样式：优先使用前端传入，否则回退默认值
    style = req.style or SubtitleStyle()

    # voiceover / auto -> 统一走配音管线（若某段未生成 TTS，会回落到 clip 时长）
    if plan.mode in ("auto", "voiceover"):
        from app.api.subtitle import generate_srt as generate_srt_route

        if req.include_subtitle:
            if await request.is_disconnected():
                raise HTTPException(status_code=400, detail="客户端已断开连接")
            srt_req = GenerateSRTRequest(segments=seg_inputs, style=style, use_tts_timing=True)
            srt_res = await generate_srt_route(srt_req)
            burn_req = BurnSubtitleRequest(
                segments=seg_inputs,
                srt_content=srt_res.srt_content,
                style=style,
                project_name=project_name,
            )
            burn_res = await execute_burn_subtitle(burn_req)
        else:
            if await request.is_disconnected():
                raise HTTPException(status_code=400, detail="客户端已断开连接")
            export_req = ExportOriginalRequest(
                segments=seg_inputs,
                style=style,
                project_name=project_name,
                include_subtitle=False,
                normalize_audio=True,
            )
            export_res = await execute_export_original(export_req)
            burn_res = {
                "filename": export_res.get("filename"),
                "url": export_res.get("url"),
            }
        if await request.is_disconnected():
            raise HTTPException(status_code=400, detail="客户端已断开连接")
        final_filename, final_url = await run_heavy(
            apply_bgm_postprocess_if_needed,
            plan,
            burn_res["filename"],
            burn_res["url"],
        )
        return AutoEditRealizeResponse(mode="voiceover", filename=final_filename, url=final_url)

    export_req = ExportOriginalRequest(
        segments=seg_inputs,
        style=style,
        project_name=project_name,
        include_subtitle=req.include_subtitle,
        normalize_audio=True,
    )
    if await request.is_disconnected():
        raise HTTPException(status_code=400, detail="客户端已断开连接")
    res = await execute_export_original(export_req)
    if await request.is_disconnected():
        raise HTTPException(status_code=400, detail="客户端已断开连接")
    final_filename, final_url = await run_heavy(
        apply_bgm_postprocess_if_needed,
        plan,
        res.get("filename") or "",
        res.get("url") or "",
    )
    return AutoEditRealizeResponse(mode="original", filename=final_filename, url=final_url)

