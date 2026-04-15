from __future__ import annotations

import logging
import os
import subprocess
from typing import List

from app.utils.bin_paths import ffmpeg_bin

logger = logging.getLogger(__name__)


def run_ffmpeg(args: List[str], desc: str = "") -> None:
    """运行 FFmpeg 命令，失败时抛出 RuntimeError 并附带 stderr 输出。"""
    cmd = [ffmpeg_bin(), "-y"] + args
    logger.info("FFmpeg%s: %s", f" [{desc}]" if desc else "", " ".join(cmd))
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=3600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg 失败 [{desc}]\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stderr: {result.stderr.decode(errors='replace')[-2000:]}"
        )


def write_concat_list(paths: List[str], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        for p in paths:
            f.write(f"file '{p.replace(chr(92), '/')}' \n")


def extract_audio_for_asr(
    input_path: str,
    output_path: str,
    *,
    overwrite: bool = True,
    sample_rate: int = 16000,
    channels: int = 1,
) -> str:
    """将输入媒体稳定转成 ASR 友好的 WAV（pcm_s16le / mono / 16kHz）。"""
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"输入媒体不存在: {input_path}")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    args = [
        "-i",
        input_path,
        "-vn",
        "-ac",
        str(max(1, int(channels))),
        "-ar",
        str(max(8000, int(sample_rate))),
        "-c:a",
        "pcm_s16le",
    ]
    args += ["-y" if overwrite else "-n", output_path]
    run_ffmpeg(args, desc="extract-audio-for-asr")
    return output_path

