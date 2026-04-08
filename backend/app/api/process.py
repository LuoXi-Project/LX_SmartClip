import asyncio
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from app.core.license import ensure_license_valid, is_license_enforced
from .process_db import ProgressReporter, create_task, get_running_task_for_video, get_task, get_video, row_to_task_payload, set_video_status, update_task_status
from .process_pipeline import run_pipeline
from .process_shared import ProcessCancelled, _job_tasks, _task_subscribers, request_process_cancel

router = APIRouter(prefix="/api/videos", tags=["process"])
jobs_router = APIRouter(prefix="/api/process-jobs", tags=["process"])


@router.post("/{video_id}/process-cancel")
async def process_video_cancel(video_id: str):
    running = await get_running_task_for_video(video_id)
    if not running:
        return {"ok": True, "video_id": video_id}
    request_process_cancel(video_id)
    return {"ok": True, "video_id": video_id, "task_id": running["id"]}


async def _run_task(task_id: str, video_id: str, skip_steps: list[str] | None = None):
    reporter = ProgressReporter(ws=None, task_id=task_id)
    try:
        await run_pipeline(video_id, reporter, skip_steps=skip_steps or [], task_id=task_id)
        await update_task_status(task_id, "done")
    except ProcessCancelled:
        await set_video_status(video_id, "pending")
        await reporter.send("done", "done", "处理已停止", {"cancelled": True})
        await update_task_status(task_id, "cancelled")
    except Exception as e:
        await set_video_status(video_id, "error")
        await reporter.send("error", "error", f"处理异常: {str(e)}")
        await update_task_status(task_id, "error", error_message=str(e))
    finally:
        _job_tasks.pop(task_id, None)


@router.post("/{video_id}/process-jobs")
async def create_process_job(video_id: str):
    video = await get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")
    if is_license_enforced() and not await ensure_license_valid():
        raise HTTPException(status_code=403, detail="LICENSE_REQUIRED")
    task_payload = await create_task(video_id)
    task_id = task_payload["id"]
    if task_id not in _job_tasks:
        _job_tasks[task_id] = asyncio.create_task(_run_task(task_id, video_id))
    return {"task_id": task_id, "video_id": video_id, "status": task_payload["status"], "stream_url": f"/api/process-jobs/{task_id}/ws"}


@jobs_router.get("/{task_id}")
async def get_process_job(task_id: str):
    row = await get_task(task_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"任务 '{task_id}' 不存在")
    return row_to_task_payload(row)


@jobs_router.post("/{task_id}/cancel")
async def cancel_process_job(task_id: str):
    row = await get_task(task_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"任务 '{task_id}' 不存在")
    request_process_cancel(row["video_id"])
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
async def process_video_http(video_id: str):
    return await create_process_job(video_id)


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
        _ = await asyncio.wait_for(ws.receive_json(), timeout=60.0)
    except Exception:
        pass
    task_payload = await create_task(video_id)
    task_id = task_payload["id"]
    if task_id not in _job_tasks:
        _job_tasks[task_id] = asyncio.create_task(_run_task(task_id, video_id))
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
