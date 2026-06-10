"""素材处理流水线：抽帧 / ASR / VLM / Embedding worker。"""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from app.core.killable_subprocess import run_killable_target
from app.core.metrics.token_usage import TokenUsage

from .process_db import update_clip_asr, update_clip_field
from .process_pipeline_context import PipelineContext
from .process_pipeline_helpers import (
    PIPELINE_STEP_TIMEOUT_SEC,
    _PIPELINE_ISOLATED,
    step_with_timeout_retries,
    transcript_from_payload,
)
from .process_shared import ProcessCancelled, check_cancel, logger


def make_pipeline_item(ctx: PipelineContext, clip_id: str, clip_path: str, asr_text: str = "", vlm_description: str = "") -> dict:
    item = {
        "id": clip_id,
        "clip_path": clip_path,
        "asr_text": (asr_text or "").strip(),
        "vlm_description": (vlm_description or "").strip(),
        "frame_paths": None,
        "frame_ready": asyncio.Event(),
        "asr_ready": asyncio.Event(),
        "vlm_enqueued": False,
    }
    if not ctx.do_asr:
        item["asr_ready"].set()
    return item


async def inc_progress(ctx: PipelineContext, step: str, message_prefix: str, total: int, success: int, done: int) -> None:
    ctx.ensure_step_start(step)
    if total > 0 and done >= total:
        ctx.ensure_step_end(step)
    await ctx.reporter.send(
        step,
        "running",
        f"{message_prefix} {done}/{total} 已处理（成功 {success}）",
        {"current": done, "total": total, "processed": success, "metrics": ctx.metrics_snapshot()},
    )


async def load_frame_paths(ctx: PipelineContext, clip_path: str) -> list[str]:
    clip_name = os.path.splitext(os.path.basename(clip_path))[0]
    frames_dir = os.path.join(ctx.splitter.frames_dir, clip_name)
    if os.path.isdir(frames_dir):
        return sorted(
            os.path.join(frames_dir, f)
            for f in os.listdir(frames_dir)
            if f.lower().endswith((".jpg", ".png"))
        )
    return []


async def maybe_enqueue_vlm(ctx: PipelineContext, item: dict) -> None:
    if not item["frame_ready"].is_set() or not item["asr_ready"].is_set():
        return
    assert ctx.vlm_enqueue_lock is not None and ctx.vlm_queue is not None
    async with ctx.vlm_enqueue_lock:
        if item["vlm_enqueued"]:
            return
        item["vlm_enqueued"] = True
        await ctx.put_with_timeout(ctx.vlm_queue, item, f"vlm:{item['id']}")


async def frames_worker(ctx: PipelineContext) -> None:
    assert ctx.frame_queue is not None and ctx.progress_lock is not None
    while True:
        item = await ctx.frame_queue.get()
        if item is None:
            ctx.frame_queue.task_done()
            break
        ok = False
        try:
            await check_cancel(ctx.video_id)

            async def _run_frames():
                await check_cancel(ctx.video_id)
                fp = item["frame_paths"]
                if not fp:
                    if ctx.do_frames:
                        fp = await run_killable_target(
                            _PIPELINE_ISOLATED,
                            "isolated_extract_frames",
                            (ctx.video_id, item["clip_path"], ctx.frame_fps, ctx.frame_target_pixels),
                            timeout_sec=PIPELINE_STEP_TIMEOUT_SEC,
                        )
                    elif ctx.do_vlm:
                        fp = await load_frame_paths(ctx, item["clip_path"])
                        if not fp:
                            fp = await run_killable_target(
                                _PIPELINE_ISOLATED,
                                "isolated_extract_frames",
                                (ctx.video_id, item["clip_path"], ctx.frame_fps, ctx.frame_target_pixels),
                                timeout_sec=PIPELINE_STEP_TIMEOUT_SEC,
                            )
                return fp or []

            frame_paths = await step_with_timeout_retries(item["id"], "抽帧", _run_frames)
            if frame_paths is not None:
                item["frame_paths"] = frame_paths
                ok = bool(frame_paths)
            else:
                item["frame_paths"] = []
        except ProcessCancelled:
            raise
        except Exception as e:
            logger.warning("片段 %s 抽帧失败: %s", item["id"], e)
        finally:
            item["frame_ready"].set()
            if ctx.do_frames:
                async with ctx.progress_lock:
                    ctx.frame_done += 1
                    if ok:
                        ctx.frame_success += 1
                    await inc_progress(
                        ctx, "extract_frames", "抽帧", ctx.total_clips, ctx.frame_success, ctx.frame_done
                    )
            await maybe_enqueue_vlm(ctx, item)
            ctx.frame_queue.task_done()


