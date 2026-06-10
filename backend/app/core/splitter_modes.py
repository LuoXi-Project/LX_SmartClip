from __future__ import annotations

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

from app.core.splitter_types import (
    ClipInfo,
    SplitProgressFn,
    StopRequested,
    notify_split_progress as _notify_split_progress,
)

logger = logging.getLogger(__name__)


class SplitterModesMixin:
        def split_by_fixed(
            self,
            video_path: str,
            duration: float,
            transcode_opts: Optional[Dict[str, str]] = None,
            on_clip_created: Optional[Callable[[ClipInfo], None]] = None,
            on_progress: Optional[SplitProgressFn] = None,
            should_stop: Optional[Callable[[], bool]] = None,
        ) -> List[ClipInfo]:
            """
            固定时长切分视频
        
            Args:
                video_path: 视频文件路径
                duration: 每个片段的时长（秒）
            
            Returns:
                片段信息列表
            """
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"视频文件不存在: {video_path}")

            if duration <= 0:
                raise ValueError(f"时长必须大于 0: {duration}")

            # 获取视频总时长
            total_duration = self.get_video_duration(video_path)
        
            # 计算片段数量
            num_clips = int(total_duration / duration) + (1 if total_duration % duration > 0 else 0)
        
            logger.info(f"固定时长切分: 总时长={total_duration}s, 片段时长={duration}s, 片段数={num_clips}")

            # 预生成所有时间区间
            ranges: List[Tuple[float, float]] = []
            for i in range(num_clips):
                start_time = i * duration
                end_time = min((i + 1) * duration, total_duration)
                if end_time <= start_time + 1e-6:
                    continue
                ranges.append((start_time, end_time))

            clips = self._cut_ranges_parallel(
                video_path,
                ranges,
                transcode_opts=transcode_opts,
                on_clip_created=on_clip_created,
                on_progress=on_progress,
                split_mode="fixed",
                should_stop=should_stop,
                name_prefix="clip",
                index_width=3,
            )
            logger.info(f"固定时长切分完成: {len(clips)} 个片段")
            return clips
        def split_by_scene(
            self,
            video_path: str,
            threshold: float = 30.0,
            min_scene_len: int = 30,
            transcode_opts: Optional[Dict[str, str]] = None,
            on_clip_created: Optional[Callable[[ClipInfo], None]] = None,
            on_progress: Optional[SplitProgressFn] = None,
            should_stop: Optional[Callable[[], bool]] = None,
        ) -> List[ClipInfo]:
            """
            使用 PySceneDetect 进行镜头识别切分
        
            Args:
                video_path: 视频文件路径
                threshold: 场景检测阈值（推荐 27~35，值越小越敏感）
                min_scene_len: 最小场景长度（帧数），用于抑制过碎切分
            
            Returns:
                片段信息列表
            """
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"视频文件不存在: {video_path}")

            # 兼容旧配置：若传入 0~1 的阈值（如 0.4），按新版参数回退到推荐值
            threshold_value = float(threshold)
            if 0.0 < threshold_value <= 1.0:
                logger.warning(
                    f"检测到旧阈值范围 threshold={threshold_value}，自动使用推荐值 30.0 避免过碎切分"
                )
                threshold_value = 30.0

            min_scene_len_value = max(1, int(min_scene_len))

            logger.info(
                f"镜头识别切分: 视频={video_path}, 阈值={threshold_value}, min_scene_len={min_scene_len_value}"
            )

            # 拉取场景时间区间（复用 streaming 逻辑以避免重复实现）
            # 这里不需要 streaming 消费，一次性拉到列表即可
            ranges: List[Tuple[float, float]] = []
            shots_detected = 0
            for shot in self.detect_shots_stream(
                video_path,
                mode="adaptive",
                adaptive_threshold=threshold_value,
                adaptive_min_scene_len=min_scene_len_value,
                should_stop=should_stop,
                on_progress=on_progress,
                split_mode="scene",
            ):
                if should_stop and should_stop():
                    raise StopRequested("镜头识别切分已停止")
                start_time = float(shot["start"])
                end_time = float(shot["end"])
                if end_time <= start_time + 1e-6:
                    continue
                ranges.append((start_time, end_time))
                shots_detected = len(ranges)

            if not ranges:
                logger.warning("未检测到场景切换，返回整个视频作为一个片段")
                total_duration = self.get_video_duration(video_path)
                # 使用统一的切分管线输出整段视频（便于应用转码参数、日志控制）
                whole = self._cut_ranges_parallel(
                    video_path,
                    [(0.0, total_duration)],
                    transcode_opts=transcode_opts,
                    on_clip_created=on_clip_created,
                    on_progress=on_progress,
                    split_mode="scene",
                    should_stop=should_stop,
                    name_prefix="scene_fallback",
                    index_width=3,
                    shots_detected=0,
                )
                return whole

            clips = self._cut_ranges_parallel(
                video_path,
                ranges,
                transcode_opts=transcode_opts,
                on_clip_created=on_clip_created,
                on_progress=on_progress,
                split_mode="scene",
                should_stop=should_stop,
                name_prefix="scene",
                index_width=3,
                shots_detected=shots_detected,
            )
            logger.info(f"镜头识别切分完成: {len(clips)} 个片段")
            return clips
