"""素材处理流水线常量与通用辅助。"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.core.asr.types import ASRSegment, ASRTranscript

from .process_shared import ProcessCancelled, logger

PIPELINE_STEP_TIMEOUT_SEC = 600.0
PIPELINE_STEP_MAX_ATTEMPTS = 4
PIPELINE_TOTAL_TIMEOUT_SEC = 6 * 60 * 60.0
PIPELINE_SPLIT_TIMEOUT_SEC = 2 * 60 * 60.0
PIPELINE_QUEUE_TIMEOUT_SEC = 300.0
PIPELINE_WORKERS_DRAIN_TIMEOUT_SEC = 600.0

_PIPELINE_ISOLATED = "app.core.pipeline_isolated_workers"

T = TypeVar("T")


def transcript_from_payload(d: dict[str, Any]) -> ASRTranscript:
    segs: list[ASRSegment] = []
    for s in d.get("segments") or []:
        try:
            t = (s.get("text") or "").strip()
            if not t:
                continue
            segs.append(ASRSegment(start=float(s["start"]), end=float(s["end"]), text=t))
        except (KeyError, TypeError, ValueError):
            continue
    return ASRTranscript(text=(d.get("text") or "").strip(), segments=tuple(segs))


async def step_with_timeout_retries(
    clip_id: str,
    step_label: str,
    run: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = PIPELINE_STEP_MAX_ATTEMPTS,
    timeout_sec: float = PIPELINE_STEP_TIMEOUT_SEC,
) -> T | None:
    last_err: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await run()
        except asyncio.CancelledError:
            raise
        except ProcessCancelled:
            raise
        except TimeoutError as e:
            last_err = e
            logger.warning(
                "片段 %s %s 超时 (第 %d/%d 次, 限制 %.0fs)",
                clip_id,
                step_label,
                attempt,
                max_attempts,
                timeout_sec,
            )
        except Exception as e:
            last_err = e
            logger.warning(
                "片段 %s %s 失败 (第 %d/%d 次): %s",
                clip_id,
                step_label,
                attempt,
                max_attempts,
                e,
            )
        if attempt < max_attempts:
            await asyncio.sleep(min(2 ** (attempt - 1), 30))
    logger.error(
        "片段 %s %s 已达 %d 次尝试仍失败，跳过该步骤: %s",
        clip_id,
        step_label,
        max_attempts,
        last_err,
    )
    return None
