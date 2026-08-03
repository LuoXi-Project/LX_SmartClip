from __future__ import annotations

import json
import logging
import os
import subprocess
from math import gcd
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.utils.bin_paths import ffprobe_bin

logger = logging.getLogger(__name__)


def _parse_frame_rate(raw: str) -> Optional[Tuple[int, int]]:
    """把 ffprobe 的 r_frame_rate（如 '30/1'、'30000/1001'）约分成 (num, den)；非法返回 None。

    约分后比较，规避 '30/1' 与 '60/2' 这类同值不同写法导致的误判。
    """
    if not raw:
        return None
    text = raw.strip().splitlines()[0].strip() if raw.strip() else ""
    if "/" not in text:
        return None
    try:
        n_str, d_str = text.split("/", 1)
        num, den = int(n_str), int(d_str)
    except Exception:
        return None
    if den <= 0 or num < 0:
        return None
    g = gcd(num, den) or 1
    return (num // g, den // g)


# ---------------------------------------------------------------------------
# 进程内 probe 缓存：单次合成任务（如口播快剪 80 段）会对同一批 seg 文件
# 反复 probe（composer uniform 检查、xfade canvas、xfade 每段又 probe 两三次），
# 合计几百次 ffprobe 子进程。缓存以 (path, mtime, size) 为键，跨任务通过
# clear_probe_cache() 清理，避免脏读。
# ---------------------------------------------------------------------------
_PROBE_CACHE: Dict[Tuple[str, float, int], Dict[str, Any]] = {}
_PROBE_CACHE_CAP = 512


def _probe_cache_key(path: str) -> Optional[Tuple[str, float, int]]:
    """以路径+mtime+size 作为缓存键；取不到 stat 时返回 None（不缓存）。"""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (path, st.st_mtime, st.st_size)


def _probe_cache_get(path: str, field: str) -> Tuple[bool, Any]:
    key = _probe_cache_key(path)
    if key is None:
        return False, None
    bucket = _PROBE_CACHE.get(key)
    if bucket is None or field not in bucket:
        return False, None
    return True, bucket[field]


def _probe_cache_set(path: str, field: str, value: Any) -> None:
    key = _probe_cache_key(path)
    if key is None:
        return
    # 简单容量上限：超出时整体清空（合成任务内总量可控，无需精细 LRU）。
    if len(_PROBE_CACHE) >= _PROBE_CACHE_CAP:
        _PROBE_CACHE.clear()
    bucket = _PROBE_CACHE.setdefault(key, {})
    bucket[field] = value


def clear_probe_cache() -> None:
    """清空进程内 probe 缓存（合成任务结束后调用）。"""
    _PROBE_CACHE.clear()


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
    hit, cached = _probe_cache_get(path, "duration")
    if hit:
        return float(cached)  # type: ignore[arg-type]

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
        val = float(raw or 0.0)
        _probe_cache_set(path, "duration", val)
        return val
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
    hit, cached = _probe_cache_get(path, "dims")
    if hit:
        return cached  # type: ignore[return-value]
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
            _probe_cache_set(path, "dims", (w, h))
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
    hit, cached = _probe_cache_get(path, "sr")
    if hit:
        return int(cached)  # type: ignore[arg-type]
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
        val = int(float(raw))
        _probe_cache_set(path, "sr", val)
        return val
    except Exception:
        log.warning("ffprobe 探测音频采样率失败，回退 %s: %s", default, path)
        return default


def probe_video_frame_rate(
    path: str,
    *,
    timeout: int = 600,
    logger_: Optional[logging.Logger] = None,
) -> Optional[Tuple[int, int]]:
    """探测主视频流帧率，返回约分后的 (num, den)；失败返回 None。

    用于判断多段是否「帧率/时间基准一致」：concat demuxer 与 -c copy 拼接都要求
    各段 time_base 一致，否则段边界会吐出乱序 DTS → ffmpeg 丢帧 + 复制上一帧，
    表现为「部分段画面卡死、声音正常」。用 r_frame_rate（基础帧率）约分后比较。
    """
    log = logger_ or logger
    hit, cached = _probe_cache_get(path, "fr")
    if hit:
        return cached  # type: ignore[return-value]
    probe = _run_ffprobe(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        timeout=timeout,
    )
    raw = (probe.stdout.decode(errors="replace") or "").strip()
    val = _parse_frame_rate(raw)
    if val is None:
        log.warning("ffprobe 探测视频帧率失败: %s", path)
    _probe_cache_set(path, "fr", val)
    return val


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


def has_audio_stream(
    path: str,
    *,
    timeout: int = 600,
    logger_: Optional[logging.Logger] = None,
) -> bool:
    """
    判断媒体是否包含音频流（判断 a:0 的 codec_type 是否为 audio）。

    失败时返回 False（与 has_video_stream 一致）。
    """
    log = logger_ or logger
    probe = _run_ffprobe(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        timeout=timeout,
    )

    try:
        return (probe.stdout.decode(errors="replace") or "").strip() == "audio"
    except Exception:
        log.warning("ffprobe 检查音频流失败，返回 False: %s", path)
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
    - 进程内缓存：同一源片的关键帧扫描成本较高（-skip_frame nokey 全片扫描），
      在单次合成任务内对同一文件只扫一次。
    """
    log = logger_ or logger
    hit, cached = _probe_cache_get(path, "keyframes")
    if hit:
        return list(cached)  # type: ignore[arg-type]
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
        _probe_cache_set(path, "keyframes", out)
        return out
    except Exception:
        log.warning("ffprobe 探测关键帧失败，回退为空: %s", path)
        return []

