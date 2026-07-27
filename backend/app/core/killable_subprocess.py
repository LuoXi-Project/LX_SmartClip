"""
在独立子进程中执行阻塞型同步任务，超时后对进程 terminate/kill，避免默认线程池 wait_for 后任务仍占用线程。

Windows 使用 multiprocessing spawn；任务目标须为模块顶层可 pickle 的函数。
"""
from __future__ import annotations

import importlib
import logging
import multiprocessing as mp
import queue
import traceback
from typing import Any

logger = logging.getLogger(__name__)

KILL_JOIN_AFTER_TERMINATE_SEC = 15.0


def _child_entry(result_q: mp.Queue, module: str, qualname: str, args: tuple, kwargs: dict) -> None:
    try:
        mod = importlib.import_module(module)
        fn = getattr(mod, qualname)
        out = fn(*args, **kwargs)
        result_q.put(("ok", out))
    except Exception:
        result_q.put(("err", traceback.format_exc()))


def _sync_run_target(
    module: str,
    qualname: str,
    args: tuple,
    kwargs: dict,
    timeout_sec: float,
) -> Any:
    ctx = mp.get_context("spawn")
    result_q: mp.Queue = ctx.Queue(maxsize=1)
    proc = ctx.Process(
        target=_child_entry,
        args=(result_q, module, qualname, args, kwargs),
        daemon=True,
    )
    proc.start()
    proc.join(timeout_sec)
    if proc.is_alive():
        logger.warning(
            "killable_subprocess: 超时 %.1fs，terminate pid=%s (%s.%s)",
            timeout_sec,
            proc.pid,
            module,
            qualname,
        )
        proc.terminate()
        proc.join(KILL_JOIN_AFTER_TERMINATE_SEC)
        if proc.is_alive():
            logger.warning("killable_subprocess: terminate 未结束，kill pid=%s", proc.pid)
            proc.kill()
            proc.join(5.0)
        try:
            status, payload = result_q.get_nowait()
            if status == "ok":
                return payload
        except queue.Empty:
            pass
        raise TimeoutError(f"子进程超时已终止: {module}.{qualname}")

    try:
        status, payload = result_q.get(timeout=3.0)
    except queue.Empty:
        raise RuntimeError(f"子进程已结束 (exit={proc.exitcode}) 但无返回: {module}.{qualname}")
    if status == "ok":
        return payload
    raise RuntimeError(payload)


async def run_killable_target(
    module: str,
    qualname: str,
    args: tuple = (),
    *,
    kwargs: dict | None = None,
    timeout_sec: float,
) -> Any:
    """在子进程中执行 ``module.qualname(*args, **kwargs)``，超时则终止子进程并抛出 ``TimeoutError``。

    使用专用 I/O 线程池（``run_in_blocking_executor``）而非 ``asyncio.to_thread``：本函数
    线程绝大部分时间在 ``proc.join()`` 上阻塞等待子进程，属于 I/O 等待而非 CPU 工作。
    若走默认 ThreadPoolExecutor，预处理流水线高并发时会占满默认线程池，导致普通 HTTP
    请求（列表/流/静态文件等）排队 → 前端整体卡顿。
    """
    from app.core.blocking_pool import run_in_blocking_executor

    return await run_in_blocking_executor(
        _sync_run_target, module, qualname, args, kwargs or {}, timeout_sec
    )
