"""素材处理流水线入口：split -> (frames||asr) -> vlm -> embed。"""
from __future__ import annotations

import asyncio

from fastapi import HTTPException

from .process_db import get_clips, get_video, set_video_status
from .process_pipeline_context import PipelineContext
from .process_pipeline_services import init_pipeline_services
from .process_pipeline_split import run_split_phase
from .process_pipeline_workers import (
    cancel_all_workers,
    drain_workers,
    enqueue_item,
    make_pipeline_item,
    start_workers,
)
from .process_shared import (
    ProcessCancelled,
    STEP_LABELS,
    cancel_event_for,
    check_cancel,
    get_splitter,
    logger,
)


async def run_pipeline(
    video_id: str,
    reporter,
    skip_steps: list = None,
    task_id: str | None = None,
    clip_ids_filter: frozenset[str] | None = None,
):
    """执行全素材处理（按片段流水线并发）。"""
    skip_steps = skip_steps or []
    skip_cn = "、".join(STEP_LABELS.get(s, s) for s in skip_steps) if skip_steps else "无"
    stage_log(
        "预处理",
        f"开始处理视频 {video_id}（跳过: {skip_cn}）",
        status="running",
    )

    video = await get_video(video_id)
    if not video:
        logger.error("run_pipeline: video_id=%s 视频不存在", video_id)
        raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")

    splitter = get_splitter(video_id)
    cancel_event_for(video_id).clear()
    await set_video_status(video_id, "processing")

    loop = asyncio.get_event_loop()
    ctx = PipelineContext(
        video_id=video_id,
        reporter=reporter,
        skip_steps=skip_steps,
        task_id=task_id,
        clip_ids_filter=clip_ids_filter,
        video=video,
        splitter=splitter,
        loop=loop,
        cancel_event=cancel_event_for(video_id),
    )
    await ctx.load_config()
    await check_cancel(video_id)

    ctx.do_split = "split" not in skip_steps
    if ctx.do_split:
        ctx.ensure_step_start("split")
        await reporter.send("split", "running", f"开始切分视频（流式模式：{ctx.split_mode})")
    else:
        await reporter.send("split", "skip", "跳过视频切分")

    clips_rows = await get_clips(video_id) if not ctx.do_split else []
    if not ctx.do_split and clip_ids_filter:
        clips_rows = [r for r in clips_rows if r["id"] in clip_ids_filter]
    ctx.total_clips = len(clips_rows)

    ctx.do_frames = "extract_frames" not in skip_steps
    ctx.do_asr = "asr" not in skip_steps
    ctx.do_vlm = "vlm" not in skip_steps
    ctx.do_embed = "embed" not in skip_steps

    if ctx.do_frames:
        msg = (
            f"开始流式抽帧（{ctx.frame_fps} 帧/秒）"
            if ctx.do_split
            else f"开始为 {ctx.total_clips} 个片段抽帧（{ctx.frame_fps} 帧/秒）"
        )
        await reporter.send("extract_frames", "running", msg)
    else:
        await reporter.send("extract_frames", "skip", "跳过图帧提取")

    await init_pipeline_services(ctx)
    ctx.init_queues()
    start_workers(ctx)

    cancelled_early = False
    if ctx.do_split:
        split_result = await run_split_phase(ctx)
        if split_result == "empty":
            return
        if split_result == "cancelled":
            cancelled_early = True
    else:
        if not clips_rows:
            await cancel_all_workers(ctx)
            await reporter.send("extract_frames", "error", "没有可处理的片段")
            await set_video_status(video_id, "error")
            return
        for clip in clips_rows:
            await enqueue_item(
                ctx,
                make_pipeline_item(
                    ctx,
                    clip["id"],
                    clip["clip_path"],
                    clip["asr_text"] or "",
                    clip["vlm_description"] or "",
                ),
            )

    if cancelled_early:
        await cancel_all_workers(ctx)
        raise ProcessCancelled()

    await drain_workers(ctx)

    fc = max(1, ctx.frame_concurrency)
    ac = max(1, ctx.asr_concurrency)
    vc = max(1, ctx.vlm_concurrency)
    ec = max(1, ctx.embedding_concurrency)

    if ctx.do_frames:
        ctx.ensure_step_end("extract_frames")
        await reporter.send(
            "extract_frames",
            "done",
            f"抽帧完成，成功 {ctx.frame_success}/{ctx.total_clips} 个（并发={fc}）",
            {
                "processed": ctx.frame_success,
                "total": ctx.total_clips,
                "errors": ctx.total_clips - ctx.frame_success,
                "concurrency": fc,
                "metrics": ctx.metrics_snapshot(),
            },
        )
    if ctx.do_asr:
        ctx.ensure_step_end("asr")
        await reporter.send(
            "asr",
            "done",
            f"语音识别完成，成功 {ctx.asr_success}/{ctx.total_clips} 个（并发={ac}）",
            {
                "processed": ctx.asr_success,
                "total": ctx.total_clips,
                "concurrency": ac,
                "metrics": ctx.metrics_snapshot(),
            },
        )
    if ctx.do_vlm:
        ctx.ensure_step_end("vlm")
        await reporter.send(
            "vlm",
            "done",
            f"视觉描述完成，成功 {ctx.vlm_success}/{ctx.total_clips} 个（并发={vc}）",
            {
                "processed": ctx.vlm_success,
                "total": ctx.total_clips,
                "concurrency": vc,
                "metrics": ctx.metrics_snapshot(),
            },
        )
    if ctx.do_embed:
        ctx.ensure_step_end("embed")
        await reporter.send(
            "embed",
            "done",
            f"向量入库完成，成功 {ctx.emb_success}/{ctx.total_clips} 个（并发={ec}，model={ctx.embedding_model}）",
            {
                "processed": ctx.emb_success,
                "total": ctx.total_clips,
                "concurrency": ec,
                "model": ctx.embedding_model,
                "metrics": ctx.metrics_snapshot(),
            },
        )

    await set_video_status(video_id, "done")
    await reporter.send("done", "done", "全部处理完成！", {"metrics": ctx.metrics_snapshot()})