async def asr_worker(ctx: PipelineContext) -> None:
    assert ctx.asr_queue is not None and ctx.progress_lock is not None
    loop = ctx.loop
    while True:
        item = await ctx.asr_queue.get()
        if item is None:
            ctx.asr_queue.task_done()
            break
        ok = False
        try:
            await check_cancel(ctx.video_id)

            async def _run_asr():
                await check_cancel(ctx.video_id)
                if ctx.asr_provider == "openai":
                    payload = await run_killable_target(
                        _PIPELINE_ISOLATED,
                        "isolated_openai_asr_clip",
                        (
                            ctx.video_id,
                            item["clip_path"],
                            True,
                            ctx.asr_base_url,
                            ctx.asr_api_key,
                            ctx.asr_openai_model,
                            ctx.asr_language,
                        ),
                        timeout_sec=PIPELINE_STEP_TIMEOUT_SEC,
                    )
                    return transcript_from_payload(payload)
                if ctx.asr_provider == "bailian":
                    payload = await run_killable_target(
                        _PIPELINE_ISOLATED,
                        "isolated_bailian_asr_clip",
                        (
                            ctx.video_id,
                            item["clip_path"],
                            True,
                            ctx.asr_base_url,
                            ctx.asr_api_key,
                            ctx.asr_openai_model,
                            ctx.asr_language,
                        ),
                        timeout_sec=PIPELINE_STEP_TIMEOUT_SEC,
                    )
                    return transcript_from_payload(payload)
                if ctx.whisper_inprocess_transcribe:
                    audio_path = await run_killable_target(
                        _PIPELINE_ISOLATED,
                        "isolated_extract_audio",
                        (ctx.video_id, item["clip_path"], True),
                        timeout_sec=PIPELINE_STEP_TIMEOUT_SEC,
                    )
                    return await asyncio.wait_for(
                        loop.run_in_executor(None, ctx.asr_instance.transcribe_detailed, audio_path),
                        timeout=PIPELINE_STEP_TIMEOUT_SEC,
                    )
                payload = await run_killable_target(
                    _PIPELINE_ISOLATED,
                    "isolated_whisper_asr_clip",
                    (ctx.video_id, item["clip_path"], True, ctx.asr_model, ctx.asr_language or None),
                    timeout_sec=PIPELINE_STEP_TIMEOUT_SEC,
                )
                return transcript_from_payload(payload)

            tr = await step_with_timeout_retries(item["id"], "ASR", _run_asr)
            if tr is not None:
                seg_json = json.dumps(tr.segments_as_dicts(), ensure_ascii=False) if tr.segments else None
                await update_clip_asr(item["id"], tr.text, seg_json)
                item["asr_text"] = (tr.text or "").strip()
                ok = True
        except ProcessCancelled:
            raise
        except Exception as e:
            logger.warning("片段 %s ASR 失败: %s", item["id"], e)
        finally:
            item["asr_ready"].set()
            await maybe_enqueue_vlm(ctx, item)
            async with ctx.progress_lock:
                ctx.asr_done += 1
                if ok:
                    ctx.asr_success += 1
                await inc_progress(ctx, "asr", "ASR", ctx.total_clips, ctx.asr_success, ctx.asr_done)
            ctx.asr_queue.task_done()


