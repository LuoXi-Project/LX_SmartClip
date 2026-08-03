"""素材代理（proxy）：高分辨率原片的 1080p 降采样副本，用于混剪合成提速。

背景：
  混剪合成时，segment_render 会从原片（src_video_path）按 src_start/src_end 裁剪。
  若原片是 4K/1440p，合成单链要逐帧解码全分辨率 + 缩放到 1080p（解码是物理瓶颈，
  实测占合成 60%+ 时间）。

  代理思路：合成前为每个 >目标分辨率 的原片生成一份 1080p 副本，合成时用代理替代
  原片，使合成只解码 1080p。代理保持与原片相同的时间轴（只降分辨率、不改 fps、不裁剪），
  故 src_start/src_end 可直接复用。

  生命周期：代理文件放 storage/<video_id>/videos/ 内，随素材删除（rmtree）自动清理。
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Dict, Optional

from app.utils.bin_paths import ffmpeg_bin
from app.utils.ffprobe_utils import probe_duration, probe_video_dimensions
from app.utils.paths import ensure_storage_subpath

logger = logging.getLogger(__name__)

# 代理文件固定名（目录已含 video_id，文件名不重复 UUID）。
PROXY_FILENAME = "proxy_1080p.mp4"


def _proxy_enabled_from_opts(opts: Dict[str, str]) -> bool:
    """代理功能是否启用。config.proxy_enabled（默认 on）。"""
    raw = str(opts.get("proxy_enabled") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    return True  # 默认启用


def _proxy_max_height_from_opts(opts: Dict[str, str]) -> int:
    """代理目标高度（像素）。config.proxy_max_height（默认 1080）。"""
    raw = str(opts.get("proxy_max_height") or "").strip()
    try:
        v = int(float(raw))
        return max(360, v)  # 下限 360p，过小无意义
    except Exception:
        return 1080


def _needs_proxy(src_path: str, max_height: int) -> bool:
    """原片高度 > max_height 时才需要代理（≤目标分辨率的原片直接用，无需代理）。"""
    w, h = probe_video_dimensions(src_path, default=(0, 0), logger_=logger)
    return h > max_height > 0


def _proxy_path_for(video_id: str) -> str:
    """代理文件路径：storage/<video_id>/videos/proxy_1080p.mp4。"""
    return os.path.join(ensure_storage_subpath(video_id, "videos"), PROXY_FILENAME)


def _proxy_valid(proxy_path: str, ref_duration: float) -> bool:
    """代理是否可用：文件存在、非空、时长与原片基本一致（时间轴对齐校验）。

    时长校验是时间轴对齐的安全守门：若代理与原片时长差异过大（如生成中断/损坏），
    绝不能复用（src_start/src_end 会错位），必须重新生成。
    """
    if not os.path.isfile(proxy_path):
        return False
    if os.path.getsize(proxy_path) <= 0:
        return False
    if ref_duration <= 0.05:
        return True  # 无参考时长则只校验文件存在性
    pd = float(probe_duration(proxy_path, log_on_failure=True) or 0.0)
    if pd <= 0.05:
        return False
    # 代理为整体重编码（不裁剪），时长应与原片基本一致；容忍 0.5s 或 1%。
    tol = max(0.5, ref_duration * 0.01)
    return abs(pd - ref_duration) <= tol


def generate_proxy(
    *,
    src_path: str,
    out_path: str,
    max_height: int,
    prefer_gpu: bool = True,
    on_progress: Optional[callable] = None,
) -> str:
    """生成单个素材的 1080p（或 max_height）代理副本。

    关键约束（保证时间轴与原片逐帧对齐，src_start/src_end 可复用）：
    - 整体重编码，不用 -ss/-t 裁剪；
    - 不改 fps（不加 fps 滤镜）；
    - 仅 scale 降采样 + format=yuv420p。

    用 NVENC 快编码（代理是中间产物，画质足够即可，合成后丢弃）；NVENC 失败回退 libx264。
    on_progress(percent: float)：可选进度回调（0~100）。
    """
    vf = (
        f"scale=-2:{max_height}:force_original_aspect_ratio=decrease:"
        f"force_divisible_by=2,format=yuv420p"
    )
    audio_args = ["-c:a", "aac", "-b:a", "128k"]  # 音频统一为 aac，与合成管线一致

    codecs = _pick_proxy_vcodecs(prefer_gpu)
    last_err: Optional[Exception] = None
    for vcodec, extra in codecs:
        cmd = [
            ffmpeg_bin(), "-y",
            "-i", src_path,
            "-vf", vf,
            "-c:v", vcodec, *extra,
            *audio_args,
            "-movflags", "+faststart",
            out_path,
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode == 0:
            if on_progress:
                on_progress(100.0)
            return out_path
        last_err = RuntimeError(
            f"代理生成[{vcodec}]失败: {src_path}\nstderr: {proc.stderr.decode(errors='replace')[-1500:]}"
        )
        logger.warning("代理生成[%s]失败，尝试下一档: %s", vcodec, src_path)
        # 清理可能的半成品，避免 _proxy_valid 误判
        try:
            if os.path.isfile(out_path):
                os.remove(out_path)
        except OSError:
            pass
    raise last_err if last_err else RuntimeError(f"代理生成失败: {src_path}")


def _pick_proxy_vcodecs(prefer_gpu: bool):
    """代理编码器候选档：优先 NVENC（快），回退 libx264（稳）。"""
    if prefer_gpu:
        return [
            ("h264_nvenc", ["-preset", "p4", "-rc", "vbr", "-cq", "24", "-g", "48"]),
            ("libx264", ["-preset", "veryfast", "-crf", "20", "-g", "48"]),
        ]
    return [("libx264", ["-preset", "veryfast", "-crf", "20", "-g", "48"])]


def ensure_proxies_for_clips(
    rows,
    opts: Optional[Dict[str, str]] = None,
    *,
    prefer_gpu: bool = True,
    on_progress: Optional[callable] = None,
) -> Dict[str, str]:
    """为混剪涉及的素材批量生成代理，返回 {video_id: proxy_path}（含已存在的代理）。

    rows：_load_clip_rows_with_raw_fallback 的结果（每行含 id/video_id/video_file_path）。
    仅对「启用代理 + 原片高度 > max_height」的素材生成；其余跳过。
    任一素材代理生成失败 → 该素材不进返回表（调用方会用原片，不阻断合成）。
    on_progress(done: int, total: int, msg: str)：可选进度回调。
    """
    opts = opts or {}
    if not _proxy_enabled_from_opts(opts):
        return {}
    max_height = _proxy_max_height_from_opts(opts)

    # 收集去重的 {video_id: src_path}（一个素材的多切片只生成一次代理）
    candidates: Dict[str, str] = {}
    for r in rows:
        vid = str(r.get("video_id") or "").strip()
        vfp = str(r.get("video_file_path") or "").strip()
        if not vid or not vfp:
            continue
        if vid in candidates:
            continue
        src_path = vfp
        # video_file_path 可能是 DB 相对路径，转绝对
        from app.utils.paths import resolve_stored_path
        src_abs = resolve_stored_path(src_path)
        if not os.path.isfile(src_abs):
            continue
        candidates[vid] = src_abs

    if not candidates:
        return {}

    result: Dict[str, str] = {}
    todo = []
    for vid, src_abs in candidates.items():
        proxy_path = _proxy_path_for(vid)
        ref_dur = float(probe_duration(src_abs, log_on_failure=True) or 0.0)
        # 已有可用代理 → 直接复用（缓存命中）
        if _proxy_valid(proxy_path, ref_dur):
            result[vid] = proxy_path
            continue
        # 仅 >目标分辨率的原片才需代理
        if not _needs_proxy(src_abs, max_height):
            continue
        todo.append((vid, src_abs, proxy_path, ref_dur))

    total = len(todo)
    if total == 0:
        return result  # 全部命中缓存或无需代理

    logger.info("代理生成：%d 个素材待转码（目标高度 %dp）", total, max_height)
    for i, (vid, src_abs, proxy_path, ref_dur) in enumerate(todo, 1):
        try:
            generate_proxy(
                src_path=src_abs,
                out_path=proxy_path,
                max_height=max_height,
                prefer_gpu=prefer_gpu,
            )
            # 生成后校验时间轴对齐，通过才纳入
            if _proxy_valid(proxy_path, ref_dur):
                result[vid] = proxy_path
                logger.info("代理生成完成: %s -> %s", os.path.basename(src_abs), proxy_path)
            else:
                logger.warning("代理生成后时长校验失败，回退原片: %s", src_abs)
        except Exception as e:
            logger.warning("代理生成失败，回退原片: %s: %s", src_abs, e)
        if on_progress:
            on_progress(i, total, f"代理生成 {i}/{total}")
    return result
