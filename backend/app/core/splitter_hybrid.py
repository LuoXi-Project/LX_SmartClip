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


class SplitterHybridMixin:
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
