from __future__ import annotations

import os
import shutil
import sys
from typing import Iterable


def _bundled_binary_candidates(name: str) -> Iterable[str]:
    """PyInstaller / Nuitka 等打包场景下，可执行文件与资源目录中的候选路径（优先于 PATH）。"""
    is_windows = os.name == "nt"
    bin_name = f"{name}.exe" if is_windows else name

    # PyInstaller onefile/onedir：解包目录（多为 _internal）
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        yield os.path.join(meipass, bin_name)
        yield os.path.join(meipass, "bin", bin_name)

    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        yield os.path.join(exe_dir, bin_name)
        yield os.path.join(exe_dir, "bin", bin_name)
        yield os.path.join(exe_dir, "_internal", bin_name)
        yield os.path.join(exe_dir, "_internal", "bin", bin_name)


def _bundled_binary_path_if_present(name: str) -> str | None:
    """若打包目录内存在该二进制则返回绝对路径，否则 None。"""
    for p in _bundled_binary_candidates(name):
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    return None


def apply_default_ffmpeg_environment() -> None:
    """
    将 FFmpeg 相关环境变量默认指向打包内置二进制（若存在且未显式设置）。

    - FFMPEG_BIN / FFPROBE_BIN：本模块 resolve_binary 会优先读取
    - IMAGEIO_FFMPEG_EXE：imageio-ffmpeg / MoviePy 使用
    """
    ff = _bundled_binary_path_if_present("ffmpeg")
    if ff:
        os.environ.setdefault("FFMPEG_BIN", ff)
        os.environ.setdefault("IMAGEIO_FFMPEG_EXE", ff)
    fp = _bundled_binary_path_if_present("ffprobe")
    if fp:
        os.environ.setdefault("FFPROBE_BIN", fp)


def _candidate_paths(name: str) -> Iterable[str]:
    is_windows = os.name == "nt"
    bin_name = f"{name}.exe" if is_windows else name

    env_var = f"{name.upper()}_BIN"
    env_path = (os.getenv(env_var) or "").strip()
    if env_path:
        yield env_path

    yield from _bundled_binary_candidates(name)

    which_path = shutil.which(name)
    if which_path:
        yield which_path
    if is_windows:
        which_exe = shutil.which(bin_name)
        if which_exe:
            yield which_exe


def resolve_binary(name: str) -> str:
    for p in _candidate_paths(name):
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    return name


def ffmpeg_bin() -> str:
    return resolve_binary("ffmpeg")


def ffprobe_bin() -> str:
    return resolve_binary("ffprobe")
