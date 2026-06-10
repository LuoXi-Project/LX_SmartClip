import os
import subprocess
import queue
import threading
import bisect
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, Generator, List, Optional, Set, Tuple
import logging

from app.utils.bin_paths import ffmpeg_bin
from app.utils.bin_paths import ffprobe_bin
from app.utils.ffprobe_utils import has_video_stream as _has_video_stream, probe_duration
from app.utils.paths import ensure_storage_subpath, get_storage_root
from app.utils.storage_dedupe import strip_leading_material_id_from_clip_basename

logger = logging.getLogger(__name__)
_SENTINEL = object()

# phase: detecting（镜头识别）| planning（二次切分规划）| cutting（ffmpeg 导出）
SplitProgressFn = Callable[[Dict[str, Any]], None]


def notify_split_progress(
    on_progress: Optional[SplitProgressFn],
    *,
    phase: str,
    split_mode: str = "",
    shots_detected: int = 0,
    segments_planned: int = 0,
    clips_ready: int = 0,
) -> None:
    if not on_progress:
        return
    total = segments_planned if segments_planned > 0 else 0
    current = clips_ready if phase == "cutting" and total > 0 else (
        segments_planned if phase == "planning" and total > 0 else shots_detected
    )
    on_progress(
        {
            "phase": phase,
            "split_mode": split_mode,
            "shots_detected": shots_detected,
            "segments_planned": segments_planned,
            "clips_ready": clips_ready,
            "current": current,
            "total": total,
        },
    )

class StopRequested(Exception):
    """外部请求停止切分流程。"""

class ClipInfo:
    """视频片段信息"""
    def __init__(self, clip_path: str, start_time: float, end_time: float, duration: float):
        self.clip_path = clip_path
        self.start_time = start_time
        self.end_time = end_time
        self.duration = duration

    def to_dict(self):
        return {
            "clip_path": self.clip_path,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
        }


