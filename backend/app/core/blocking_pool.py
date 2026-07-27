"""
长时间阻塞型同步任务（匹配、ffmpeg 等）使用的专用线程池与异步并发闸门。

- asyncio.to_thread / 默认 ThreadPoolExecutor 会与其它逻辑共享、且线程数策略不可控，
  高并发时易导致排队不可预期或与其它任务争抢。
- 单独划池 + Semaphore：限制「同时执行的重任务」数量，其余请求在 async 侧等待，
  不阻塞事件循环；池在进程退出时在 lifespan 中显式 shutdown。
"""
from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

_executor: ThreadPoolExecutor | None = None
_io_executor: ThreadPoolExecutor | None = None
_heavy_semaphore: asyncio.Semaphore | None = None


def _default_worker_count() -> int:
    cpu = os.cpu_count() or 2
    return max(2, min(12, cpu + 2))


def _default_io_worker_count() -> int:
    """I/O 等待型线程池大小：线程绝大部分时间在 proc.join / socket read 上阻塞，
    几乎不占 CPU，故上限远高于 CPU 池，确保高并发预处理时子进程等待不互相串行。"""
    cpu = os.cpu_count() or 2
    return max(16, cpu * 4)


async def init_blocking_pool() -> None:
    """在 FastAPI lifespan 启动阶段调用（需在事件循环内，以便创建 Semaphore）。"""
    global _executor, _io_executor, _heavy_semaphore
    if _executor is not None:
        return

    raw_workers = int(os.environ.get("SMARTCLIP_HEAVY_POOL_WORKERS", "0"))
    workers = raw_workers if raw_workers > 0 else _default_worker_count()

    raw_io_workers = int(os.environ.get("SMARTCLIP_IO_POOL_WORKERS", "0"))
    io_workers = raw_io_workers if raw_io_workers > 0 else _default_io_worker_count()

    raw_cap = int(os.environ.get("SMARTCLIP_HEAVY_TASK_CONCURRENCY", "0"))
    concurrent = raw_cap if raw_cap > 0 else min(workers, 8)
    concurrent = max(1, min(concurrent, workers))

    _executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="schp-heavy")
    _io_executor = ThreadPoolExecutor(max_workers=io_workers, thread_name_prefix="schp-io")
    _heavy_semaphore = asyncio.Semaphore(concurrent)
    logger.info(
        "Heavy blocking pool ready: thread_pool_workers=%d io_pool_workers=%d async_concurrency_cap=%d "
        "(env SMARTCLIP_HEAVY_POOL_WORKERS / SMARTCLIP_IO_POOL_WORKERS / SMARTCLIP_HEAVY_TASK_CONCURRENCY)",
        workers,
        io_workers,
        concurrent,
    )


def shutdown_blocking_pool() -> None:
    """进程退出前释放线程；已在跑的任务会等到线程函数返回（无法强行中断同步代码）。"""
    global _executor, _io_executor, _heavy_semaphore
    ex = _executor
    io_ex = _io_executor
    _executor = None
    _io_executor = None
    _heavy_semaphore = None
    for e in (ex, io_ex):
        if e is not None:
            e.shutdown(wait=True, cancel_futures=False)
    logger.info("Heavy blocking pool shutdown complete")


async def run_heavy(callable: Callable[..., _T], /, *args: Any, **kwargs: Any) -> _T:
    """
    在专用线程池执行可调用对象，并占用「重任务」并发名额。

    注意：协程被取消（客户端断开等）时，await 会收到 CancelledError，但已提交的线程
    仍可能跑完；这是阻塞式第三方 SDK / subprocess 的通用限制。
    """
    ex = _executor
    sem = _heavy_semaphore
    if ex is None or sem is None:
        raise RuntimeError("blocking pool not initialized (missing lifespan init_blocking_pool?)")

    def _call() -> _T:
        return callable(*args, **kwargs)

    loop = asyncio.get_running_loop()
    async with sem:
        return await loop.run_in_executor(ex, _call)


async def run_in_blocking_executor(callable: Callable[..., _T], /, *args: Any, **kwargs: Any) -> _T:
    """
    在专用线程池执行可调用对象，但**不**占用「重任务」并发名额。

    适用于「阻塞但几乎纯等待」的任务，例如 ``proc.join()`` 等待子进程、阻塞式 socket
    read 等：这类任务线程大部分时间在 I/O 等待而非占 CPU，不应与 split / ffmpeg 这类
    CPU 重任务争同一个 Semaphore，否则会把并发压得很低。

    关键收益：把这些等待从 asyncio 默认 ThreadPoolExecutor 移走，避免预处理流水线高并发
    时占满默认线程池（默认线程池还服务于普通 HTTP 请求、FileResponse、aiosqlite 兜底等），
    导致前端整体卡顿。
    """
    ex = _io_executor
    if ex is None:
        raise RuntimeError("blocking pool not initialized (missing lifespan init_blocking_pool?)")

    def _call() -> _T:
        return callable(*args, **kwargs)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(ex, _call)
