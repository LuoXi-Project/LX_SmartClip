import os
import subprocess
from pathlib import Path
from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)

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


class VideoSplitter:
    """视频切分器 - 支持镜头识别和固定时长切分"""

    def __init__(self, storage_dir: str = None):
        if storage_dir is None:
            storage_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "storage")
            )
        self.storage_dir = storage_dir
        self.clips_dir = os.path.join(storage_dir, "clips")
        self.audio_dir = os.path.join(storage_dir, "audio")
        self.frames_dir = os.path.join(storage_dir, "frames")

        # 创建必要的目录
        os.makedirs(self.clips_dir, exist_ok=True)
        os.makedirs(self.audio_dir, exist_ok=True)
        os.makedirs(self.frames_dir, exist_ok=True)

    def extract_audio(self, video_path: str) -> str:
        """
        使用 FFmpeg 提取视频音频为 WAV 格式
        
        Args:
            video_path: 视频文件路径
            
        Returns:
            音频文件路径
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"视频文件不存在: {video_path}")

        # 生成音频文件路径
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        audio_path = os.path.join(self.audio_dir, f"{video_name}.wav")

        # 如果音频已存在，直接返回
        if os.path.exists(audio_path):
            logger.info(f"音频文件已存在: {audio_path}")
            return audio_path

        # 使用 FFmpeg 提取音频
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-q:a", "9",
            "-n",  # 不覆盖已存在的文件
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
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1:nokey=1",
            video_path,
        ]

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            duration = float(result.stdout.strip())
            logger.info(f"视频时长: {duration} 秒")
            return duration
        except (subprocess.CalledProcessError, ValueError) as e:
            logger.error(f"获取视频时长失败: {e}")
            raise RuntimeError(f"获取视频时长失败: {str(e)}")

    def split_by_fixed(self, video_path: str, duration: float) -> List[ClipInfo]:
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

        clips = []
        video_name = os.path.splitext(os.path.basename(video_path))[0]

        for i in range(num_clips):
            start_time = i * duration
            end_time = min((i + 1) * duration, total_duration)
            clip_duration = end_time - start_time

            # 生成片段文件路径
            clip_filename = f"{video_name}_clip_{i:03d}.mp4"
            clip_path = os.path.join(self.clips_dir, clip_filename)

            # 使用 FFmpeg 切分视频
            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-ss", str(start_time),
                "-to", str(end_time),
                "-c", "copy",  # 不重新编码，直接复制
                "-n",  # 不覆盖已存在的文件
                clip_path,
            ]

            try:
                logger.info(f"切分片段 {i+1}/{num_clips}: {start_time:.2f}s - {end_time:.2f}s")
                subprocess.run(cmd, check=True, capture_output=True)
                clips.append(ClipInfo(clip_path, start_time, end_time, clip_duration))
            except subprocess.CalledProcessError as e:
                logger.error(f"切分片段失败: {e.stderr.decode()}")
                raise RuntimeError(f"切分片段失败: {str(e)}")

        logger.info(f"固定时长切分完成: {len(clips)} 个片段")
        return clips

    def split_by_scene(
        self,
        video_path: str,
        threshold: float = 30.0,
        min_scene_len: int = 30,
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
        try:
            from scenedetect import open_video, SceneManager
            from scenedetect.detectors import ContentDetector
        except ImportError:
            raise ImportError("请安装 scenedetect: pip install scenedetect[opencv]")

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

        # 检测场景
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
            logger.warning("未检测到场景切换，返回整个视频作为一个片段")
            total_duration = self.get_video_duration(video_path)
            clip_path = os.path.join(self.clips_dir, os.path.basename(video_path))
            return [ClipInfo(clip_path, 0, total_duration, total_duration)]

        logger.info(f"检测到 {len(scenes)} 个场景")

        clips = []
        video_name = os.path.splitext(os.path.basename(video_path))[0]

        for i, (start_frame, end_frame) in enumerate(scenes):
            # 将帧数转换为秒
            start_time = start_frame.get_seconds()
            end_time = end_frame.get_seconds()
            clip_duration = end_time - start_time

            # 生成片段文件路径
            clip_filename = f"{video_name}_scene_{i:03d}.mp4"
            clip_path = os.path.join(self.clips_dir, clip_filename)

            # 使用 FFmpeg 切分视频
            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-ss", str(start_time),
                "-to", str(end_time),
                "-c", "copy",
                "-n",
                clip_path,
            ]

            try:
                logger.info(f"切分场景 {i+1}/{len(scenes)}: {start_time:.2f}s - {end_time:.2f}s")
                subprocess.run(cmd, check=True, capture_output=True)
                clips.append(ClipInfo(clip_path, start_time, end_time, clip_duration))
            except subprocess.CalledProcessError as e:
                logger.error(f"切分场景失败: {e.stderr.decode()}")
                raise RuntimeError(f"切分场景失败: {str(e)}")

        logger.info(f"镜头识别切分完成: {len(clips)} 个片段")
        return clips

    def has_video_stream(self, clip_path: str) -> bool:
        """
        检查视频文件是否包含视频流

        Args:
            clip_path: 视频文件路径

        Returns:
            是否包含视频流
        """
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_type",
            "-of", "default=noprint_wrappers=1:nokey=1",
            clip_path,
        ]
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            return result.stdout.strip() == "video"
        except subprocess.CalledProcessError:
            return False

    def extract_frames(self, clip_path: str, fps: float = 1.0) -> List[str]:
        """
        按帧率从视频片段中抽帧（每秒抽 fps 帧）

        Args:
            clip_path: 视频片段路径
            fps: 抽帧帧率（帧/秒），例如 1.0 表示每秒 1 帧，0.5 表示每 2 秒 1 帧

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

        # 创建帧存储目录
        clip_name = os.path.splitext(os.path.basename(clip_path))[0]
        frames_output_dir = os.path.join(self.frames_dir, clip_name)
        os.makedirs(frames_output_dir, exist_ok=True)

        logger.info(f"抽取帧: {clip_path}, fps={fps}, 时长={duration:.2f}s, 共 {n_frames} 帧")

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
                "ffmpeg",
                "-ss", str(timestamp),
                "-i", clip_path,
                "-map", "0:v:0",
                "-vframes", "1",
                "-q:v", "2",  # 高质量
                "-n",
                frame_path,
            ]

            try:
                logger.info(f"抽取帧 {i+1}/{n_frames}: {timestamp:.2f}s")
                subprocess.run(cmd, check=True, capture_output=True)
                frame_paths.append(frame_path)
            except subprocess.CalledProcessError as e:
                logger.error(f"抽取帧失败: {e.stderr.decode()}")
                raise RuntimeError(f"抽取帧失败: {str(e)}")

        logger.info(f"抽取帧完成: {len(frame_paths)} 帧")
        return frame_paths
