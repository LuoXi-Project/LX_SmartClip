from __future__ import annotations

import os
import shutil
import sys
from typing import Iterable


def _candidate_paths(name: str) -> Iterable[str]:
    is_windows = os.name == "nt"
    bin_name = f"{name}.exe" if is_windows else name

    env_var = f"{name.upper()}_BIN"
    env_path = (os.getenv(env_var) or "").strip()
    if env_path:
        yield env_path

    which_path = shutil.which(name)
    if which_path:
        yield which_path
    if is_windows:
        which_exe = shutil.which(bin_name)
        if which_exe:
            yield which_exe

    # PyInstaller onefile/onedir: 临时解包目录
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        yield os.path.join(meipass, bin_name)

    # 打包后主程序目录
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        yield os.path.join(exe_dir, bin_name)
        yield os.path.join(exe_dir, "bin", bin_name)
        yield os.path.join(exe_dir, "_internal", "bin", bin_name)


def resolve_binary(name: str) -> str:
    for p in _candidate_paths(name):
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    return name


def ffmpeg_bin() -> str:
    return resolve_binary("ffmpeg")


def ffprobe_bin() -> str:
    return resolve_binary("ffprobe")
