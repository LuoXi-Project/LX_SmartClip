"""音频母带：响度标准化与限幅。"""
from __future__ import annotations

import logging
import os
import uuid

from app.models.production import AudioMasterPolicy
from app.utils.ffmpeg_utils import run_ffmpeg

logger = logging.getLogger(__name__)


def apply_audio_master(video_path: str, policy: AudioMasterPolicy) -> str:
    if policy.loudnorm == "off" and not policy.limiter:
        return video_path
    if not os.path.isfile(video_path):
        return video_path

    out_dir = os.path.dirname(os.path.abspath(video_path))
    base = os.path.splitext(os.path.basename(video_path))[0]
    out_path = os.path.join(out_dir, f"{base}_master_{uuid.uuid4().hex[:6]}.mp4")

    filters: list[str] = []
    if policy.loudnorm == "fast":
        i = float(policy.target_lufs)
        filters.append(f"loudnorm=I={i}:TP=-1.5:LRA=11")
    elif policy.loudnorm == "precise":
        i = float(policy.target_lufs)
        filters.append(f"loudnorm=I={i}:TP=-1.5:LRA=7:linear=true")
    if policy.limiter:
        filters.append("alimiter=limit=0.95")

    if not filters:
        return video_path

    af = ",".join(filters)
    try:
        run_ffmpeg(
            [
                "-i",
                video_path,
                "-af",
                af,
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                out_path,
            ],
            desc="postprod loudnorm",
        )
        return out_path
    except Exception as e:
        logger.warning("音频母带失败，回退原片: %s", e)
        return video_path
