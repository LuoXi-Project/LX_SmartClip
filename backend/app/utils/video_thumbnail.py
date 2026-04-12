from __future__ import annotations

import os
import subprocess

from app.utils.bin_paths import ffmpeg_bin
from app.utils.material_media_names import THUMBNAIL_FILENAME
from app.utils.paths import ensure_storage_subpath


def generate_thumbnail(video_path: str, video_id: str) -> str | None:
    """使用 ffmpeg 提取视频封面帧，返回封面图路径，失败返回 None。"""
    thumb_dir = ensure_storage_subpath(video_id, "thumbnails")
    out_path = os.path.join(thumb_dir, THUMBNAIL_FILENAME)
    for ss in ("00:00:01", "00:00:00"):
        try:
            result = subprocess.run(
                [
                    ffmpeg_bin(),
                    "-y",
                    "-ss",
                    ss,
                    "-i",
                    video_path,
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=320:-1",
                    "-q:v",
                    "5",
                    out_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=300,
            )
            if result.returncode == 0 and os.path.exists(out_path):
                return out_path
        except Exception:
            pass
    return None
