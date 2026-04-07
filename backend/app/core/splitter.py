import os
import subprocess
import queue
import threading
from typing import Callable, Dict, Generator, List, Optional, Set, Tuple
import logging

from app.utils.bin_paths import ffmpeg_bin
from app.utils.ffprobe_utils import has_video_stream as _has_video_stream, probe_duration

logger = logging.getLogger(__name__)
_SENTINEL = object()

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
    """视频切分器 - 支持镜头识别、固定时长与混合（镜头 + 超长强制切段）切分"""

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

        # 生成音频文件路径
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        audio_path = os.path.join(self.audio_dir, f"{video_name}.wav")

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

    def _build_transcode_args(
        self,
        *,
        has_video_stream: bool,
        output_container: str,
        opts: Optional[Dict[str, str]] = None,
    ) -> List[str]:
        """
        根据配置构建 FFmpeg 编码参数（用于切分输出片段）。

        opts 约定（均为字符串，便于从配置表读取）：
        - clip_vcodec: libx264/libx265/libvpx-vp9/copy...
        - clip_acodec: aac/libopus/copy...
        - clip_preset: ultrafast/superfast/veryfast/faster/fast/medium/slow/slower/veryslow
        - clip_crf: 0~51（仅 x264/x265）
        - clip_video_bitrate_kbps: 例如 2500（>0 则优先生效，且会忽略 crf）
        - clip_audio_bitrate_kbps: 例如 128（>0 生效）
        - clip_fps: 例如 30（>0 则通过滤镜强制 CFR）
        - clip_scale_width / clip_scale_height: 例如 1920/1080（0=不限制；可只填一边）
        - clip_pix_fmt: yuv420p/yuv422p...
        """
        opts = opts or {}

        vcodec = (opts.get("clip_vcodec") or "libx264").strip()
        acodec = (opts.get("clip_acodec") or "aac").strip()
        preset = (opts.get("clip_preset") or "veryfast").strip()
        pix_fmt = (opts.get("clip_pix_fmt") or "yuv420p").strip()

        def _to_int(name: str, default: int = 0) -> int:
            try:
                return int(float((opts.get(name) or "").strip() or default))
            except Exception:
                return default

        def _to_float(name: str, default: float = 0.0) -> float:
            try:
                return float((opts.get(name) or "").strip() or default)
            except Exception:
                return default

        crf = _to_int("clip_crf", 23)
        v_bitrate_kbps = _to_int("clip_video_bitrate_kbps", 0)
        a_bitrate_kbps = _to_int("clip_audio_bitrate_kbps", 128)
        fps = _to_float("clip_fps", 0.0)
        scale_w = _to_int("clip_scale_width", 0)
        scale_h = _to_int("clip_scale_height", 0)

        vf_parts: List[str] = []
        if scale_w > 0 or scale_h > 0:
            # 只设置一边时，另一边保持等比（-2 以保证偶数）
            sw = scale_w if scale_w > 0 else -2
            sh = scale_h if scale_h > 0 else -2
            vf_parts.append(f"scale={sw}:{sh}:flags=lanczos")
        if fps and fps > 0:
            vf_parts.append(f"fps={fps}")

        args: List[str] = []
        if has_video_stream:
            args += ["-map", "0:v:0", "-map", "0:a?"]
            args += ["-c:v", vcodec]
            if vcodec in ("libx264", "libx265") and preset:
                args += ["-preset", preset]
            if v_bitrate_kbps > 0:
                args += ["-b:v", f"{v_bitrate_kbps}k"]
            else:
                # bitrate 未指定时使用 CRF（仅 x264/x265 有意义，其他编码器忽略也不会致命）
                if crf >= 0:
                    args += ["-crf", str(crf)]
            if pix_fmt:
                args += ["-pix_fmt", pix_fmt]
            if vf_parts:
                args += ["-vf", ",".join(vf_parts)]

            args += ["-c:a", acodec]
            if a_bitrate_kbps > 0 and acodec not in ("copy",):
                args += ["-b:a", f"{a_bitrate_kbps}k"]
            args += ["-shortest"]
        else:
            # 音频-only：不映射视频流
            args += ["-map", "0:a?", "-vn"]
            args += ["-c:a", acodec]
            if a_bitrate_kbps > 0 and acodec not in ("copy",):
                args += ["-b:a", f"{a_bitrate_kbps}k"]
            args += ["-shortest"]

        # faststart 只对 mp4/mov 系更有意义
        if output_container.lower() in ("mp4", "m4v", "mov"):
            args += ["-movflags", "+faststart"]

        return args

    def split_by_fixed(
        self,
        video_path: str,
        duration: float,
        transcode_opts: Optional[Dict[str, str]] = None,
        on_clip_created: Optional[Callable[[ClipInfo], None]] = None,
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

        # 预先探测一次，避免每个片段都重复 ffprobe
        video_has_stream = self.has_video_stream(video_path)
        output_container = (transcode_opts or {}).get("clip_container", "mp4").strip() or "mp4"

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
            clip_filename = f"{video_name}_clip_{i:03d}.{output_container}"
            clip_path = os.path.join(self.clips_dir, clip_filename)

            # 使用 FFmpeg 切分视频
            cmd_base = [
                ffmpeg_bin(),
                "-i", video_path,
                "-ss", str(start_time),
                "-to", str(end_time),
            ]

            transcode_args = self._build_transcode_args(
                has_video_stream=video_has_stream,
                output_container=output_container,
                opts=transcode_opts,
            )
            cmd = cmd_base + transcode_args + [
                "-y",  # 覆盖已存在的文件
                clip_path,
            ]

            try:
                logger.info(f"切分片段 {i+1}/{num_clips}: {start_time:.2f}s - {end_time:.2f}s")
                subprocess.run(cmd, check=True, capture_output=True)
                clips.append(ClipInfo(clip_path, start_time, end_time, clip_duration))
                if on_clip_created:
                    on_clip_created(clips[-1])
            except subprocess.CalledProcessError as e:
                logger.error(f"切分片段失败: {e.stderr.decode()}")
                raise RuntimeError(f"切分片段失败: {str(e)}")

        logger.info(f"固定时长切分完成: {len(clips)} 个片段")
        return clips

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
                scene_manager.detect_scenes(video, callback=frame_callback, show_progress=True)
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
            item = shot_queue.get()
            if item is _SENTINEL:
                break
            if max_shots is not None and shot_count >= int(max_shots):
                continue
            item["shot_id"] = shot_count
            yield item
            shot_count += 1

        if detect_error:
            raise detect_error[0]
        thread.join()

    def split_by_hybrid(
        self,
        video_path: str,
        threshold: float = 30.0,
        min_scene_len: int = 30,
        max_segment_sec: float = 60.0,
        chunk_sec: float = 10.0,
        transcode_opts: Optional[Dict[str, str]] = None,
        on_clip_created: Optional[Callable[[ClipInfo], None]] = None,
    ) -> List[ClipInfo]:
        """
        混合切分：先做镜头识别；若某镜头时长超过 max_segment_sec，再按 chunk_sec 强制切段。

        Args:
            max_segment_sec: 单镜头允许的最长秒数，超过则拆分
            chunk_sec: 超长镜头的切段步长（通常与「固定分割时长」一致）
        """
        if max_segment_sec <= 0:
            raise ValueError(f"混合模式最大镜头时长必须大于 0: {max_segment_sec}")

        video_has_stream = self.has_video_stream(video_path)
        output_container = (transcode_opts or {}).get("clip_container", "mp4").strip() or "mp4"

        logger.info(
            f"混合切分: 视频={video_path}, threshold={threshold}, min_scene_len={min_scene_len}, "
            f"max_segment_sec={max_segment_sec}, chunk_sec={chunk_sec}"
        )

        clips: List[ClipInfo] = []
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        clip_idx = 0

        for shot in self.detect_shots_stream(
            video_path,
            mode="adaptive",
            adaptive_threshold=threshold,
            adaptive_min_scene_len=min_scene_len,
        ):
            shot_start = float(shot["start"])
            shot_end = float(shot["end"])
            expanded = self._expand_long_scene_ranges(
                shot_start, shot_end, max_segment_sec, chunk_sec
            )
            for start_time, end_time in expanded:
                clip_duration = end_time - start_time
                clip_filename = f"{video_name}_hybrid_{clip_idx:04d}.{output_container}"
                clip_path = os.path.join(self.clips_dir, clip_filename)

                cmd = [ffmpeg_bin(), "-i", video_path, "-ss", str(start_time), "-to", str(end_time)]
                cmd += self._build_transcode_args(
                    has_video_stream=video_has_stream,
                    output_container=output_container,
                    opts=transcode_opts,
                )
                cmd += ["-y", clip_path]

                try:
                    logger.info(f"混合切分片段 {clip_idx+1}: {start_time:.2f}s - {end_time:.2f}s")
                    subprocess.run(cmd, check=True, capture_output=True)
                    clips.append(ClipInfo(clip_path, start_time, end_time, clip_duration))
                    if on_clip_created:
                        on_clip_created(clips[-1])
                    clip_idx += 1
                except subprocess.CalledProcessError as e:
                    logger.error(f"混合切分失败: {e.stderr.decode()}")
                    raise RuntimeError(f"混合切分失败: {str(e)}")

        logger.info(f"混合切分完成: {len(clips)} 个片段")
        return clips

    def split_by_scene(
        self,
        video_path: str,
        threshold: float = 30.0,
        min_scene_len: int = 30,
        transcode_opts: Optional[Dict[str, str]] = None,
        on_clip_created: Optional[Callable[[ClipInfo], None]] = None,
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

        # 预先探测一次，避免在每个场景片段都重复 ffprobe
        video_has_stream = self.has_video_stream(video_path)
        output_container = (transcode_opts or {}).get("clip_container", "mp4").strip() or "mp4"

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

        clips = []
        video_name = os.path.splitext(os.path.basename(video_path))[0]
        shot_count = 0

        for shot in self.detect_shots_stream(
            video_path,
            mode="adaptive",
            adaptive_threshold=threshold_value,
            adaptive_min_scene_len=min_scene_len_value,
        ):
            start_time = float(shot["start"])
            end_time = float(shot["end"])
            clip_duration = end_time - start_time

            # 生成片段文件路径
            clip_filename = f"{video_name}_scene_{shot_count:03d}.{output_container}"
            clip_path = os.path.join(self.clips_dir, clip_filename)

            # 使用 FFmpeg 切分视频
            cmd = [ffmpeg_bin(), "-i", video_path, "-ss", str(start_time), "-to", str(end_time)]
            cmd += self._build_transcode_args(
                has_video_stream=video_has_stream,
                output_container=output_container,
                opts=transcode_opts,
            )
            cmd += ["-y", clip_path]

            try:
                logger.info(f"切分场景 {shot_count+1}: {start_time:.2f}s - {end_time:.2f}s")
                subprocess.run(cmd, check=True, capture_output=True)
                clips.append(ClipInfo(clip_path, start_time, end_time, clip_duration))
                if on_clip_created:
                    on_clip_created(clips[-1])
                shot_count += 1
            except subprocess.CalledProcessError as e:
                logger.error(f"切分场景失败: {e.stderr.decode()}")
                raise RuntimeError(f"切分场景失败: {str(e)}")

        if not clips:
            logger.warning("未检测到场景切换，返回整个视频作为一个片段")
            total_duration = self.get_video_duration(video_path)
            clip_path = os.path.join(self.clips_dir, f"{video_name}.{output_container}")
            if not os.path.exists(clip_path):
                cmd = [ffmpeg_bin(), "-i", video_path]
                cmd += self._build_transcode_args(
                    has_video_stream=video_has_stream,
                    output_container=output_container,
                    opts=transcode_opts,
                )
                cmd += ["-y", clip_path]
                try:
                    subprocess.run(cmd, check=True, capture_output=True)
                    logger.info(f"整段视频已编码生成到 clips 目录: {clip_path}")
                except subprocess.CalledProcessError as e:
                    logger.error(f"编码视频失败: {e.stderr.decode()}")
                    raise RuntimeError(f"编码视频失败: {str(e)}")
            fallback_clip = ClipInfo(clip_path, 0, total_duration, total_duration)
            if on_clip_created:
                on_clip_created(fallback_clip)
            return [fallback_clip]

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

        # 创建帧存储目录
        clip_name = os.path.splitext(os.path.basename(clip_path))[0]
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
