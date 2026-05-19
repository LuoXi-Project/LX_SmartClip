"""混剪成片后处理：覆盖视频叠加。"""
from __future__ import annotations

import logging
import os
import subprocess
import uuid
from typing import Tuple

from app.models.auto_edit import MixOverlayVideoConfig, Plan
from app.utils.bin_paths import ffprobe_bin
from app.utils.ffprobe_utils import probe_duration, probe_video_dimensions
from app.utils.ffmpeg_utils import run_ffmpeg
from app.utils.paths import storage_public_url_for_file

logger = logging.getLogger(__name__)


def _has_audio_stream(path: str) -> bool:
    probe = subprocess.run(
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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    return (probe.stdout.decode(errors="replace") or "").strip() == "audio"


def _resolve_media_path(raw: str | None) -> str | None:
    if not raw:
        return None
    p = raw.strip()
    if not p:
        return None
    if os.path.isfile(p):
        return os.path.abspath(p)
    # 相对 backend 根或 storage
    from app.utils.paths import ensure_storage_subpath, get_writable_backend_root

    root = str(get_writable_backend_root())
    for candidate in (
        os.path.join(root, p),
        ensure_storage_subpath("mix_assets", os.path.basename(p)),
        os.path.join(ensure_storage_subpath("mix_assets"), p),
    ):
        ap = os.path.abspath(candidate)
        if os.path.isfile(ap):
            return ap
    return None


def apply_overlay_video_postprocess(
    video_path: str,
    overlay_cfg: MixOverlayVideoConfig,
) -> str:
    overlay_path = _resolve_media_path(overlay_cfg.path)
    if not overlay_path:
        raise FileNotFoundError(f"覆盖视频不存在: {overlay_cfg.path}")

    opacity = min(1.0, max(0.0, float(overlay_cfg.opacity)))
    volume = min(1.0, max(0.0, float(overlay_cfg.volume)))

    main_w, main_h = probe_video_dimensions(video_path, default=(1920, 1080), logger_=logger)
    video_dur = float(probe_duration(video_path) or 0.0)
    if video_dur <= 0:
        raise RuntimeError("无法探测主成片时长")

    out_dir = os.path.dirname(os.path.abspath(video_path))
    out_path = os.path.join(
        out_dir,
        f"{os.path.splitext(os.path.basename(video_path))[0]}_ov_{uuid.uuid4().hex[:6]}.mp4",
    )

    main_has_audio = _has_audio_stream(video_path)
    ov_has_audio = _has_audio_stream(overlay_path)

    vf = (
        f"[1:v]scale={main_w}:{main_h}:force_original_aspect_ratio=decrease,"
        f"pad={main_w}:{main_h}:(ow-iw)/2:(oh-ih)/2,format=yuva420p,"
        f"colorchannelmixer=aa={opacity:.4f}[ov];"
        f"[0:v][ov]overlay=0:0:format=auto[vout]"
    )

    args = ["-i", video_path, "-i", overlay_path, "-filter_complex", vf, "-map", "[vout]"]
    if main_has_audio and ov_has_audio:
        af = f";[1:a]volume={volume:.4f}[ov_a];[0:a][ov_a]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        args[5] = vf + af
        args += ["-map", "[aout]"]
    elif ov_has_audio:
        af = f";[1:a]volume={volume:.4f}[aout]"
        args[5] = vf + af
        args += ["-map", "[aout]"]
    elif main_has_audio:
        args += ["-map", "0:a"]

    args += [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-shortest",
        "-t",
        f"{video_dur:.3f}",
        out_path,
    ]
    run_ffmpeg(args, desc="mix overlay video")
    return out_path


def apply_mix_overlay_if_needed(plan: Plan, filename: str, url: str) -> Tuple[str, str]:
    pp = getattr(plan, "postprocess", None)
    if not pp or not pp.overlay_video:
        return filename, url
    ov = pp.overlay_video
    if not (ov.path or "").strip():
        return filename, url
    if not ov.enabled:
        return filename, url

    from app.core.bgm.auto_bgm import resolve_burned_videos_dir_from_public_url
    from app.utils.paths import ensure_storage_subpath

    burn_dir = (
        resolve_burned_videos_dir_from_public_url(url)
        if (url or "").strip()
        else ensure_storage_subpath("burned_videos")
    )
    src = os.path.join(burn_dir, filename)
    if not os.path.isfile(src):
        logger.warning("覆盖视频后处理跳过：成片不存在 %s", src)
        return filename, url

    try:
        mixed = apply_overlay_video_postprocess(src, ov)
    except Exception as e:
        logger.error("覆盖视频叠加失败，回退原成片: %s", e)
        return filename, url

    return os.path.basename(mixed), storage_public_url_for_file(mixed)
