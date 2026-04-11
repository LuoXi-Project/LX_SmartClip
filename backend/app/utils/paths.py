from __future__ import annotations

import os
import sys
import tempfile
from functools import lru_cache
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


def _dev_backend_dir() -> Path:
    """源码运行：定位到 `backend/`（paths.py 位于 backend/app/utils/）。"""
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def get_writable_backend_root() -> Path:
    """
    持久化数据根目录（与仓库中 `backend/` 布局一致：其下可有 `data/`、`storage/`）。

    - 源码：仓库内的 `backend/`
    - PyInstaller：优先环境变量 `LX_SMARTCLIP_HOME`；否则 `exe` 同级目录（可写时）；
      再否则本地应用数据目录；最后为系统临时目录下的子目录。
    """
    env_home = (os.environ.get("LX_SMARTCLIP_HOME") or "").strip()
    if env_home:
        p = Path(env_home).expanduser().resolve()
        if _is_writable_dir(p):
            return p

    if getattr(sys, "frozen", False):
        candidates: list[Path] = []
        try:
            exe_dir = Path(sys.executable).resolve().parent
            candidates.append(exe_dir)
        except Exception:
            pass

        local = os.environ.get("LOCALAPPDATA") or ""
        if local:
            candidates.append(Path(local) / "LX_SmartClip")
        if sys.platform == "darwin":
            home = os.environ.get("HOME", "")
            if home:
                candidates.append(Path(home) / "Library" / "Application Support" / "LX_SmartClip")
        else:
            home = os.environ.get("HOME") or os.environ.get("USERPROFILE", "")
            if home and sys.platform != "win32":
                candidates.append(Path(home) / ".local" / "share" / "LX_SmartClip")

        candidates.append(Path(tempfile.gettempdir()) / "LX_SmartClip")

        for base in candidates:
            if _is_writable_dir(base):
                return base

        return Path(tempfile.gettempdir())

    return _dev_backend_dir()


@lru_cache(maxsize=1)
def get_resource_backend_root() -> Path:
    """
    只读资源根（字体、随包静态素材等）。

    - 源码：与 `get_writable_backend_root()` 相同（`backend/`）
    - 打包：优先 `sys._MEIPASS`（PyInstaller 解包目录），否则退回可写根目录。
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        try:
            return Path(getattr(sys, "_MEIPASS")).resolve()  # type: ignore[arg-type]
        except Exception:
            pass
    return get_writable_backend_root()


def get_data_dir() -> Path:
    return get_writable_backend_root() / "data"


def get_db_path() -> str:
    p = get_data_dir() / "smartclip.db"
    return str(p.resolve())


def get_storage_root() -> Path:
    return get_writable_backend_root() / "storage"


def storage_subpath(*parts: str) -> str:
    """返回 `storage/<parts...>` 的绝对路径字符串。"""
    root = get_storage_root()
    return str(root.joinpath(*parts).resolve())


def ensure_storage_subpath(*parts: str) -> str:
    """创建 `storage/<parts...>` 目录并返回绝对路径字符串。"""
    p = get_storage_root().joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return str(p.resolve())


def get_fonts_dir() -> str:
    """字幕烧录等使用的字体目录：优先包内 `fonts/`，否则可写根下 `fonts/`。"""
    for base in (get_resource_backend_root(), get_writable_backend_root()):
        d = base / "fonts"
        if d.is_dir():
            return str(d.resolve())
    d = get_writable_backend_root() / "fonts"
    d.mkdir(parents=True, exist_ok=True)
    return str(d.resolve())


def iter_storage_static_mount_candidates() -> list[str]:
    """
    供 FastAPI 挂载 `/storage` 静态目录：优先可写 `storage`（与用户上传一致），
    再尝试包内只读副本（兼容旧打包资源布局）。
    """
    seen: set[str] = set()
    out: list[str] = []
    for p in (
        get_storage_root(),
        get_resource_backend_root() / "storage",
        _dev_backend_dir() / "storage",
    ):
        try:
            s = str(p.resolve())
        except Exception:
            continue
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


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

    # 与业务持久化 storage 对齐（打包后写入不在 _MEIPASS 时仍可用）
    try:
        candidates.append(get_writable_backend_root() / "storage" / "tmp")
    except Exception:
        pass

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

