import asyncio
from datetime import datetime
import logging
from fastapi import WebSocket
from app.core.splitter import VideoSplitter

logger = logging.getLogger(__name__)


def get_splitter(material_id: str) -> VideoSplitter:
    """按素材 ID 返回切分器（输出落在 ``storage/<material_id>/{clips,audio,frames}/``）。"""
    mid = (material_id or "").strip()
    if not mid:
        raise ValueError("material_id 不能为空")
    return VideoSplitter(material_id=mid)


# 用户停止：不能继承 Exception，否则会被流水线里大量 except Exception 吞掉
class ProcessCancelled(BaseException):
    pass


_cancel_events: dict[str, asyncio.Event] = {}
_job_tasks: dict[str, asyncio.Task] = {}
_task_subscribers: dict[str, set[WebSocket]] = {}


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def cancel_event_for(video_id: str) -> asyncio.Event:
    ev = _cancel_events.get(video_id)
    if ev is None:
        ev = asyncio.Event()
        _cancel_events[video_id] = ev
    return ev


def request_process_cancel(video_id: str) -> None:
    cancel_event_for(video_id).set()


async def check_cancel(video_id: str) -> None:
    if cancel_event_for(video_id).is_set():
        raise ProcessCancelled()


def parse_positive_int(raw: str, default: int, min_v: int = 1, max_v: int = 16) -> int:
    try:
        v = int(str(raw).strip())
    except Exception:
        return default
    if v < min_v:
        return min_v
    if v > max_v:
        return max_v
    return v


STEP_LABELS = {
    "split": "视频切分",
    "extract_frames": "图帧提取",
    "asr": "语音识别 (ASR)",
    "vlm": "视觉描述 (VLM)",
    "embed": "向量入库",
}
