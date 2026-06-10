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


class SplitterCutMixin:
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
