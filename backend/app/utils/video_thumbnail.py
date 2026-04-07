from __future__ import annotations

import os
import subprocess


THUMBNAIL_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "storage", "thumbnails")
)
os.makedirs(THUMBNAIL_DIR, exist_ok=True)


def generate_thumbnail(video_path: str, video_id: str) -> str | None:
    """使用 ffmpeg 提取视频封面帧，返回封面图路径，失败返回 None。"""
    out_path = os.path.join(THUMBNAIL_DIR, f"{video_id}.jpg")
    for ss in ("00:00:01", "00:00:00"):
        try:
            result = subprocess.run(
                [
                    "ffmpeg",
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
