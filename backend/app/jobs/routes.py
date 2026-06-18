"""通用 Job 进度路由：REST 轮询 / WS / SSE 流 / 取消。

端点：
  GET  /api/jobs/{id}         — 轮询快照
  POST /api/jobs/{id}/cancel  — 取消
  GET  /api/jobs/{id}/stream  — SSE 流（前端 reconnect 友好）
  WS   /api/jobs/{id}/ws      — WebSocket
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from .runtime import _job_tasks, _ws_subscribers, _sse_subscribers, cancel_event_for
from .store import get_job, row_to_payload, update_job_status
from .sse import sse_event, sse_comment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ── REST 轮询 ──────────────────────────────────────────────────────────────────

@router.get("/{job_id}")
async def get_job_route(job_id: str):
    row = await get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"任务 '{job_id}' 不存在")
    return row_to_payload(row)


# ── 取消 ───────────────────────────────────────────────────────────────────────

@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str):
    row = await get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"任务 '{job_id}' 不存在")
    cancel_event_for(job_id).set()
    t = _job_tasks.get(job_id)
    if t is not None:
        try:
            t.cancel()
        except Exception:
            pass
    await update_job_status(job_id, "cancelled")
    return {"ok": True, "job_id": job_id}


# ── SSE 流 ─────────────────────────────────────────────────────────────────────

@router.get("/{job_id}/stream")
async def stream_job(job_id: str):
    """SSE 命名事件流：重连时先回放当前 step 快照，再推进直播事件。"""

    async def gen():
        row = await get_job(job_id)
        payload = row_to_payload(row) if row else {}
        cur_step = payload.get("current_step")
        steps = payload.get("steps") or {}
        job_status = payload.get("status")

        queue: asyncio.Queue = asyncio.Queue()
        _sse_subscribers.setdefault(job_id, []).append(queue)

        try:
            # 终态 → 贴标签后直接结束
            if job_status != "running":
                if job_status == "done":
                    yield sse_event("result", payload.get("result") or {"ok": True})
                elif job_status == "error":
                    yield sse_event("failed", {"message": payload.get("error_message") or "处理失败"})
                elif job_status == "cancelled":
                    yield sse_event("failed", {"message": "已取消", "cancelled": True})
                else:
                    yield sse_event("failed", {"message": "任务未就绪"})
                return

            # 回放当前 step 为 progress 事件，让前端立即更新阶段/百分比
            if cur_step and cur_step in steps:
                st = steps[cur_step]
                yield sse_event(
                    "progress",
                    {
                        "step": cur_step,
                        "status": st.get("status", "running"),
                        "message": st.get("message", ""),
                        "detail": st.get("detail", {}),
                    },
                )

            # 直播推进
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=10.0)
                except asyncio.TimeoutError:
                    yield sse_comment()
                    continue

                mstatus = msg.get("status")
                if mstatus == "done":
                    yield sse_event("progress", msg)
                    final = row_to_payload(await get_job(job_id))
                    yield sse_event("result", final.get("result") or {"ok": True})
                    return
                if mstatus == "error":
                    yield sse_event("failed", {"message": msg.get("message") or "处理失败"})
                    return
                if mstatus == "cancelled":
                    yield sse_event("failed", {"message": "已取消", "cancelled": True})
                    return
                yield sse_event("progress", msg)
        finally:
            qs = _sse_subscribers.get(job_id)
            if qs and queue in qs:
                qs.remove(queue)
            if not qs:
                _sse_subscribers.pop(job_id, None)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ── WebSocket ──────────────────────────────────────────────────────────────────

@router.websocket("/{job_id}/ws")
async def job_ws(job_id: str, ws: WebSocket):
    await ws.accept()
    row = await get_job(job_id)
    if not row:
        await ws.send_json(
            {"step": "error", "status": "error", "message": "任务不存在", "detail": {}},
        )
        await ws.close()
        return
    # 先发当前快照
    await ws.send_json(row_to_payload(row))
    _ws_subscribers.setdefault(job_id, set()).add(ws)
    try:
        while True:
            await ws.receive()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        _ws_subscribers.get(job_id, set()).discard(ws)
        try:
            await ws.close()
        except Exception:
            pass
