"""让 openai-whisper 使用项目解析到的 ffmpeg（不依赖系统 PATH）。"""
from __future__ import annotations

import logging
import os
from subprocess import CalledProcessError, run

import numpy as np

from app.utils.bin_paths import apply_default_ffmpeg_environment, ffmpeg_bin

logger = logging.getLogger(__name__)
_PATCHED = False


def require_ffmpeg_executable() -> str:
    """返回可用的 ffmpeg 绝对路径；找不到时抛出带操作提示的异常。"""
    apply_default_ffmpeg_environment()
    ff = ffmpeg_bin()
    if os.path.isfile(ff):
        return os.path.abspath(ff)
    raise FileNotFoundError(
        "未找到 ffmpeg。Whisper 转写需要 ffmpeg 解码音频。\n"
        "请运行: .\\scripts\\prepare_ffmpeg.ps1\n"
        "或将 ffmpeg.exe 放入仓库 ffmpeg\\bin\\ 目录，或安装到系统 PATH。"
    )


def patch_whisper_ffmpeg() -> None:
    """一次性 patch whisper.audio.load_audio，使用 resolve 后的 ffmpeg 路径。"""
    global _PATCHED
    if _PATCHED:
        return

    import whisper.audio as whisper_audio

    ffmpeg = require_ffmpeg_executable()
    sample_rate = whisper_audio.SAMPLE_RATE

    def load_audio(file: str, sr: int = sample_rate):
        cmd = [
            ffmpeg,
            "-nostdin",
            "-threads",
            "0",
            "-i",
            file,
            "-f",
            "s16le",
            "-ac",
            "1",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(sr),
            "-",
        ]
        try:
            out = run(cmd, capture_output=True, check=True).stdout
        except CalledProcessError as e:
            stderr = (e.stderr or b"").decode(errors="replace")
            raise RuntimeError(f"ffmpeg 解码音频失败: {stderr}") from e
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"无法执行 ffmpeg: {ffmpeg}。请确认文件存在且可执行。"
            ) from e

        return np.frombuffer(out, np.int16).flatten().astype(np.float32) / 32768.0

    whisper_audio.load_audio = load_audio
    _PATCHED = True
    logger.debug("whisper.audio.load_audio 已指向: %s", ffmpeg)
