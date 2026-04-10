from __future__ import annotations

import json
import logging
import subprocess
from typing import List, Optional, Sequence, Tuple

from app.utils.bin_paths import ffprobe_bin

logger = logging.getLogger(__name__)


def _run_ffprobe(
    args: Sequence[str],
    *,
    timeout: int = 600,
) -> subprocess.CompletedProcess:
    """
    统一调用 ffprobe，返回原始 CompletedProcess 以便上层决定如何处理失败。
    """
    return subprocess.run(
        list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def probe_duration(
    path: str,
    *,
    timeout: int = 600,
    on_error: str = "zero",
    log_stderr_tail: int = 2000,
    log_on_failure: bool = False,
) -> float:
    """
    探测媒体时长（秒）。

    Args:
        path: 媒体文件路径
        timeout: ffprobe 超时时间（秒）
        on_error:
          - "zero": 失败返回 0.0（用于最大限度兼容旧逻辑）
          - "raise": 失败抛出 RuntimeError
        log_stderr_tail: 错误日志截断长度
    """
    probe = _run_ffprobe(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        timeout=timeout,
    )

    raw = (probe.stdout.decode(errors="replace") or "").strip()
    try:
        # 有些封装会返回空字符串或非数值，这里用 float 统一兜底
        return float(raw or 0.0)
    except Exception:
        if on_error == "raise":
            tail = probe.stderr.decode(errors="replace")[-log_stderr_tail:]
            raise RuntimeError(f"ffprobe 探测时长失败: {path}\nstderr: {tail}")
        if log_on_failure:
            logger.warning("ffprobe 时长探测失败: %s", path)
        return 0.0


def probe_video_dimensions(
    path: str,
    *,
    timeout: int = 600,
    default: Tuple[int, int] = (1920, 1080),
    logger_: Optional[logging.Logger] = None,
) -> Tuple[int, int]:
    """
    探测视频尺寸（width, height）。

    若探测失败则返回 default，避免上层依赖尺寸导致整条流水线失败。
    """
    log = logger_ or logger
    probe = _run_ffprobe(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            path,
        ],
        timeout=timeout,
    )

    text = (probe.stdout.decode(errors="replace") or "").strip()
    if not text:
        log.warning("ffprobe 探测视频尺寸失败，回退为 %s（空输出）: %s", default, path)
        return default

    try:
        w_str, h_str = [x.strip() for x in text.replace("\n", "").split(",", 1)]
        w = int(float(w_str))
        h = int(float(h_str))
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass

    log.warning("ffprobe 探测视频尺寸失败，回退为 %s: %s", default, path)
    return default


def probe_audio_sample_rate(
    path: str,
    *,
    timeout: int = 600,
    default: int = 48000,
    logger_: Optional[logging.Logger] = None,
) -> int:
    """探测主音频流采样率（Hz）；失败或无音轨时返回 default。"""
    log = logger_ or logger
    probe = _run_ffprobe(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        timeout=timeout,
    )
    raw = (probe.stdout.decode(errors="replace") or "").strip()
    try:
        return int(float(raw))
    except Exception:
        log.warning("ffprobe 探测音频采样率失败，回退 %s: %s", default, path)
        return default


def has_video_stream(
    path: str,
    *,
    timeout: int = 600,
    logger_: Optional[logging.Logger] = None,
) -> bool:
    """
    判断媒体是否包含视频流（判断 v:0 的 codec_type 是否为 video）。

    失败时返回 False（与旧逻辑一致）。
    """
    log = logger_ or logger
    probe = _run_ffprobe(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        timeout=timeout,
    )

    try:
        return (probe.stdout.decode(errors="replace") or "").strip() == "video"
    except Exception:
        # 理论上不会走到这里，但保持兼容
        log.warning("ffprobe 检查视频流失败，返回 False: %s", path)
        return False


def probe_keyframes_times(
    path: str,
    *,
    timeout: int = 600,
    logger_: Optional[logging.Logger] = None,
) -> List[float]:
    """
    探测视频关键帧时间点（秒）。

    说明：
    - 用于“是否可安全 stream copy 裁剪”的快速判断（对齐关键帧时，-c copy 的切点更可靠）。
    - 失败时返回空列表（上层可回退到重编码或宽松策略）。
    """
    log = logger_ or logger
    probe = _run_ffprobe(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-skip_frame",
            "nokey",
            "-show_frames",
            "-show_entries",
            "frame=best_effort_timestamp_time,key_frame",
            "-of",
            "json",
            path,
        ],
        timeout=timeout,
    )

    try:
        data = json.loads((probe.stdout.decode(errors="replace") or "").strip() or "{}")
        frames = data.get("frames") or []
        out: List[float] = []
        for f in frames:
            # ffprobe 在 skip_frame=nokey 下理论上只返回关键帧，但这里仍保守判断一下
            if int(f.get("key_frame") or 0) != 1:
                continue
            ts = f.get("best_effort_timestamp_time")
            if ts is None:
                continue
            try:
                out.append(float(ts))
            except Exception:
                continue
        out.sort()
        return out
    except Exception:
        log.warning("ffprobe 探测关键帧失败，回退为空: %s", path)
        return []

