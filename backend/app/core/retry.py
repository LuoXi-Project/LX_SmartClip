"""
retry.py — 统一 API 调用重试工具

使用方式
--------
同步调用:
    from app.core.retry import retry_sync

    result = retry_sync(my_func, arg1, arg2, retries=3)

异步调用:
    from app.core.retry import retry_async

    result = await retry_async(my_async_func, arg1, arg2, retries=3)

装饰器方式（同步）:
    from app.core.retry import with_retry

    @with_retry(retries=3)
    def call_api(): ...

装饰器方式（异步）:
    from app.core.retry import with_async_retry

    @with_async_retry(retries=3)
    async def call_api(): ...

默认策略
--------
- 最大重试次数: 3
- 首次等待:     1.0 秒
- 退避系数:     2.0（指数退避）
- 最大等待上限: 60 秒
- 随机抖动:     ±20%（避免惊群）
- 不可重试异常: ValueError / TypeError / FileNotFoundError（参数/逻辑错误，重试无意义）
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
import time
from typing import Any, Callable, Optional, Tuple, Type

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 默认配置
# ──────────────────────────────────────────────
_DEFAULT_RETRIES: int = 3
_DEFAULT_BASE_WAIT: float = 1.0   # 秒
_DEFAULT_BACKOFF: float = 2.0     # 指数退避系数
_DEFAULT_MAX_WAIT: float = 60.0   # 最大等待上限（秒）
_JITTER_RATIO: float = 0.2        # ±20% 随机抖动

# 这些异常属于调用方逻辑错误，不应重试
_NO_RETRY_EXCEPTIONS: Tuple[Type[BaseException], ...] = (
    ValueError,
    TypeError,
    FileNotFoundError,
)


# ──────────────────────────────────────────────
# 内部辅助
# ──────────────────────────────────────────────

def _calc_wait(attempt: int, base_wait: float, backoff: float, max_wait: float) -> float:
    """计算第 attempt 次重试的等待时间（含随机抖动）"""
    raw = base_wait * (backoff ** attempt)
    capped = min(raw, max_wait)
    jitter = capped * _JITTER_RATIO * (random.random() * 2 - 1)  # ±jitter
    return max(0.0, capped + jitter)


def _should_retry(exc: BaseException) -> bool:
    """判断该异常是否值得重试"""
    return not isinstance(exc, _NO_RETRY_EXCEPTIONS)


def _log_retry(func_name: str, attempt: int, retries: int, exc: BaseException, wait: float) -> None:
    logger.warning(
        "[Retry] %s 第 %d/%d 次失败: %s — %.1fs 后重试",
        func_name,
        attempt + 1,
        retries,
        exc,
        wait,
    )


def _log_give_up(func_name: str, retries: int, exc: BaseException) -> None:
    logger.error(
        "[Retry] %s 已重试 %d 次，最终失败: %s",
        func_name,
        retries,
        exc,
    )


# ──────────────────────────────────────────────
# 公共 API — 同步
# ──────────────────────────────────────────────

def retry_sync(
    func: Callable[..., Any],
    *args: Any,
    retries: int = _DEFAULT_RETRIES,
    base_wait: float = _DEFAULT_BASE_WAIT,
    backoff: float = _DEFAULT_BACKOFF,
    max_wait: float = _DEFAULT_MAX_WAIT,
    **kwargs: Any,
) -> Any:
    """
    同步重试执行 func(*args, **kwargs)。

    Args:
        func:      待调用的同步函数
        *args:     传给 func 的位置参数
        retries:   最大重试次数（不含首次调用）
        base_wait: 首次失败后等待秒数
        backoff:   指数退避系数
        max_wait:  单次等待上限（秒）
        **kwargs:  传给 func 的关键字参数

    Returns:
        func 的返回值

    Raises:
        最后一次调用抛出的异常
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(retries + 1):
        try:
            return func(*args, **kwargs)
        except BaseException as exc:
            last_exc = exc
            if not _should_retry(exc) or attempt == retries:
                _log_give_up(func.__name__, attempt, exc)
                raise
            wait = _calc_wait(attempt, base_wait, backoff, max_wait)
            _log_retry(func.__name__, attempt, retries, exc, wait)
            time.sleep(wait)
    raise last_exc  # type: ignore[misc]  # 理论上不会到达此处


def with_retry(
    retries: int = _DEFAULT_RETRIES,
    base_wait: float = _DEFAULT_BASE_WAIT,
    backoff: float = _DEFAULT_BACKOFF,
    max_wait: float = _DEFAULT_MAX_WAIT,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """同步重试装饰器"""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return retry_sync(
                func, *args,
                retries=retries,
                base_wait=base_wait,
                backoff=backoff,
                max_wait=max_wait,
                **kwargs,
            )
        return wrapper
    return decorator


# ──────────────────────────────────────────────
# 公共 API — 异步
# ──────────────────────────────────────────────

async def retry_async(
    func: Callable[..., Any],
    *args: Any,
    retries: int = _DEFAULT_RETRIES,
    base_wait: float = _DEFAULT_BASE_WAIT,
    backoff: float = _DEFAULT_BACKOFF,
    max_wait: float = _DEFAULT_MAX_WAIT,
    **kwargs: Any,
) -> Any:
    """
    异步重试执行 await func(*args, **kwargs)。

    Args:
        func:      待调用的异步函数（coroutine function）
        *args:     传给 func 的位置参数
        retries:   最大重试次数（不含首次调用）
        base_wait: 首次失败后等待秒数
        backoff:   指数退避系数
        max_wait:  单次等待上限（秒）
        **kwargs:  传给 func 的关键字参数

    Returns:
        func 的返回值

    Raises:
        最后一次调用抛出的异常
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(retries + 1):
        try:
            return await func(*args, **kwargs)
        except BaseException as exc:
            last_exc = exc
            if not _should_retry(exc) or attempt == retries:
                _log_give_up(func.__name__, attempt, exc)
                raise
            wait = _calc_wait(attempt, base_wait, backoff, max_wait)
            _log_retry(func.__name__, attempt, retries, exc, wait)
            await asyncio.sleep(wait)
    raise last_exc  # type: ignore[misc]


def with_async_retry(
    retries: int = _DEFAULT_RETRIES,
    base_wait: float = _DEFAULT_BASE_WAIT,
    backoff: float = _DEFAULT_BACKOFF,
    max_wait: float = _DEFAULT_MAX_WAIT,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """异步重试装饰器"""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await retry_async(
                func, *args,
                retries=retries,
                base_wait=base_wait,
                backoff=backoff,
                max_wait=max_wait,
                **kwargs,
            )
        return wrapper
    return decorator