async def vlm_worker(ctx: PipelineContext) -> None:
    assert ctx.vlm_queue is not None and ctx.embed_queue is not None and ctx.progress_lock is not None
    while True:
        item = await ctx.vlm_queue.get()
        if item is None:
            ctx.vlm_queue.task_done()
            break
        ok = False
        try:
            await check_cancel(ctx.video_id)
            if ctx.do_vlm and ctx.vlm_instance is not None:
                frame_paths = item["frame_paths"] or []
                if frame_paths:
                    frame_times_sec = ctx.splitter.frame_timestamps_in_clip(item["clip_path"], len(frame_paths))

                    async def _run_vlm():
                        await check_cancel(ctx.video_id)
                        return await run_killable_target(
                            _PIPELINE_ISOLATED,
                            "isolated_vlm_generate",
                            (
                                ctx.vlm_base_url,
                                ctx.vlm_model,
                                ctx.vlm_api_key,
                                frame_paths,
                                frame_times_sec,
                                ctx.vlm_max_images,
                                ctx.vlm_context_length,
                            ),
                            timeout_sec=PIPELINE_STEP_TIMEOUT_SEC,
                        )

                    raw_vlm = await step_with_timeout_retries(item["id"], "VLM", _run_vlm)
                    if raw_vlm is not None:
                        description = raw_vlm.get("description") or ""
                        usage_dict = raw_vlm.get("usage")
                        usage = TokenUsage(**usage_dict) if usage_dict else None
                        est = int(raw_vlm.get("est") or 0)
                        try:
                            ctx.vlm_tokens.add_call(usage, estimated_total_tokens=est)
                        except Exception:
                            ctx.metrics_errors.append("vlm_usage_merge_error")
                        item["vlm_description"] = description.strip()
                        await update_clip_field(item["id"], "vlm_description", item["vlm_description"])
                        ok = True
        except ProcessCancelled:
            raise
        except Exception as e:
            logger.warning("片段 %s VLM 失败: %s", item["id"], e)
        finally:
            if ctx.do_vlm:
                async with ctx.progress_lock:
                    ctx.vlm_done += 1
                    if ok:
                        ctx.vlm_success += 1
                    await inc_progress(ctx, "vlm", "VLM", ctx.total_clips, ctx.vlm_success, ctx.vlm_done)
            await ctx.put_with_timeout(ctx.embed_queue, item, f"embed:{item['id']}")
            ctx.vlm_queue.task_done()


async def embed_worker(ctx: PipelineContext) -> None:
    assert ctx.embed_queue is not None and ctx.progress_lock is not None and ctx.vector_db_lock is not None
    while True:
        item = await ctx.embed_queue.get()
        if item is None:
            ctx.embed_queue.task_done()
            break
        ok = False
        try:
            await check_cancel(ctx.video_id)
            if ctx.do_embed and ctx.embedder is not None and ctx.vector_db is not None:
                if ctx.do_asr:
                    logger.info("片段 %s Embedding 等待 ASR 完成...", item["id"])
                    await item["asr_ready"].wait()
                text = f'{item["asr_text"]} {item["vlm_description"]}'.strip()
                if text:
                    try:
                        async with ctx.progress_lock:
                            await ctx.reporter.send(
                                "embed",
                                "running",
                                f"Embedding 正在处理片段 {item['id']}（已处理 {ctx.emb_done}/{ctx.total_clips}）",
                                {
                                    "current": ctx.emb_done,
                                    "total": ctx.total_clips,
                                    "inflight_clip_id": item["id"],
                                    "metrics": ctx.metrics_snapshot(),
                                },
                            )
                    except Exception:
                        pass
                    logger.info(
                        "片段 %s Embedding 开始：len=%d model=%s",
                        item["id"],
                        len(text),
                        ctx.embedding_model,
                    )

                    async def _run_embed():
                        await check_cancel(ctx.video_id)
                        if ctx.embed_inprocess:
                            usage_box: dict[str, Any] = {}

                            def _do_embed_sync():
                                def _on_usage(u):
                                    usage_box["usage"] = u

                                emb_vec = ctx.embedder.embed(text, on_usage=_on_usage)
                                u = usage_box.get("usage")
                                u_dict = u.to_dict() if isinstance(u, TokenUsage) else None
                                return {"embedding": emb_vec, "usage": u_dict}

                            return await asyncio.wait_for(asyncio.to_thread(_do_embed_sync), timeout=ctx.embedding_timeout_sec)
                        return await run_killable_target(
                            _PIPELINE_ISOLATED,
                            "isolated_embed_text",
                            (
                                ctx.embedding_base_url,
                                ctx.embedding_api_key,
                                ctx.embedding_model,
                                text,
                                ctx.embedding_timeout_sec,
                                ctx.vector_dim,
                            ),
                            timeout_sec=ctx.embedding_timeout_sec,
                        )

                    t_embed0 = time.perf_counter()
                    raw_emb = await step_with_timeout_retries(
                        item["id"],
                        "Embedding",
                        _run_embed,
                        timeout_sec=ctx.embedding_timeout_sec,
                    )
                    t_embed_ms = int((time.perf_counter() - t_embed0) * 1000)
                    if raw_emb is not None:
                        embedding = raw_emb["embedding"]
                        usage_dict = raw_emb.get("usage")
                        usage = TokenUsage(**usage_dict) if usage_dict else None
                        try:
                            ctx.embed_tokens.add_call(usage)
                        except Exception:
                            ctx.metrics_errors.append("embed_usage_merge_error")
                        async with ctx.vector_db_lock:
                            ctx.vector_db.add_embedding(item["id"], embedding)
                        logger.info("片段 %s Embedding 写入完成：%dms", item["id"], t_embed_ms)
                        ok = True
                    else:
                        logger.warning("片段 %s Embedding 失败/超时：%dms", item["id"], t_embed_ms)
                else:
                    logger.info("片段 %s Embedding 跳过：无可用文本（asr+vlm 为空）", item["id"])
            else:
                logger.info(
                    "片段 %s Embedding 跳过：do_embed=%s embedder=%s vector_db=%s",
                    item["id"],
                    ctx.do_embed,
                    bool(ctx.embedder),
                    bool(ctx.vector_db),
                )
        except ProcessCancelled:
            raise
        except Exception as e:
            logger.warning("片段 %s Embedding 失败: %s", item["id"], e)
        finally:
            if ctx.do_embed:
                async with ctx.progress_lock:
                    ctx.emb_done += 1
                    if ok:
                        ctx.emb_success += 1
                    await inc_progress(
                        ctx, "embed", "Embedding", ctx.total_clips, ctx.emb_success, ctx.emb_done
                    )
            ctx.embed_queue.task_done()


