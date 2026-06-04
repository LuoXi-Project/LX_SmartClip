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


def _notify_split_progress(
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


class VideoSplitter:
    """视频切分器 - 支持镜头识别、固定时长与混合（镜头 + 超长强制切段）切分"""

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

    @staticmethod
    def _parse_bool(val: Optional[str], default: bool = False) -> bool:
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        s = str(val).strip().lower()
        return s in {"1", "true", "yes", "y", "on", "t"}

    def _probe_keyframe_times(self, video_path: str) -> List[float]:
        """
        探测 v:0 的关键帧 pts_time 列表（秒），用于 -c copy 时对齐切点。

        说明：不同封装/编码器的 keyframe 输出格式可能不同，这里做了两段式兜底。
        """
        # 尽量只输出关键帧，避免 show_frames 产生海量输出
        cmd1 = [
            ffprobe_bin(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-skip_frame",
            "nokey",
            "-show_entries",
            "frame=pts_time",
            "-of",
            "csv=p=0",
            video_path,
        ]
        try:
            p1 = subprocess.run(cmd1, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3600)
            text = (p1.stdout.decode(errors="replace") or "").strip()
            out: List[float] = []
            if text:
                for line in text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(float(line))
                    except Exception:
                        continue
            if out:
                # 去重 + 排序
                return sorted(set(out))
        except Exception:
            # 走兜底
            pass

        # 兜底：输出 key_frame 与 pts_time，再在 Python 过滤（可能更慢，但仅在 cmd1 失效时触发）
        cmd2 = [
            ffprobe_bin(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "frame=key_frame,pts_time",
            "-of",
            "csv=p=0",
            video_path,
        ]
        p2 = subprocess.run(cmd2, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3600)
        out2: List[float] = []
        text2 = (p2.stdout.decode(errors="replace") or "").strip()
        if not text2:
            return []
        # csv=p=0 下每行形如：key_frame,pts_time
        for line in text2.splitlines():
            parts = [x.strip() for x in line.split(",")]
            if len(parts) < 2:
                continue
            k, pts = parts[0], parts[1]
            if k not in {"1", "1.0", "true"}:
                continue
            try:
                out2.append(float(pts))
            except Exception:
                continue
        return sorted(set(out2))

    def _get_keyframe_times_cached(self, video_path: str) -> List[float]:
        if video_path in self._keyframe_cache:
            return self._keyframe_cache[video_path]
        times = self._probe_keyframe_times(video_path)
        self._keyframe_cache[video_path] = times
        return times

    @staticmethod
    def _adjust_range_to_keyframes(
        keyframes: List[float],
        start_time: float,
        end_time: float,
    ) -> Tuple[float, float]:
        """
        让 (start_time, end_time) 以关键帧为边界（用于 -c copy）。
        规则：start 向下取前一个关键帧；end 优先取后一个关键帧（若不存在则保持原 end）。
        """
        if not keyframes:
            return start_time, end_time

        # 确保 start/end 非负
        start_time = max(0.0, float(start_time))
        end_time = max(0.0, float(end_time))

        if end_time <= start_time + 1e-6:
            return start_time, end_time

        # start: <= start 的最大关键帧
        i = bisect.bisect_right(keyframes, start_time) - 1
        start_adj = keyframes[i] if i >= 0 else keyframes[0]

        # end: >= end 的最小关键帧；若不存在，退回原 end
        j = bisect.bisect_left(keyframes, end_time)
        end_adj = keyframes[j] if j < len(keyframes) else end_time

        # 保底，避免 end_adj 小于等于 start_adj 导致 -t<=0
        if end_adj <= start_adj + 1e-6:
            end_adj = start_adj + (end_time - start_time)
        return float(start_adj), float(end_adj)

    def _cut_ranges_parallel(
        self,
        video_path: str,
        ranges: List[Tuple[float, float]],
        *,
        transcode_opts: Optional[Dict[str, str]] = None,
        on_clip_created: Optional[Callable[[ClipInfo], None]] = None,
        on_progress: Optional[SplitProgressFn] = None,
        split_mode: str = "",
        should_stop: Optional[Callable[[], bool]] = None,
        # 命名前缀 & 序号格式
        name_prefix: str,
        index_width: int = 3,
        shots_detected: int = 0,
    ) -> List[ClipInfo]:
        """
        通用切分管线：给定一组 (start, end) 区间，使用 ffmpeg 并行切分。

        统一支持：
        - cut_mode fast/precise（-ss 放置位置）
        - stream_copy（视频流 copy 时关键帧对齐 + 关键帧缓存）
        - quiet_split（压低日志和 ffmpeg 输出）
        - split_max_workers / ffmpeg_threads_per_job 等性能参数
        """
        if not ranges:
            return []

        _notify_split_progress(
            on_progress,
            phase="planning",
            split_mode=split_mode,
            shots_detected=shots_detected,
            segments_planned=len(ranges),
            clips_ready=0,
        )
        _notify_split_progress(
            on_progress,
            phase="cutting",
            split_mode=split_mode,
            shots_detected=shots_detected,
            segments_planned=len(ranges),
            clips_ready=0,
        )

        opts = dict(transcode_opts or {})

        # ===== 基础配置 =====
        video_has_stream = self.has_video_stream(video_path)
        output_container = opts.get("clip_container", "mp4").strip() or "mp4"
        # 切片落在 storage/<素材id>/clips/，文件名不再带主视频 stem 前缀（如 hybrid_0000.mp4）

        # cut_mode
        cut_mode_val = (opts.get("cut_mode") or "fast").strip().lower()
        if cut_mode_val not in {"fast", "precise"}:
            cut_mode_val = "fast"

        # stream_copy（只控制视频）
        if "stream_copy" in opts:
            stream_copy_val = self._parse_bool(opts.get("stream_copy"), default=False)
        else:
            vcodec_cfg = (opts.get("clip_vcodec") or "").strip().lower()
            stream_copy_val = vcodec_cfg == "copy"

        # worker 数
        cfg_workers = str(opts.get("split_max_workers") or "").strip()
        if cfg_workers:
            try:
                max_workers = max(1, int(float(cfg_workers)))
            except Exception:
                max_workers = max(1, min(4, os.cpu_count() or 1))
        else:
            max_workers = max(1, min(4, os.cpu_count() or 1))

        # 日志/quiet
        quiet_split_val = self._parse_bool(opts.get("quiet_split"), default=True)
        ffmpeg_loglevel = str(opts.get("ffmpeg_loglevel") or "").strip()
        if not ffmpeg_loglevel:
            ffmpeg_loglevel = "error" if quiet_split_val else "warning"

        # ffmpeg 线程
        ffmpeg_threads = str(opts.get("ffmpeg_threads_per_job") or "").strip()
        if ffmpeg_threads:
            try:
                ffmpeg_threads_val = max(1, int(float(ffmpeg_threads)))
            except Exception:
                ffmpeg_threads_val = 1
        else:
            ffmpeg_threads_val = 1 if max_workers > 1 else 0

        # stream_copy 强制视频编码器为 copy；音频由 stream_copy_audio/clip_acodec 控制
        if stream_copy_val:
            opts["clip_vcodec"] = "copy"
            if self._parse_bool(opts.get("stream_copy_audio"), default=False):
                opts["clip_acodec"] = "copy"

        # 关键帧缓存（仅视频流 copy 时）
        keyframes: List[float] = []
        video_duration: Optional[float] = None
        if stream_copy_val and video_has_stream:
            keyframes = self._get_keyframe_times_cached(video_path)
            video_duration = self.get_video_duration(video_path)

        # 转码参数整体一次性构建
        transcode_args = self._build_transcode_args(
            has_video_stream=video_has_stream,
            output_container=output_container,
            opts=opts,
        )

        results_by_idx: Dict[int, ClipInfo] = {}
        futures = []
        clips_ready = 0

        def _run_one(idx: int, start_time: float, end_time: float, clip_path: str) -> Tuple[int, ClipInfo]:
            start_adj, end_adj = start_time, end_time
            if stream_copy_val and keyframes:
                start_adj, end_adj = self._adjust_range_to_keyframes(keyframes, start_time, end_time)
                if video_duration is not None:
                    end_adj = min(float(end_adj), float(video_duration))
                # stream copy 只能从关键帧切入，边界会偏移；显式记录便于排查“日志区间”和“落盘区间”不一致
                if abs(start_adj - start_time) > 1e-3 or abs(end_adj - end_time) > 1e-3:
                    logger.warning(
                        "stream_copy 关键帧对齐导致片段边界偏移 idx=%s 请求=[%.3f, %.3f] 实际=[%.3f, %.3f]",
                        idx,
                        start_time,
                        end_time,
                        start_adj,
                        end_adj,
                    )

            duration = max(0.0, float(end_adj - start_adj))
            if duration <= 1e-6:
                raise RuntimeError(f"切段时长过短（idx={idx}）: start={start_adj}, end={end_adj}")

            cmd: List[str] = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", ffmpeg_loglevel]
            if ffmpeg_threads_val > 0:
                cmd += ["-threads", str(ffmpeg_threads_val)]

            if cut_mode_val == "fast":
                cmd += ["-ss", str(start_adj), "-i", video_path, "-t", str(duration)]
            else:
                cmd += ["-i", video_path, "-ss", str(start_adj), "-t", str(duration)]

            cmd += transcode_args
            cmd += ["-y", clip_path]

            try:
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as e:
                err_tail = ""
                if getattr(e, "stderr", None):
                    try:
                        err_tail = e.stderr.decode(errors="replace")[-2000:]
                    except Exception:
                        err_tail = ""
                raise RuntimeError(f"切分失败（idx={idx}）: {err_tail or str(e)}")

            return idx, ClipInfo(clip_path, start_adj, end_adj, duration)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for idx, (st, ed) in enumerate(ranges):
                if should_stop and should_stop():
                    raise StopRequested("切分已停止")
                clip_filename = f"{name_prefix}_{idx:0{index_width}d}.{output_container}"
                clip_path = os.path.join(self.clips_dir, clip_filename)
                futures.append(executor.submit(_run_one, idx, float(st), float(ed), clip_path))
                if not quiet_split_val:
                    logger.info(f"提交切分片段 {name_prefix}#{idx}: {st:.2f}s - {ed:.2f}s")

            for fut in as_completed(futures):
                if should_stop and should_stop():
                    for pending in futures:
                        pending.cancel()
                    raise StopRequested("切分已停止")
                try:
                    idx_ret, clip_info = fut.result()
                    results_by_idx[idx_ret] = clip_info
                    clips_ready += 1
                    _notify_split_progress(
                        on_progress,
                        phase="cutting",
                        split_mode=split_mode,
                        shots_detected=shots_detected,
                        segments_planned=len(ranges),
                        clips_ready=clips_ready,
                    )
                    if on_clip_created:
                        on_clip_created(clip_info)
                except Exception:
                    for pending in futures:
                        pending.cancel()
                    raise

        total = len(results_by_idx)
        return [results_by_idx[i] for i in range(total)]

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
        gop = _to_int("clip_g", 0)
        keyint_min = _to_int("clip_keyint_min", 0)
        sc_threshold = _to_int("clip_sc_threshold", 0)
        fps = _to_float("clip_fps", 0.0)
        scale_w = _to_int("clip_scale_width", 0)
        scale_h = _to_int("clip_scale_height", 0)

        is_video_copy = vcodec.lower() == "copy"
        vf_parts: List[str] = []
        if not is_video_copy:
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
            if not is_video_copy:
                if vcodec in ("libx264", "libx265") and preset:
                    args += ["-preset", preset]
                # GOP/关键帧参数：对切点稳定性与 seek 行为有直接影响。
                # x264/x265 支持 keyint_min / sc_threshold；其他编码器只下发通用 g。
                if gop > 0:
                    args += ["-g", str(gop)]
                if vcodec in ("libx264", "libx265"):
                    if keyint_min > 0:
                        args += ["-keyint_min", str(keyint_min)]
                    # 保持 0 也应显式下发：用于关闭场景切换自动关键帧。
                    if sc_threshold >= 0:
                        args += ["-sc_threshold", str(sc_threshold)]
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
            else:
                # stream copy 与滤镜/像素格式/码率/CRF 等互斥，统一跳过避免 ffmpeg 报错。
                if scale_w > 0 or scale_h > 0 or (fps and fps > 0):
                    logger.warning("clip_vcodec=copy 时将忽略 clip_scale_* / clip_fps（stream copy 不支持滤镜）")
                if pix_fmt:
                    logger.warning("clip_vcodec=copy 时将忽略 clip_pix_fmt（stream copy 不支持像素格式转换）")

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

    def split_by_hybrid(
        self,
        video_path: str,
        threshold: float = 30.0,
        min_scene_len: int = 30,
        max_segment_sec: float = 60.0,
        chunk_sec: float = 10.0,
        transcode_opts: Optional[Dict[str, str]] = None,
        on_clip_created: Optional[Callable[[ClipInfo], None]] = None,
        on_progress: Optional[SplitProgressFn] = None,
        # 性能优化开关（优先从 transcode_opts 读取；此处保留参数以便直接调用时覆写）
        cut_mode: Optional[str] = None,
        stream_copy: Optional[bool] = None,
        max_workers: Optional[int] = None,
        quiet_split: Optional[bool] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> List[ClipInfo]:
        """
        混合切分：先做镜头识别；若某镜头时长超过 max_segment_sec，再按 chunk_sec 强制切段。

        Args:
            max_segment_sec: 单镜头允许的最长秒数，超过则拆分
            chunk_sec: 超长镜头的切段步长（通常与「固定分割时长」一致）
        """
        if max_segment_sec <= 0:
            raise ValueError(f"混合模式最大镜头时长必须大于 0: {max_segment_sec}")

        opts = dict(transcode_opts or {})

        # ===== 性能相关配置（尽量兼容现有 transcode_opts）
        # cut_mode：
        # - fast：-ss 放在 -i 前（快速寻址，适合提速；精度可在需要时通过切换 precise 处理）
        # - precise：-ss 放在 -i 后（更精确，但更慢）
        cut_mode_val = (cut_mode or opts.get("cut_mode") or "fast").strip().lower()
        if cut_mode_val not in {"fast", "precise"}:
            cut_mode_val = "fast"

        # stream_copy：
        # 1) 优先使用显式参数 stream_copy
        # 2) 否则从 opts 推断：clip_vcodec/clip_acodec 是否为 copy
        if stream_copy is None:
            # 支持 transcode_opts["stream_copy"] 显式开关；该开关用于控制“视频流是否 copy”
            if "stream_copy" in opts:
                stream_copy_val = self._parse_bool(opts.get("stream_copy"), default=False)
            else:
                # 兼容老配置：clip_vcodec == copy 即视为视频流 copy
                vcodec = (opts.get("clip_vcodec") or "").strip().lower()
                stream_copy_val = vcodec == "copy"
        else:
            stream_copy_val = bool(stream_copy)

        # max_workers：并行 ffmpeg 作业数
        if max_workers is None:
            cfg = str(opts.get("split_max_workers") or "").strip()
            if cfg:
                try:
                    max_workers_val = max(1, int(float(cfg)))
                except Exception:
                    max_workers_val = max(1, min(4, os.cpu_count() or 1))
            else:
                max_workers_val = max(1, min(4, os.cpu_count() or 1))
        else:
            max_workers_val = max(1, int(max_workers))

        # quiet_split：降低 Python 侧日志，减少 stdout/stderr 输出开销
        if quiet_split is None:
            quiet_split_val = self._parse_bool(opts.get("quiet_split"), default=True)
        else:
            quiet_split_val = bool(quiet_split)

        ffmpeg_loglevel = str(opts.get("ffmpeg_loglevel") or "").strip()
        if not ffmpeg_loglevel:
            ffmpeg_loglevel = "error" if quiet_split_val else "warning"

        # ffmpeg 线程：并行场景下建议每个 ffmpeg 限制线程，避免 CPU 过度争用
        ffmpeg_threads = str(opts.get("ffmpeg_threads_per_job") or "").strip()
        if ffmpeg_threads:
            try:
                ffmpeg_threads_val = max(1, int(float(ffmpeg_threads)))
            except Exception:
                ffmpeg_threads_val = 1
        else:
            ffmpeg_threads_val = 1 if max_workers_val > 1 else 0  # 0 表示不显式设置

        video_has_stream = self.has_video_stream(video_path)
        output_container = opts.get("clip_container", "mp4").strip() or "mp4"

        # stream_copy 时补齐编码器为 copy（除非用户显式指定了其他编码器）
        if stream_copy_val:
            # stream_copy_val 只表示“视频流 copy”，因此这里强制 clip_vcodec=copy
            opts["clip_vcodec"] = "copy"
            # 音频是否也 copy：默认沿用 opts（通常由 clip_acodec 决定）
            if self._parse_bool(opts.get("stream_copy_audio"), default=False):
                opts["clip_acodec"] = "copy"

        logger.info(
            f"混合切分: 视频={video_path}, threshold={threshold}, min_scene_len={min_scene_len}, "
            f"max_segment_sec={max_segment_sec}, chunk_sec={chunk_sec}, cut_mode={cut_mode_val}, "
            f"stream_copy={stream_copy_val}, workers={max_workers_val}"
        )

        # keyframe cache：仅在 -c copy 时对齐切点
        keyframes: List[float] = []
        video_duration: Optional[float] = None
        if stream_copy_val and video_has_stream:
            keyframes = self._get_keyframe_times_cached(video_path)
            video_duration = self.get_video_duration(video_path)

        # 转码参数对所有片段一致，预先构建减少重复开销
        transcode_args = self._build_transcode_args(
            has_video_stream=video_has_stream,
            output_container=output_container,
            opts=opts,
        )

        clips: List[ClipInfo] = []
        results_by_idx: Dict[int, ClipInfo] = {}

        futures = []
        clip_idx = 0
        shots_detected = 0
        segments_planned = 0
        clips_ready = 0

        def _run_one(idx: int, start_time: float, end_time: float, clip_path: str) -> Tuple[int, ClipInfo]:
            # 对齐关键帧（仅 stream copy）
            start_adj, end_adj = start_time, end_time
            if stream_copy_val and keyframes:
                start_adj, end_adj = self._adjust_range_to_keyframes(keyframes, start_time, end_time)
                if video_duration is not None:
                    end_adj = min(float(end_adj), float(video_duration))
                # stream copy 只能从关键帧切入，边界会偏移；显式记录便于排查“日志区间”和“落盘区间”不一致
                if abs(start_adj - start_time) > 1e-3 or abs(end_adj - end_time) > 1e-3:
                    logger.warning(
                        "stream_copy 关键帧对齐导致片段边界偏移 idx=%s 请求=[%.3f, %.3f] 实际=[%.3f, %.3f]",
                        idx,
                        start_time,
                        end_time,
                        start_adj,
                        end_adj,
                    )

            duration = max(0.0, float(end_adj - start_adj))
            if duration <= 1e-6:
                raise RuntimeError(f"切段时长过短（idx={idx}）: start={start_adj}, end={end_adj}")

            cmd: List[str] = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", ffmpeg_loglevel]
            if ffmpeg_threads_val > 0:
                cmd += ["-threads", str(ffmpeg_threads_val)]

            # 快速/精确切割：切换 -ss 放置位置
            if cut_mode_val == "fast":
                cmd += ["-ss", str(start_adj), "-i", video_path, "-t", str(duration)]
            else:
                cmd += ["-i", video_path, "-ss", str(start_adj), "-t", str(duration)]

            cmd += transcode_args
            cmd += ["-y", clip_path]

            stderr = subprocess.PIPE  # 只捕获 error 级别输出，便于定位失败原因
            stdout = subprocess.DEVNULL
            try:
                subprocess.run(cmd, check=True, stdout=stdout, stderr=stderr)
            except subprocess.CalledProcessError as e:
                err_tail = ""
                if getattr(e, "stderr", None):
                    try:
                        err_tail = e.stderr.decode(errors="replace")[-2000:]
                    except Exception:
                        err_tail = ""
                raise RuntimeError(f"混合切分失败（idx={idx}）: {err_tail or str(e)}")

            return idx, ClipInfo(clip_path, start_adj, end_adj, duration)

        with ThreadPoolExecutor(max_workers=max_workers_val) as executor:
            for shot in self.detect_shots_stream(
                video_path,
                mode="adaptive",
                adaptive_threshold=threshold,
                adaptive_min_scene_len=min_scene_len,
                show_progress=not quiet_split_val,
                should_stop=should_stop,
                on_progress=on_progress,
                split_mode="hybrid",
            ):
                if should_stop and should_stop():
                    raise StopRequested("混合切分已停止")
                shots_detected += 1
                shot_start = float(shot["start"])
                shot_end = float(shot["end"])
                expanded = self._expand_long_scene_ranges(shot_start, shot_end, max_segment_sec, chunk_sec)
                segments_planned += len(expanded)
                secondary = len(expanded) > 1
                _notify_split_progress(
                    on_progress,
                    phase="planning" if secondary else "detecting",
                    split_mode="hybrid",
                    shots_detected=shots_detected,
                    segments_planned=segments_planned,
                    clips_ready=clips_ready,
                )
                for start_time, end_time in expanded:
                    if should_stop and should_stop():
                        raise StopRequested("混合切分已停止")
                    clip_filename = f"hybrid_{clip_idx:04d}.{output_container}"
                    clip_path = os.path.join(self.clips_dir, clip_filename)
                    futures.append(
                        executor.submit(_run_one, clip_idx, start_time, end_time, clip_path)
                    )
                    if not quiet_split_val:
                        logger.info(f"提交混合切分片段 {clip_idx+1}: {start_time:.2f}s - {end_time:.2f}s")
                    clip_idx += 1

            if segments_planned > 0:
                _notify_split_progress(
                    on_progress,
                    phase="cutting",
                    split_mode="hybrid",
                    shots_detected=shots_detected,
                    segments_planned=segments_planned,
                    clips_ready=clips_ready,
                )

            # 收集结果（尽早触发 on_clip_created 以保持流水线）
            for fut in as_completed(futures):
                if should_stop and should_stop():
                    for pending in futures:
                        pending.cancel()
                    raise StopRequested("混合切分已停止")
                try:
                    idx_ret, clip_info = fut.result()
                    results_by_idx[idx_ret] = clip_info
                    clips_ready += 1
                    _notify_split_progress(
                        on_progress,
                        phase="cutting",
                        split_mode="hybrid",
                        shots_detected=shots_detected,
                        segments_planned=segments_planned,
                        clips_ready=clips_ready,
                    )
                    if on_clip_created:
                        on_clip_created(clip_info)
                except Exception:
                    # 避免等待其他 ffmpeg 作业无谓继续，直接抛错交由上层中断
                    for pending in futures:
                        pending.cancel()
                    raise

        # 按 idx 排序回填 clips 列表
        total_clips = len(results_by_idx)
        clips = [results_by_idx[i] for i in range(total_clips)]
        logger.info(f"混合切分完成: {len(clips)} 个片段")
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
