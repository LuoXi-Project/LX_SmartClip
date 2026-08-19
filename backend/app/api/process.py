import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.license import ensure_license_valid, is_license_enforced
from .process_db import (
    ProgressReporter,
    create_task,
    get_clips_by_ids_for_video,
    get_running_task_for_video,
    get_task,
    get_video,
    reconcile_orphan_task,
    row_to_task_payload,
    set_video_status,
    update_task_status,
)
from .process_pipeline import run_pipeline
from . import process_shared as ps
from .process_shared import ProcessCancelled, _job_tasks, _task_subscribers, request_process_cancel
from app.utils.logging_utils import stage_log

ALLOWED_SKIP_STEPS = frozenset({"split", "extract_frames", "asr", "vlm", "enrich", "embed", "replica"})

router = APIRouter(prefix="/api/videos", tags=["process"])
jobs_router = APIRouter(prefix="/api/process-jobs", tags=["process"])

logger = logging.getLogger(__name__)


class ProcessJobBody(BaseModel):
    skip_steps: list[str] = Field(default_factory=list)
    clip_ids: list[str] | None = None
    # 增量多向量化：仅补齐缺失的子空间向量（已存在的子空间不重复 embed）。
    # 供「预处理页面 → 继续拆维度向量化」使用，避免重跑时全量重 embed 浪费 API。
    embed_incremental: bool = False

    @field_validator("skip_steps")
    @classmethod
    def _validate_skip_steps(cls, v: list[str]) -> list[str]:
        for s in v:
            if s not in ALLOWED_SKIP_STEPS:
                raise ValueError(
                    f"skip_steps 含非法值 {s!r}，允许: {sorted(ALLOWED_SKIP_STEPS)}",
                )
        return v