def start_workers(ctx: PipelineContext) -> None:
    ctx.all_workers = [
        *[asyncio.create_task(frames_worker(ctx)) for _ in range(max(1, ctx.frame_concurrency))],
        *[asyncio.create_task(vlm_worker(ctx)) for _ in range(max(1, ctx.vlm_concurrency))],
        *[asyncio.create_task(embed_worker(ctx)) for _ in range(max(1, ctx.embedding_concurrency))],
    ]
    if ctx.do_asr:
        ctx.all_workers.extend(
            [asyncio.create_task(asr_worker(ctx)) for _ in range(max(1, ctx.asr_concurrency))]
        )


async def cancel_all_workers(ctx: PipelineContext) -> None:
    from .process_pipeline_helpers import PIPELINE_WORKERS_DRAIN_TIMEOUT_SEC

    for t in ctx.all_workers:
        t.cancel()
    await asyncio.wait_for(
        asyncio.gather(*ctx.all_workers, return_exceptions=True),
        timeout=ctx.remaining_timeout(PIPELINE_WORKERS_DRAIN_TIMEOUT_SEC),
    )


async def enqueue_item(ctx: PipelineContext, item: dict) -> None:
    assert ctx.frame_queue is not None and ctx.asr_queue is not None
    await ctx.put_with_timeout(ctx.frame_queue, item, f"frame:{item['id']}")
    if ctx.do_asr:
        await ctx.put_with_timeout(ctx.asr_queue, item, f"asr:{item['id']}")


async def drain_workers(ctx: PipelineContext) -> None:
    from .process_pipeline_helpers import PIPELINE_WORKERS_DRAIN_TIMEOUT_SEC

    assert ctx.frame_queue is not None and ctx.asr_queue is not None
    assert ctx.vlm_queue is not None and ctx.embed_queue is not None

    fc = max(1, ctx.frame_concurrency)
    ac = max(1, ctx.asr_concurrency)
    vc = max(1, ctx.vlm_concurrency)
    ec = max(1, ctx.embedding_concurrency)

    for _ in range(fc):
        await ctx.put_with_timeout(ctx.frame_queue, None, "frame:sentinel")
    if ctx.do_asr:
        for _ in range(ac):
            await ctx.put_with_timeout(ctx.asr_queue, None, "asr:sentinel")
    await ctx.join_with_timeout(ctx.frame_queue, "frame")
    if ctx.do_asr:
        await ctx.join_with_timeout(ctx.asr_queue, "asr")
    for _ in range(vc):
        await ctx.put_with_timeout(ctx.vlm_queue, None, "vlm:sentinel")
    await ctx.join_with_timeout(ctx.vlm_queue, "vlm")
    for _ in range(ec):
        await ctx.put_with_timeout(ctx.embed_queue, None, "embed:sentinel")
    await ctx.join_with_timeout(ctx.embed_queue, "embed")
    await asyncio.wait_for(
        asyncio.gather(*ctx.all_workers, return_exceptions=True),
        timeout=ctx.remaining_timeout(PIPELINE_WORKERS_DRAIN_TIMEOUT_SEC),
    )
