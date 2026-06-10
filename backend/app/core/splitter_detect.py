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


class SplitterDetectMixin:
        def _expand_long_scene_ranges(
            self,
            start_time: float,
            end_time: float,
            max_segment_sec: float,
            chunk_sec: float,
        ) -> List[Tuple[float, float]]:
            """
            若 (end_time - start_time) > max_segment_sec，则按 chunk_sec 步长拆成多段；否则单段。
            """
            dur = end_time - start_time
            if dur <= max_segment_sec + 1e-6:
                return [(start_time, end_time)]
            if chunk_sec <= 0:
                raise ValueError(f"强制切段步长必须大于 0: {chunk_sec}")
            out: List[Tuple[float, float]] = []
            t = start_time
            while t < end_time - 1e-6:
                seg_end = min(t + chunk_sec, end_time)
                out.append((t, seg_end))
                t = seg_end
            return out
        def _detect_scene_time_ranges(
            self,
            video_path: str,
            threshold: float,
            min_scene_len: int,
        ) -> Tuple[List[Tuple[float, float]], bool]:
            """
            使用 PySceneDetect 得到镜头时间区间列表。

            Returns:
                (ranges, had_scene_cuts)
                - ranges: List[(start_sec, end_sec)]
                - had_scene_cuts: 是否检测到至少一处切镜（False 表示退化为整段视频）
            """
            try:
                from scenedetect import open_video, SceneManager
                from scenedetect.detectors import ContentDetector
            except ImportError:
                raise ImportError("请安装 scenedetect: pip install scenedetect[opencv]")

            if not os.path.exists(video_path):
                raise FileNotFoundError(f"视频文件不存在: {video_path}")

            threshold_value = float(threshold)
            if 0.0 < threshold_value <= 1.0:
                logger.warning(
                    f"检测到旧阈值范围 threshold={threshold_value}，自动使用推荐值 30.0 避免过碎切分"
                )
                threshold_value = 30.0

            min_scene_len_value = max(1, int(min_scene_len))

            video = open_video(video_path)
            scene_manager = SceneManager()
            scene_manager.add_detector(
                ContentDetector(
                    threshold=threshold_value,
                    min_scene_len=min_scene_len_value,
                )
            )
            scene_manager.detect_scenes(video, show_progress=True)
            scenes = scene_manager.get_scene_list() or []

            if not scenes:
                total_duration = self.get_video_duration(video_path)
                return [(0.0, total_duration)], False

            ranges = [
                (start_frame.get_seconds(), end_frame.get_seconds())
                for start_frame, end_frame in scenes
            ]
            return ranges, True
        def detect_shots_stream(
            self,
            video_path: str,
            *,
            mode: str = "adaptive",
            fixed_duration: float = 60.0,
            adaptive_threshold: float = 30.0,
            adaptive_min_scene_len: int = 30,
            max_shots: Optional[int] = None,
            show_progress: bool = True,
            should_stop: Optional[Callable[[], bool]] = None,
            on_progress: Optional[SplitProgressFn] = None,
            split_mode: str = "scene",
        ) -> Generator[Dict[str, float], None, None]:
            """流式返回镜头区间，避免等待全量检测完成。"""
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"视频文件不存在: {video_path}")

            mode = (mode or "adaptive").strip().lower()
            if mode not in {"adaptive", "fixed"}:
                mode = "adaptive"

            if mode == "fixed":
                dur = self.get_video_duration(video_path)
                if dur <= 0:
                    return
                seg = max(0.1, float(fixed_duration))
                shot_id = 0
                t = 0.0
                while t < dur - 1e-6:
                    ed = min(dur, t + seg)
                    if ed <= t + 1e-6:
                        break
                    yield {"shot_id": shot_id, "start": float(t), "end": float(ed)}
                    shot_id += 1
                    if max_shots is not None and shot_id >= int(max_shots):
                        break
                    t = ed
                return

            try:
                from scenedetect import open_video, SceneManager, FrameTimecode
                from scenedetect.detectors import ContentDetector
            except ImportError:
                raise ImportError("请安装 scenedetect: pip install scenedetect[opencv]")

            threshold_value = float(adaptive_threshold)
            if 0.0 < threshold_value <= 1.0:
                logger.warning(
                    f"检测到旧阈值范围 threshold={threshold_value}，自动使用推荐值 30.0 避免过碎切分"
                )
                threshold_value = 30.0
            min_scene_len_value = max(1, int(adaptive_min_scene_len))

            video = open_video(video_path)
            video_fps = float(video.frame_rate)
            min_duration_sec = min_scene_len_value / max(video_fps, 1e-6)

            shot_queue: queue.Queue = queue.Queue()
            detect_error: List[Exception] = []
            scene_cut_frames: List[int] = []
            sent_shot_keys: Set[Tuple[float, float]] = set()

            def frame_callback(frame_image, frame_num: int) -> None:  # noqa: ANN001
                if should_stop and should_stop():
                    raise StopRequested("镜头识别已停止")
                scene_cut_frames.append(frame_num)
                cut_count = len(scene_cut_frames)
                current_time = FrameTimecode(frame_num, video_fps).get_seconds()
                if cut_count == 1:
                    shot_start = 0.0
                    shot_end = current_time
                else:
                    prev_frame = scene_cut_frames[cut_count - 2]
                    shot_start = FrameTimecode(prev_frame, video_fps).get_seconds()
                    shot_end = current_time
                if shot_end - shot_start < min_duration_sec - 1e-6:
                    return
                key = (round(shot_start, 6), round(shot_end, 6))
                if key in sent_shot_keys:
                    return
                sent_shot_keys.add(key)
                shot_queue.put({"start": float(shot_start), "end": float(shot_end)})

            def _run_detect() -> None:
                try:
                    scene_manager = SceneManager()
                    scene_manager.add_detector(
                        ContentDetector(
                            threshold=threshold_value,
                            min_scene_len=min_scene_len_value,
                        )
                    )
                    scene_manager.detect_scenes(video, callback=frame_callback, show_progress=show_progress)
                    scene_list = scene_manager.get_scene_list() or []
                    seen_scenes: Set[Tuple[float, float]] = set()
                    final_shots: List[Dict[str, float]] = []
                    for scene in scene_list:
                        start_t = float(scene[0].get_seconds())
                        end_t = float(scene[1].get_seconds())
                        if end_t <= start_t + 1e-6:
                            continue
                        key = (round(start_t, 6), round(end_t, 6))
                        if key in seen_scenes:
                            continue
                        seen_scenes.add(key)
                        final_shots.append({"start": start_t, "end": end_t})

                    for s in final_shots:
                        key = (round(s["start"], 6), round(s["end"], 6))
                        if key not in sent_shot_keys:
                            sent_shot_keys.add(key)
                            shot_queue.put(s)

                    if not final_shots:
                        dur = self.get_video_duration(video_path)
                        if dur > 0:
                            shot_queue.put({"start": 0.0, "end": float(dur)})
                except Exception as exc:  # noqa: BLE001
                    detect_error.append(exc)
                finally:
                    shot_queue.put(_SENTINEL)

            thread = threading.Thread(target=_run_detect, daemon=True)
            thread.start()

            shot_count = 0
            while True:
                if should_stop and should_stop():
                    raise StopRequested("镜头识别已停止")
                try:
                    item = shot_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                if item is _SENTINEL:
                    break
                if max_shots is not None and shot_count >= int(max_shots):
                    continue
                item["shot_id"] = shot_count
                shot_count += 1
                _notify_split_progress(
                    on_progress,
                    phase="detecting",
                    split_mode=split_mode,
                    shots_detected=shot_count,
                    segments_planned=0,
                    clips_ready=0,
                )
                yield item

            if detect_error:
                raise detect_error[0]
            thread.join()