def _normalize_clip_ids(raw: list[str] | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for x in raw:
        s = str(x).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


async def validate_process_job_options(video_id: str, body: ProcessJobBody) -> tuple[list[str], frozenset[str] | None]:
    skip_steps = list(body.skip_steps)
    clip_norm = _normalize_clip_ids(body.clip_ids)
    if clip_norm:
        if "split" not in skip_steps:
            raise HTTPException(
                status_code=400,
                detail="指定 clip_ids 时必须跳过切分（skip_steps 需包含 split）",
            )
        rows = await get_clips_by_ids_for_video(video_id, clip_norm)
        found = {r["id"] for r in rows}
        missing = [i for i in clip_norm if i not in found]
        if missing:
            raise HTTPException(
                status_code=400,
                detail="片段不存在或不属于该视频: " + ", ".join(missing[:12]),
            )
        return skip_steps, frozenset(clip_norm)
    return skip_steps, None


async def _run_task(
    task_id: str,
    video_id: str,
    skip_steps: list[str] | None = None,
    clip_ids_filter: frozenset[str] | None = None,
    embed_incremental: bool = False,
    job_id: str | None = None,
):
    reporter = ProgressReporter(ws=None, task_id=task_id, job_id=job_id)
    # 标记 async_job 为 running（从 pending 切换）
    if job_id:
        from app.jobs.store import update_job_status as _async_status
        from app.jobs.store import update_job_progress as _async_progress
        await _async_status(job_id, "running")
        await _async_progress(job_id, "split", "running", "开始处理...", {"percent": 0})

    stage_log("预处理", f"任务 {task_id[:8]}… 已启动 video_id={video_id}", status="running")
    try:
        await run_pipeline(
            video_id,
            reporter,
            skip_steps=skip_steps or [],
            task_id=task_id,
            clip_ids_filter=clip_ids_filter,
            embed_incremental=embed_incremental,
        )
        await update_task_status(task_id, "done")
        if job_id:
            await _async_status(job_id, "done", result={"video_id": video_id})
        await reporter.send("done", "done", "全部处理完成！", {"metrics": {}})
        stage_log("预处理", f"任务 {task_id[:8]}… 全部完成", status="done")
    except asyncio.CancelledError:
        await set_video_status(video_id, "pending")
        await reporter.send("done", "done", "处理已停止", {"cancelled": True})
        await update_task_status(task_id, "cancelled")
        if job_id:
            await _async_status(job_id, "cancelled")
    except ProcessCancelled:
        await set_video_status(video_id, "pending")
        await reporter.send("done", "done", "处理已停止", {"cancelled": True})
        await update_task_status(task_id, "cancelled")
        if job_id:
            await _async_status(job_id, "cancelled")
    except Exception as e:
        # asyncio.TimeoutError 等异常 str() 为空，兜底用类名，避免「处理异常: 」无法定位
        err_text = str(e).strip() or f"{type(e).__name__}（无错误消息）"
        logger.exception("预处理任务失败 video_id=%s task_id=%s", video_id, task_id)
        await set_video_status(video_id, "error")
        await reporter.send("error", "error", f"处理异常: {err_text}")
        await update_task_status(task_id, "error", error_message=err_text)
        if job_id:
            await _async_status(job_id, "error", error_message=err_text)
    finally:
        _job_tasks.pop(task_id, None)


async def _process_queue_worker():
    """串行处理队列：同一时间只跑一个预处理任务。"""
    while True:
        job_info = await ps._pending_queue.get()
        if job_info is None:  # 停止信号
            ps._pending_queue.task_done()
            break
        job_id = job_info.get("job_id") if isinstance(job_info, dict) else None
        try:
            # 已被用户取消/删除、尚在队列里的任务：跳过，不执行、不翻视频状态
            if job_id and job_id in ps._pending_cancelled:
                ps._pending_cancelled.discard(job_id)
                logger.info("队列跳过已取消的 process job: %s", job_id)
            else:
                await _run_task(**job_info)
        except Exception:
            logger.exception("队列任务异常")
        finally:
            ps._pending_queue.task_done()
            # 仅当队列已空时释放「正在处理」标志，保证排队期间新任务被正确判定为 queued
            if ps._pending_queue.empty():
                ps._processing_now = False


def _ensure_queue_worker():
    """懒启动队列 worker（只启动一次）。"""
    if ps._queue_worker_task is None or ps._queue_worker_task.done():
        ps._queue_worker_task = asyncio.create_task(_process_queue_worker())
        logger.info("预处理队列 worker 已启动")


@router.post("/{video_id}/process-cancel")
async def process_video_cancel(video_id: str):
    running = await get_running_task_for_video(video_id)
    if not running:
        return {"ok": True, "video_id": video_id}
    request_process_cancel(video_id)
    return {"ok": True, "video_id": video_id, "task_id": running["id"]}


@router.get("/process-queue-status")
async def get_process_queue_status():
    """返回队列状态：当前是否在跑、排队数量。"""
    return {
        "processing": ps._processing_now,
        "queue_size": ps._pending_queue.qsize(),
    }


def _default_job_body() -> ProcessJobBody:
    return ProcessJobBody()


async def enqueue_process_job(
    video_id: str,
    *,
    video_name: str = "",
    skip_steps: list[str] | None = None,
    clip_ids_filter: frozenset[str] | None = None,
    embed_incremental: bool = False,
) -> dict:
    """创建 process_task + async_job 并放入串行预处理队列。

    HTTP 入口（create_process_job）与外部关键词采集任务（external_search.ingest）
    共用；license 校验只留在 HTTP 层。
    """
    task_payload = await create_task(video_id)
    task_id = task_payload["id"]

    # 判断是立即执行还是排队（在创建 job 之前判定，决定初始状态）
    is_queued = ps._processing_now

    # 同步创建 async_job 供前端（TaskHub / ProcessPage）统一消费。
    # 排队中初始 pending；队列 worker 接手时在 _run_task 内切换为 running。
    from app.jobs.store import create_job as _async_create
    async_job = await _async_create(
        kind="process",
        ref_type="video",
        ref_id=video_id,
        ref_name=video_name,
        initial_step="split",
        initial_status="pending" if is_queued else "running",
    )
    job_id = async_job["id"]

    # 入队列
    job_info = {
        "task_id": task_id,
        "video_id": video_id,
        "skip_steps": list(skip_steps or []),
        "clip_ids_filter": clip_ids_filter,
        "embed_incremental": bool(embed_incremental),
        "job_id": job_id,
    }
    await ps._pending_queue.put(job_info)
    ps._processing_now = True
    _ensure_queue_worker()

    logger.info(
        "enqueue_process_job: video_id=%s task_id=%s job_id=%s queued=%s skip_steps=%s incremental=%s",
        video_id, task_id, job_id, is_queued, skip_steps, embed_incremental,
    )
    return {
        "task_id": task_id,
        "video_id": video_id,
        "job_id": job_id,
        "status": "queued" if is_queued else "running",
        "queue_size": ps._pending_queue.qsize(),
        "queue_position": ps._pending_queue.qsize(),
        "stream_url": f"/api/jobs/{job_id}/stream",
        "job_stream_url": f"/api/jobs/{job_id}/stream",
    }


@router.post("/{video_id}/process-jobs")
async def create_process_job(
    video_id: str,
    body: ProcessJobBody = Body(default_factory=_default_job_body),
):
    video = await get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")
    if is_license_enforced() and not await ensure_license_valid():
        raise HTTPException(status_code=403, detail="LICENSE_REQUIRED")
    skip_steps, clip_ids_filter = await validate_process_job_options(video_id, body)
    video_name = (video.get("name") if isinstance(video, dict) else None) or ""
    result = await enqueue_process_job(
        video_id,
        video_name=video_name,
        skip_steps=skip_steps,
        clip_ids_filter=clip_ids_filter,
        embed_incremental=bool(body.embed_incremental),
    )
    result["video_name"] = video_name
    return result


@jobs_router.get("/{task_id}")
async def get_process_job(task_id: str):
    row = await get_task(task_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"任务 '{task_id}' 不存在")
    return await reconcile_orphan_task(row)


@jobs_router.post("/{task_id}/cancel")
async def cancel_process_job(task_id: str):
    row = await get_task(task_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"任务 '{task_id}' 不存在")
    request_process_cancel(row["video_id"])
    t = _job_tasks.get(task_id)
    if t is not None:
        try:
            t.cancel()
        except Exception:
            pass
    # 即便任务协程已丢失，也将状态落库，避免永远 running
    await update_task_status(task_id, "cancelled")
    return {"ok": True, "task_id": task_id, "video_id": row["video_id"]}


@jobs_router.websocket("/{task_id}/ws")
async def process_job_ws(task_id: str, ws: WebSocket):
    await ws.accept()
    row = await get_task(task_id)
    if not row:
        await ws.send_json({"step": "error", "status": "error", "message": "任务不存在", "detail": {}})
        await ws.close()
        return
    _task_subscribers.setdefault(task_id, set()).add(ws)
    try:
        while True:
            await ws.receive()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        _task_subscribers.get(task_id, set()).discard(ws)
        try:
            await ws.close()
        except Exception:
            pass


@router.post("/{video_id}/process")
async def process_video_http(
    video_id: str,
    body: ProcessJobBody = Body(default_factory=_default_job_body),
):
    return await create_process_job(video_id, body)


def _parse_ws_first_payload(raw: Any) -> ProcessJobBody:
    if not isinstance(raw, dict):
        return ProcessJobBody()
    skip = raw.get("skip_steps")
    clips = raw.get("clip_ids")
    return ProcessJobBody.model_validate(
        {
            "skip_steps": skip if isinstance(skip, list) else [],
            "clip_ids": clips if isinstance(clips, list) else None,
            "embed_incremental": bool(raw.get("embed_incremental")),
        },
    )


@router.websocket("/{video_id}/process-ws")
async def process_video_ws(video_id: str, ws: WebSocket):
    await ws.accept()
    video = await get_video(video_id)
    if not video:
        await ws.send_json({"step": "error", "status": "error", "message": "视频不存在", "detail": {}})
        await ws.close()
        return
    if is_license_enforced() and not await ensure_license_valid():
        await ws.send_json({"step": "error", "status": "error", "message": "LICENSE_REQUIRED", "detail": {}})
        await ws.close()
        return
    try:
        raw = await asyncio.wait_for(ws.receive_json(), timeout=60.0)
    except Exception:
        raw = {}
    try:
        body = _parse_ws_first_payload(raw)
        skip_steps, clip_ids_filter = await validate_process_job_options(video_id, body)
    except ValidationError as e:
        await ws.send_json(
            {
                "step": "error",
                "status": "error",
                "message": "参数无效",
                "detail": {"errors": e.errors()},
            },
        )
        await ws.close()
        return
    except HTTPException as ex:
        detail = ex.detail if isinstance(ex.detail, str) else str(ex.detail)
        await ws.send_json({"step": "error", "status": "error", "message": detail, "detail": {}})
        await ws.close()
        return
    task_payload = await create_task(video_id)
    task_id = task_payload["id"]

    # 同步创建 async_job 供 TaskHub 展示
    from app.jobs.store import create_job as _async_create
    async_job = await _async_create(kind="process", ref_type="video", ref_id=video_id, initial_step="split")
    job_id = async_job["id"]

    logger.info(
        "process_video_ws: video_id=%s task_id=%s job_id=%s skip_steps=%s clip_ids=%s",
        video_id, task_id, job_id, skip_steps,
        sorted(list(clip_ids_filter)) if clip_ids_filter else [],
    )
    # 入队（串行处理）
    await ps._pending_queue.put({
        "task_id": task_id, "video_id": video_id,
        "skip_steps": skip_steps, "clip_ids_filter": clip_ids_filter,
        "embed_incremental": bool(body.embed_incremental),
        "job_id": job_id,
    })
    ps._processing_now = True
    _ensure_queue_worker()

    _task_subscribers.setdefault(task_id, set()).add(ws)
    try:
        while True:
            await ws.receive()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        _task_subscribers.get(task_id, set()).discard(ws)
        try:
            await ws.close()
        except Exception:
            pass
