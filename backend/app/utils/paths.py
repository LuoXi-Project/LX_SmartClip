from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        try:
            probe.unlink(missing_ok=True)  # py>=3.8
        except TypeError:
            if probe.exists():
                probe.unlink()
        return True
    except Exception:
        return False


def get_render_tmp_base_dir(env_key: str = "LX_SMARTCLIP_TMP_DIR") -> str:
    """
    获取用于存放临时渲染文件的基准目录（优先落到项目/发布包的 storage 下，避免占用系统盘临时目录）。

    优先级：
    1) 环境变量（默认 `LX_SMARTCLIP_TMP_DIR`）
    2) PyInstaller: `sys._MEIPASS/storage/tmp`
    3) 发布目录旁: `<exe_dir>/_internal/storage/tmp`
    4) 源码目录: `<repo>/backend/storage/tmp`
    5) 系统临时目录
    """
    env_dir = (os.environ.get(env_key) or "").strip()
    if env_dir:
        p = Path(env_dir).expanduser()
        if _is_writable_dir(p):
            return str(p)

    candidates: list[Path] = []

    # PyInstaller 解包资源目录
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        try:
            candidates.append(Path(getattr(sys, "_MEIPASS")) / "storage" / "tmp")  # type: ignore[arg-type]
        except Exception:
            pass

    # 可执行文件旁的 _internal（与 dist/backend/_internal/storage 结构兼容）
    try:
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "_internal" / "storage" / "tmp")
    except Exception:
        pass

    # 源码运行：backend/app/... 下的任意模块，都能通过该定位拿到 backend 目录
    try:
        # .../backend/app/utils/paths.py -> parents[2] = .../backend
        backend_dir = Path(__file__).resolve().parents[2]
        candidates.append(backend_dir / "storage" / "tmp")
    except Exception:
        pass

    for p in candidates:
        if _is_writable_dir(p):
            return str(p)

    return tempfile.gettempdir()

