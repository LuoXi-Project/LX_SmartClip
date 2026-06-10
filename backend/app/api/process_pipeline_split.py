"""素材处理流水线：视频切分阶段。"""
from __future__ import annotations

import asyncio

from app.core.splitter import StopRequested

from .process_db import clear_clips_for_video, insert_clip_to_db, set_video_status
from .process_pipeline_context import PipelineContext
from .process_pipeline_helpers import PIPELINE_SPLIT_TIMEOUT_SEC
from .process_pipeline_workers import cancel_all_workers, enqueue_item, make_pipeline_item
from .process_shared import ProcessCancelled, check_cancel


def split_progress_message(ctx: PipelineContext, d: dict) -> str:
    phase = str(d.get("phase") or "")
    shots = int(d.get("shots_detected") or 0)
    planned = int(d.get("segments_planned") or 0)
    ready = int(d.get("clips_ready") or 0)
    mode = str(d.get("split_mode") or ctx.split_mode)
    if phase == "detecting":
        if mode == "hybrid" and planned > 0 and ready > 0:
            return (
                f"镜头识别中（已发现 {shots} 个镜头），"
                f"已导出 {ready}/{planned} 段（含超长镜头二次切分）…"
            )
        return f"镜头识别中，已发现 {shots} 个镜头…"
    if phase == "planning":
        return (
            f"混合模式：已规划 {planned} 段（{shots} 个镜头），"
            f"超长镜头二次切分中，已导出 {ready} 段…"
        )
    if phase == "cutting" and planned > 0:
        return f"正在导出片段 {ready}/{planned}（{shots} 个镜头），切分尚未结束…"
    if ready > 0:
        return f"已导出 {ready} 个片段，切分进行中…"
    return f"切分进行中（模式: {mode}）…"


async def run_split_phase(ctx: PipelineContext) -> bool:
    """执行切分；返回 True 表示用户取消。"""
    loop = ctx.loop
    reporter = ctx.reporter
    splitter = ctx.splitter
    video_path = ctx.video_path

    await clear_clips_for_video(ctx.video_id)
    split_out_queue: asyncio.Queue = asyncio.Queue()
    split_done = object()
    split_error: dict = {"err": None}
    split_count = 0
    last_split_detail: dict = {
        "phase": "detecting",
        "split_mode": ctx.split_mode,
        "shots_detected": 0,
        "segments_planned": 0,
        "clips_ready": 0,
    }

    def _on_clip_created(clip):
        asyncio.run_coroutine_threadsafe(split_out_queue.put(("clip", clip)), loop).result()

    def _on_split_progress(data: dict):
        asyncio.run_coroutine_threadsafe(split_out_queue.put(("progress", data)), loop).result()

    async def _run_split_task():
        try:
            if ctx.split_mode == "fixed":
                await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: splitter.split_by_fixed(
                            video_path,
                            ctx.fixed_duration,
                            transcode_opts=ctx.transcode_opts,
                            on_clip_created=_on_clip_created,
                            on_progress=_on_split_progress,
                            should_stop=ctx.cancel_event.is_set,
                        ),
                    ),
                    timeout=ctx.remaining_timeout(PIPELINE_SPLIT_TIMEOUT_SEC),
                )
            elif ctx.split_mode == "hybrid":
                await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: splitter.split_by_hybrid(
                            video_path,
                            ctx.scene_threshold,
                            ctx.scene_min_scene_len,
                            ctx.hybrid_max_segment_sec,
                            ctx.fixed_duration,
                            transcode_opts=ctx.transcode_opts,
                            on_clip_created=_on_clip_created,
                            on_progress=_on_split_progress,
                            should_stop=ctx.cancel_event.is_set,
                        ),
                    ),
                    timeout=ctx.remaining_timeout(PIPELINE_SPLIT_TIMEOUT_SEC),
                )
            else:
                await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: splitter.split_by_scene(
                            video_path,
                            ctx.scene_threshold,
                            ctx.scene_min_scene_len,
                            transcode_opts=ctx.transcode_opts,
                            on_clip_created=_on_clip_created,
                            on_progress=_on_split_progress,
                            should_stop=ctx.cancel_event.is_set,
                        ),
                    ),
                    timeout=ctx.remaining_timeout(PIPELINE_SPLIT_TIMEOUT_SEC),
                )
        except (StopRequested, ProcessCancelled):
            split_error["err"] = ProcessCancelled()
        except Exception as e:
            split_error["err"] = e
        finally:
            await split_out_queue.put(("done", split_done))

    split_task = asyncio.create_task(_run_split_task())
    cancelled_early = False
    while True:
        ctx.remaining_timeout()
        try:
            await check_cancel(ctx.video_id)
        except ProcessCancelled:
            cancelled_early = True
            break
        try:
            item = await asyncio.wait_for(
                split_out_queue.get(),
                timeout=min(1.0, ctx.remaining_timeout(1.0)),
            )
        except asyncio.TimeoutError:
            continue
        kind = item[0] if isinstance(item, tuple) else "clip"
        payload = item[1] if isinstance(item, tuple) else item
        if kind == "done":
            break
        if kind == "progress":
            last_split_detail = {**last_split_detail, **(payload or {})}
            detail = {
                **last_split_detail,
                "processed": split_count,
                "metrics": ctx.metrics_snapshot(),
            }
            await reporter.send(
                "split",
                "running",
                split_progress_message(ctx, detail),
                detail,
            )
            continue
        clip_obj = payload
        try:
            await check_cancel(ctx.video_id)
        except ProcessCancelled:
            cancelled_early = True
            break
        clip_id = await insert_clip_to_db(ctx.video_id, clip_obj)
        split_count += 1
        ctx.total_clips = split_count
        last_split_detail["clips_ready"] = split_count
        planned = int(last_split_detail.get("segments_planned") or 0)
        detail = {
            **last_split_detail,
            "processed": split_count,
            "current": split_count,
            "total": max(planned, split_count),
            "metrics": ctx.metrics_snapshot(),
        }
        await reporter.send(
            "split",
            "running",
            split_progress_message(ctx, {**detail, "phase": "cutting", "clips_ready": split_count}),
            detail,
        )
        await enqueue_item(ctx, make_pipeline_item(ctx, clip_id, clip_obj.clip_path))

    await split_task
    if split_error["err"] is not None:
        await cancel_all_workers(ctx)
        raise split_error["err"]
    if split_count <= 0:
        await cancel_all_workers(ctx)
        await reporter.send("extract_frames", "error", "没有可处理的片段")
        await set_video_status(ctx.video_id, "error")
        return "empty"
    ctx.ensure_step_end("split")
    await reporter.send(
        "split",
        "done",
        f"切分完成，共 {split_count} 个片段"
        + (
            f"（{int(last_split_detail.get('shots_detected') or 0)} 个镜头"
            f"→{int(last_split_detail.get('segments_planned') or split_count)} 段）"
            if ctx.split_mode in ("scene", "hybrid")
            and int(last_split_detail.get("shots_detected") or 0) > 0
            else ""
        ),
        {
            "total_clips": split_count,
            "shots_detected": int(last_split_detail.get("shots_detected") or 0),
            "segments_planned": int(last_split_detail.get("segments_planned") or split_count),
            "phase": "done",
            "metrics": ctx.metrics_snapshot(),
        },
    )
    return "cancelled" if cancelled_early else None
