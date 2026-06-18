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

from .runtime import _job_tasks, _ws_subscribers, _sse_subscribers, cancel_event_for, broadcast
from .store import delete_job, get_job, list_jobs, row_to_payload, update_job_status
from .sse import sse_event, sse_comment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ── REST 轮询 ──────────────────────────────────────────────────────────────────

@router.get("")
async def list_jobs_route(
    kind: str | None = None,
    active: bool = False,
    ref_id: str | None = None,
    limit: int = 200,
):
    """列出 job（按 created_at 升序=排队顺序）。可选 kind / active / ref_id 过滤。"""
    jobs = await list_jobs(kind=kind, active_only=active, ref_id=ref_id, limit=limit)
    # 注入 queue_index（活跃任务中的顺序），便于前端显示「排队第 N 位」
    for idx, j in enumerate(jobs):
        j["queue_index"] = idx
    return {"items": jobs, "total": len(jobs)}


@router.get("/{job_id}")
async def get_job_route(job_id: str):
    row = await get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"任务 '{job_id}' 不存在")
    return row_to_payload(row)


# ── 取消 ───────────────────────────────────────────────────────────────────────

async def _do_cancel_job(row) -> None:
    """kind-aware 取消：process 任务命中视频级 cancel 事件；其余沿用 job 级事件。"""
    job_id = row["id"]
    kind = row["kind"] if "kind" in row.keys() else None
    if kind == "process":
        # 管线监听的是视频级 cancel 事件（process_shared.cancel_event_for(video_id)）
        from app.api import process_shared as ps

        video_id = row["ref_id"] if "ref_id" in row.keys() else None
        if video_id:
            ps.request_process_cancel(video_id)
        # 若任务尚在队列未取出，标记跳过，实现「从队列移除而不执行」
        ps._pending_cancelled.add(job_id)
    else:
        cancel_event_for(job_id).set()
    t = _job_tasks.get(job_id)
    if t is not None:
        try:
            t.cancel()
        except Exception:
            pass
    await update_job_status(job_id, "cancelled")
    # 广播取消终止帧；SSE 层会把 step="done"+cancelled 转成 failed(cancelled)
    await broadcast(
        job_id,
        {"step": "done", "status": "cancelled", "message": "已取消", "detail": {"cancelled": True}},
    )


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str):
    row = await get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"任务 '{job_id}' 不存在")
    await _do_cancel_job(row)
    return {"ok": True, "job_id": job_id}


# ── 删除（停止后移除）──────────────────────────────────────────────────────────

@router.delete("/{job_id}")
async def delete_job_route(job_id: str):
    row = await get_job(job_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"任务 '{job_id}' 不存在")
    status = row["status"] if "status" in row.keys() else None
    # 运行中 / 排队中：先取消（停止），再删行
    if status in ("running", "pending"):
        await _do_cancel_job(row)
    deleted = await delete_job(job_id)
    return {"ok": True, "job_id": job_id, "deleted": deleted}


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
            # 仅终态立即结束；pending（排队中）当作进行中处理，进入直播循环等待 worker 接手
            if job_status in ("done", "error", "cancelled"):
                if job_status == "done":
                    yield sse_event("result", payload.get("result") or {"ok": True})
                elif job_status == "error":
                    yield sse_event("failed", {"message": payload.get("error_message") or "处理失败"})
                else:
                    yield sse_event("failed", {"message": "已取消", "cancelled": True})
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

                # 仅当 step="done" / step="error" 时才是任务级别的终态事件；
                # 各步骤自身的 done/error（如 split done, asr error）仅作为进度事件透传，
                # 不应终止 SSE 流，否则前端 TaskHub 会在首步完成后就显示「预处理完成」。
                if msg.get("step") == "done":
                    mstatus = msg.get("status")
                    yield sse_event("progress", msg)
                    if mstatus == "done":
                        final = row_to_payload(await get_job(job_id))
                        yield sse_event("result", final.get("result") or {"ok": True})
                    elif mstatus == "cancelled":
                        yield sse_event("failed", {"message": "已取消", "cancelled": True})
                    else:
                        yield sse_event("failed", {"message": msg.get("message") or "处理失败"})
                    return
                if msg.get("step") == "error":
                    yield sse_event("failed", {"message": msg.get("message") or "处理失败"})
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
