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


class SplitterBaseMixin:
        def __init__(self, storage_dir: str | None = None, material_id: str | None = None):
            """
            Args:
                storage_dir: 显式指定素材根目录（其下含 clips/audio/frames）。
                material_id: 素材 ID（通常即 videos.id），等价于 ``storage_dir = storage/<id>/``。
            """
            self._material_id: str | None = str(material_id).strip() if material_id and str(material_id).strip() else None
            if storage_dir is None:
                if self._material_id:
                    storage_dir = str(ensure_storage_subpath(self._material_id))
                else:
                    storage_dir = str(get_storage_root())
            self.storage_dir = storage_dir
            self.clips_dir = os.path.join(storage_dir, "clips")
            self.audio_dir = os.path.join(storage_dir, "audio")
            self.frames_dir = os.path.join(storage_dir, "frames")

            # 创建必要的目录
            os.makedirs(self.clips_dir, exist_ok=True)
            os.makedirs(self.audio_dir, exist_ok=True)
            os.makedirs(self.frames_dir, exist_ok=True)

            # keyframe 缓存：同一视频多次切分时避免重复 ffprobe
            # {video_path: sorted_keyframe_pts_time_list}
            self._keyframe_cache: Dict[str, List[float]] = {}
        def extract_audio(self, video_path: str, overwrite: bool = False) -> str:
            """
            使用 FFmpeg 提取视频音频为 WAV 格式
        
            Args:
                video_path: 视频文件路径
            
            Returns:
                音频文件路径
            """
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"视频文件不存在: {video_path}")

            # 与切片命名一致：落在 storage/<素材id>/audio/ 时，wav 名不再带前导素材 id（如 hybrid_0000.wav）
            base = os.path.basename(video_path)
            if self._material_id:
                base = strip_leading_material_id_from_clip_basename(self._material_id, base)
            stem = os.path.splitext(base)[0]
            audio_path = os.path.join(self.audio_dir, f"{stem}.wav")

            # 如果音频已存在且不要求覆盖，直接返回
            if os.path.exists(audio_path) and not overwrite:
                logger.info(f"音频文件已存在: {audio_path}")
                return audio_path

            # 使用 FFmpeg 提取音频
            cmd = [
                ffmpeg_bin(),
                "-i", video_path,
                "-q:a", "9",
                "-y" if overwrite else "-n",  # 覆盖或保留已存在文件
                audio_path,
            ]

            try:
                logger.info(f"开始提取音频: {video_path}")
                subprocess.run(cmd, check=True, capture_output=True)
                logger.info(f"音频提取成功: {audio_path}")
                return audio_path
            except subprocess.CalledProcessError as e:
                logger.error(f"音频提取失败: {e.stderr.decode()}")
                raise RuntimeError(f"音频提取失败: {str(e)}")
        def get_video_duration(self, video_path: str) -> float:
            """
            获取视频时长（秒）
        
            Args:
                video_path: 视频文件路径
            
            Returns:
                视频时长（秒）
            """
            try:
                duration = probe_duration(video_path, on_error="raise")
                logger.info(f"视频时长: {duration} 秒")
                return duration
            except Exception as e:
                logger.error(f"获取视频时长失败: {e}")
                raise RuntimeError(f"获取视频时长失败: {str(e)}")
        def frame_timestamps_in_clip(self, clip_path: str, frame_count: int) -> List[float]:
            """
            与 extract_frames 相同的片内采样时刻（秒）：第 i 帧对应 (i+1) * duration / (frame_count + 1)。

            不与 fps 强绑定——只要帧数与 extract_frames 产出一致，时间轴即对齐。
            """
            if frame_count <= 0:
                return []
            duration = self.get_video_duration(clip_path)
            interval = duration / (frame_count + 1)
            return [(i + 1) * interval for i in range(frame_count)]
        def has_video_stream(self, clip_path: str) -> bool:
            """
            检查视频文件是否包含视频流

            Args:
                clip_path: 视频文件路径

            Returns:
                是否包含视频流
            """
            return _has_video_stream(clip_path)
        def extract_frames(self, clip_path: str, fps: float = 1.0, target_pixels: int = 0) -> List[str]:
            """
            按帧率从视频片段中抽帧（每秒抽 fps 帧）

            Args:
                clip_path: 视频片段路径
                fps: 抽帧帧率（帧/秒），例如 1.0 表示每秒 1 帧，0.5 表示每 2 秒 1 帧
                target_pixels: 输出帧的长边像素限制，0 表示不压制，>0 时将长边等比缩放到该值

            Returns:
                帧文件路径列表
            """
            if not os.path.exists(clip_path):
                raise FileNotFoundError(f"视频片段不存在: {clip_path}")

            if fps <= 0:
                raise ValueError(f"fps 必须大于 0: {fps}")

            # 检查是否有视频流，音频专用片段直接跳过
            if not self.has_video_stream(clip_path):
                logger.warning(f"片段无视频流，跳过抽帧: {clip_path}")
                return []

            # 获取视频时长，据此计算总帧数
            duration = self.get_video_duration(clip_path)
            n_frames = max(1, int(duration * fps))

            # 创建帧存储目录（与切片文件同名 stem，且不含素材 id 前缀）
            bn = os.path.basename(clip_path)
            if self._material_id:
                bn = strip_leading_material_id_from_clip_basename(self._material_id, bn)
            clip_name = os.path.splitext(bn)[0]
            frames_output_dir = os.path.join(self.frames_dir, clip_name)
            os.makedirs(frames_output_dir, exist_ok=True)

            px_info = f", 长边压制={target_pixels}px" if target_pixels > 0 else ""
            logger.info(f"抽取帧: {clip_path}, fps={fps}, 时长={duration:.2f}s, 共 {n_frames} 帧{px_info}")

            frame_paths = []

            # 等间隔采样：将时长均分为 n_frames+1 段，取各段内侧时间点
            interval = duration / (n_frames + 1)

            for i in range(n_frames):
                timestamp = (i + 1) * interval
                frame_filename = f"frame_{i:03d}.jpg"
                frame_path = os.path.join(frames_output_dir, frame_filename)

                # 使用 FFmpeg 抽取帧：-ss 放在 -i 前快速定位，
                # 显式 -map 0:v:0 确保只映射视频流，避免「no stream」错误
                cmd = [
                    ffmpeg_bin(),
                    "-ss", str(timestamp),
                    "-i", clip_path,
                    "-map", "0:v:0",
                    "-vframes", "1",
                    "-q:v", "2",  # 高质量
                ]

                # 若设置了目标像素，按长边等比缩放（不放大原图）
                if target_pixels and target_pixels > 0:
                    p = target_pixels
                    # scale: 长边超过 target_pixels 则缩放，否则保持原尺寸；宽高保持偶数
                    vf = (
                        f"scale='if(gt(iw,ih),min({p},iw),trunc(oh*a/2)*2)':"
                        f"'if(gt(iw,ih),trunc(ow/a/2)*2,min({p},ih))':flags=lanczos"
                    )
                    cmd += ["-vf", vf]

                cmd += ["-y", frame_path]

                try:
                    logger.info(f"抽取帧 {i+1}/{n_frames}: {timestamp:.2f}s")
                    subprocess.run(cmd, check=True, capture_output=True)
                    frame_paths.append(frame_path)
                except subprocess.CalledProcessError as e:
                    logger.error(f"抽取帧失败: {e.stderr.decode()}")
                    raise RuntimeError(f"抽取帧失败: {str(e)}")

            logger.info(f"抽取帧完成: {len(frame_paths)} 帧")
            return frame_paths
