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
from .process_shared import ProcessCancelled, _job_tasks, _task_subscribers, request_process_cancel

ALLOWED_SKIP_STEPS = frozenset({"split", "extract_frames", "asr", "vlm", "embed"})

router = APIRouter(prefix="/api/videos", tags=["process"])
jobs_router = APIRouter(prefix="/api/process-jobs", tags=["process"])

logger = logging.getLogger(__name__)


class ProcessJobBody(BaseModel):
    skip_steps: list[str] = Field(default_factory=list)
    clip_ids: list[str] | None = None

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
):
    reporter = ProgressReporter(ws=None, task_id=task_id)
    try:
        await run_pipeline(
            video_id,
            reporter,
            skip_steps=skip_steps or [],
            task_id=task_id,
            clip_ids_filter=clip_ids_filter,
        )
        await update_task_status(task_id, "done")
    except asyncio.CancelledError:
        await set_video_status(video_id, "pending")
        await reporter.send("done", "done", "处理已停止", {"cancelled": True})
        await update_task_status(task_id, "cancelled")
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


@router.post("/{video_id}/process-cancel")
async def process_video_cancel(video_id: str):
    running = await get_running_task_for_video(video_id)
    if not running:
        return {"ok": True, "video_id": video_id}
    request_process_cancel(video_id)
    return {"ok": True, "video_id": video_id, "task_id": running["id"]}


def _default_job_body() -> ProcessJobBody:
    return ProcessJobBody()


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
    task_payload = await create_task(video_id)
    task_id = task_payload["id"]
    logger.info(
        "create_process_job: video_id=%s task_id=%s skip_steps=%s clip_ids=%s",
        video_id,
        task_id,
        skip_steps,
        sorted(list(clip_ids_filter)) if clip_ids_filter else [],
    )
    if task_id not in _job_tasks:
        _job_tasks[task_id] = asyncio.create_task(
            _run_task(task_id, video_id, skip_steps=skip_steps, clip_ids_filter=clip_ids_filter),
        )
    return {
        "task_id": task_id,
        "video_id": video_id,
        "status": task_payload["status"],
        "stream_url": f"/api/process-jobs/{task_id}/ws",
    }


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
    logger.info(
        "process_video_ws: video_id=%s task_id=%s skip_steps=%s clip_ids=%s",
        video_id,
        task_id,
        skip_steps,
        sorted(list(clip_ids_filter)) if clip_ids_filter else [],
    )
    if task_id not in _job_tasks:
        _job_tasks[task_id] = asyncio.create_task(
            _run_task(task_id, video_id, skip_steps=skip_steps, clip_ids_filter=clip_ids_filter),
        )
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
