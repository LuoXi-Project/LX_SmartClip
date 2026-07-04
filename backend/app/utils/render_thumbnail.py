"""成片缩略图懒生成。

复用 video_thumbnail.generate_thumbnail 的 ffmpeg 抽帧命令，
但缩略图存到成片同目录的 .thumbs/ 子目录，文件名 = 成片 basename + .jpg。
"""
from __future__ import annotations

import os
import subprocess

from app.utils.bin_paths import ffmpeg_bin


def generate_render_thumbnail(video_abs_path: str) -> str | None:
    """为成片生成缩略图，返回绝对路径，失败返回 None。

    存储位置：<成片所在目录>/.thumbs/<成片stem>.jpg
    """
    if not os.path.isfile(video_abs_path):
        return None
    out_dir = os.path.join(os.path.dirname(video_abs_path), ".thumbs")
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(video_abs_path))[0]
    out_path = os.path.join(out_dir, f"{stem}.jpg")

    for ss in ("00:00:01", "00:00:00"):
        try:
            result = subprocess.run(
                [
                    ffmpeg_bin(),
                    "-y",
                    "-ss",
                    ss,
                    "-i",
                    video_abs_path,
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=480:-1",  # 成片缩略图略大，适合卡片预览
                    "-q:v",
                    "4",
                    out_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
            if result.returncode == 0 and os.path.exists(out_path):
                return out_path
        except Exception:
            continue
    return None
