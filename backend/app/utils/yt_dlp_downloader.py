from __future__ import annotations

import os
import shutil
import subprocess
import sys


class YtDlpDownloadError(Exception):
    pass


def ensure_yt_dlp_available() -> None:
    """
    兼容两种安装形态：
    - 有 `yt-dlp` 可执行文件（shutil.which 命中）
    - 只有 Python 包（可通过 `python -m yt_dlp` 调用）
    """
    if shutil.which("yt-dlp"):
        return
    try:
        import yt_dlp  # noqa: F401
    except Exception as exc:
        raise YtDlpDownloadError(
            "未检测到 yt-dlp 可执行文件，也未检测到 python 包。请安装 yt-dlp 后重试。"
        ) from exc


def _build_yt_dlp_base_cmd() -> list[str]:
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    return [sys.executable, "-m", "yt_dlp"]


def _pick_downloaded_file(output_dir: str, file_stem: str) -> str:
    candidates: list[str] = []
    for name in os.listdir(output_dir):
        if name.startswith(file_stem + "."):
            candidates.append(os.path.join(output_dir, name))
    if not candidates:
        raise YtDlpDownloadError("yt-dlp 下载成功但未找到落盘视频文件")

    mp4s = [p for p in candidates if p.lower().endswith(".mp4")]
    if mp4s:
        return max(mp4s, key=lambda p: os.path.getsize(p))
    return max(candidates, key=lambda p: os.path.getsize(p))


def download_video_with_yt_dlp(
    *,
    url: str,
    output_dir: str,
    file_stem: str,
    timeout_sec: int = 60 * 20,
) -> str:
    """
    用 yt-dlp 下载视频到 output_dir，并返回最终文件路径。
    """
    os.makedirs(output_dir, exist_ok=True)
    ensure_yt_dlp_available()

    out_tpl = os.path.join(output_dir, f"{file_stem}.%(ext)s")
    cmd = [
        *_build_yt_dlp_base_cmd(),
        "-f",
        "bestvideo+bestaudio/best",
        "--merge-output-format",
        "mp4",
        "--no-playlist",
        "--retries",
        "3",
        "--fragment-retries",
        "3",
        "--no-part",
        "--restrict-filenames",
        "-o",
        out_tpl,
        url,
    ]

    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_sec)
    if proc.returncode != 0:
        err_tail = (proc.stderr.decode(errors="replace") or "").strip()[-2000:]
        raise YtDlpDownloadError(f"yt-dlp 下载失败：{err_tail}")

    return _pick_downloaded_file(output_dir, file_stem)
