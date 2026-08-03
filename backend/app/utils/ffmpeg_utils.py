from __future__ import annotations

import logging
import os
import subprocess
from typing import List

from app.utils.bin_paths import ffmpeg_bin

logger = logging.getLogger(__name__)


def ffmpeg_subprocess_timeout_sec() -> int:
    """子进程超时（秒）。环境变量 SMARTCLIP_FFMPEG_TIMEOUT_SEC 可覆盖，默认 3600。"""
    raw = (os.environ.get("SMARTCLIP_FFMPEG_TIMEOUT_SEC") or "").strip()
    if not raw:
        return 3600
    try:
        return max(120, int(raw))
    except ValueError:
        return 3600


def run_ffmpeg(args: List[str], desc: str = "") -> None:
    """运行 FFmpeg 命令，失败时抛出 RuntimeError 并附带 stderr 输出。

    用 Popen + 实时读取 stderr，避免「进程假死时无任何输出、无限阻塞」的问题：
    - 实时把 ffmpeg 的进度行（frame=/time=）打到日志，便于区分「在跑」vs「卡死」；
    - 进度停滞超过 stall_timeout_sec 视为卡死，主动 kill 进程并抛错（让上层回退），
      而非等到 3600s 总超时。
    """
    cmd = [ffmpeg_bin(), "-y"] + args
    timeout_sec = ffmpeg_subprocess_timeout_sec()
    # 进度停滞超时：ffmpeg 若超过该时长无新进度输出，视为卡死（NVENC 会话耗尽/解码死循环等）。
    # 默认 300s：正常编码即使很慢也会有进度行；完全无进度 >5min 几乎必是假死。
    stall_timeout_sec = _ffmpeg_stall_timeout_sec()
    logger.info("FFmpeg%s: %s", f" [{desc}]" if desc else "", " ".join(cmd))

    import subprocess as _sp
    import threading
    import time as _time

    proc = _sp.Popen(cmd, stdout=_sp.PIPE, stderr=_sp.PIPE)
    last_progress_ts = [_time.monotonic()]
    last_progress_line = [""]
    stderr_lines: list = []

    def _read_stderr():
        try:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode(errors="replace").rstrip()
                stderr_lines.append(line)
                # 检测进度行（frame=/time=/size=），更新进度时间戳并精简打印
                if "frame=" in line or "time=" in line or "size=" in line:
                    last_progress_ts[0] = _time.monotonic()
                    last_progress_line[0] = line
        finally:
            proc.stderr.close()

    reader = threading.Thread(target=_read_stderr, daemon=True)
    reader.start()

    start = _time.monotonic()
    killed_for_stall = False
    while True:
        ret = proc.poll()
        if ret is not None:
            break
        now = _time.monotonic()
        # 总超时
        if now - start > timeout_sec:
            proc.kill()
            proc.wait(timeout=30)
            raise RuntimeError(
                f"FFmpeg 总超时 [{desc}]（{timeout_sec}s）\ncmd: {' '.join(cmd)}"
            )
        # 进度停滞超时（卡死检测）
        if stall_timeout_sec > 0 and now - last_progress_ts[0] > stall_timeout_sec:
            killed_for_stall = True
            logger.warning(
                "FFmpeg [%s] 进度停滞 %ds，判定卡死，终止进程（最后进度: %s）",
                desc, stall_timeout_sec, last_progress_line[0][:200],
            )
            proc.kill()
            proc.wait(timeout=30)
            break
        _time.sleep(2.0)

    reader.join(timeout=10)
    returncode = proc.returncode
    stderr_tail = "\n".join(stderr_lines[-80:])

    if killed_for_stall:
        raise RuntimeError(
            f"FFmpeg 进度停滞卡死 [{desc}]（{stall_timeout_sec}s 无进度）\n"
            f"cmd: {' '.join(cmd)}\n"
            f"最后进度: {last_progress_line[0][:300]}\n"
            f"stderr 尾部:\n{stderr_tail[-2000:]}"
        )
    if returncode != 0:
        raise RuntimeError(
            f"FFmpeg 失败 [{desc}]\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stderr: {stderr_tail[-2000:]}"
        )


def _ffmpeg_stall_timeout_sec() -> int:
    """ffmpeg 进度停滞超时（秒）。环境变量 SMARTCLIP_FFMPEG_STALL_TIMEOUT_SEC 可覆盖，默认 300。

    进度停滞超过该时长视为进程卡死（NVENC 会话耗尽/解码死循环/filter 死锁等），
    主动终止而非等到总超时。设 0 关闭卡死检测（仅用总超时）。
    """
    raw = (os.environ.get("SMARTCLIP_FFMPEG_STALL_TIMEOUT_SEC") or "").strip()
    if not raw:
        return 300
    try:
        return max(0, int(raw))
    except ValueError:
        return 300



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

