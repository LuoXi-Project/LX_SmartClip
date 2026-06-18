"""通用 Job 的运行时：订阅注册表、JobReporter（写库 + 广播）、取消、后台任务启动。

镜像 app/api/process_shared.py + process_db.ProgressReporter，新增 SSE 订阅
（per-client asyncio.Queue）以支持 StreamingResponse 拉取式消费。
"""

import asyncio
import logging

from fastapi import WebSocket

from app.utils.logging_utils import stage_log

from .store import update_job_progress, update_job_status

logger = logging.getLogger(__name__)

# job_id -> asyncio.Task（后台工作协程）
_job_tasks: dict[str, asyncio.Task] = {}
# job_id -> asyncio.Event（取消信号）
_cancel_events: dict[str, asyncio.Event] = {}
# job_id -> set[WebSocket]（WS 订阅者）
_ws_subscribers: dict[str, set[WebSocket]] = {}
# job_id -> list[asyncio.Queue]（SSE 订阅者，每个客户端一个队列）
_sse_subscribers: dict[str, list[asyncio.Queue]] = {}


class JobCancelled(BaseException):
    """取消异常：继承 BaseException，避免被业务代码的 except Exception 吞掉。"""

    pass


def cancel_event_for(job_id: str) -> asyncio.Event:
    ev = _cancel_events.get(job_id)
    if ev is None:
        ev = asyncio.Event()
        _cancel_events[job_id] = ev
    return ev


def is_cancelled(job_id: str) -> bool:
    return cancel_event_for(job_id).is_set()


async def check_cancel(job_id: str) -> None:
    if is_cancelled(job_id):
        raise JobCancelled()


async def broadcast(job_id: str, payload: dict) -> None:
    """同时向 WS 与 SSE 订阅者广播一条进度消息。"""
    subs = _ws_subscribers.get(job_id)
    if subs:
        stale: list[WebSocket] = []
        for ws in subs:
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            subs.discard(ws)
        if not subs:
            _ws_subscribers.pop(job_id, None)

    queues = _sse_subscribers.get(job_id)
    if queues:
        for q in queues:
            try:
                q.put_nowait(payload)
            except Exception:
                pass


class JobReporter:
    """一次 send 同时：写库（update_job_progress）+ 广播给 WS/SSE 订阅者。"""

    def __init__(self, job_id: str):
        self.job_id = job_id

    async def send(self, step: str, status: str, message: str, detail: dict | None = None):
        payload = {"step": step, "status": status, "message": message, "detail": detail or {}}
        stage_log("后台任务", f"{step} — {message}", status=status)
        logger.info("[job %s] %s/%s: %s", self.job_id[:8], step, status, message)
        await update_job_progress(self.job_id, step=step, status=status, message=message, detail=payload["detail"])
        await broadcast(self.job_id, payload)


def launch_job(job_id: str, coro) -> asyncio.Task:
    """把工作协程包成后台任务，统一处理取消/异常/清理。

    成功完成需由工作协程自行调用 reporter.send(...,'done',...) + update_job_status('done', result=...)；
    本包装只兜底 cancel/error，并在异常时广播终止帧。
    """

    async def _wrap():
        try:
            await coro
        except (asyncio.CancelledError, JobCancelled):
            await update_job_status(job_id, "cancelled")
            await broadcast(
                job_id,
                {"step": "done", "status": "cancelled", "message": "已取消", "detail": {"cancelled": True}},
            )
        except Exception as e:
            logger.exception("job %s failed", job_id)
            await update_job_status(job_id, "error", error_message=str(e))
            await broadcast(
                job_id,
                {"step": "error", "status": "error", "message": f"处理失败: {e}", "detail": {}},
            )
        finally:
            _job_tasks.pop(job_id, None)

    task = asyncio.create_task(_wrap())
    _job_tasks[job_id] = task
    return task
