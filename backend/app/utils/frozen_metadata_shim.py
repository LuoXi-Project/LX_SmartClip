"""
PyInstaller / frozen 运行时：部分包（如 imageio）在 import 时用 importlib.metadata 读版本。
若未打入对应 .dist-info，会报 “No package metadata was found for …”。
在首次导入这些包之前调用 apply_frozen_metadata_shim()，从 sys._MEIPASS 解析 METADATA 兜底。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

_applied = False


def _canonical_dist_key(name: str) -> str:
    try:
        from packaging.utils import canonicalize_name

        return str(canonicalize_name(name))
    except Exception:
        return name.strip().lower().replace("_", "-")


def _versions_from_meipass() -> dict[str, str]:
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return {}
    base = Path(meipass)
    out: dict[str, str] = {}
    for meta_dir in base.rglob("*.dist-info"):
        meta_file = meta_dir / "METADATA"
        if not meta_file.is_file():
            continue
        dist_name: str | None = None
        version: str | None = None
        for line in meta_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Name: "):
                dist_name = line[6:].strip()
            elif line.startswith("Version: "):
                version = line[9:].strip()
            if dist_name and version:
                break
        if dist_name and version:
            out[_canonical_dist_key(dist_name)] = version
    return out


def apply_frozen_metadata_shim() -> None:
    global _applied
    if _applied:
        return
    if not getattr(sys, "frozen", False):
        return

    import importlib.metadata as im

    _orig_version: Callable[[str], str] = im.version
    _cache = _versions_from_meipass()

    def _version(dist_name: str) -> str:
        try:
            return _orig_version(dist_name)
        except im.PackageNotFoundError:
            key = _canonical_dist_key(dist_name)
            v = _cache.get(key)
            if v is not None:
                return v
            raise

    im.version = _version  # type: ignore[method-assign]
    _applied = True
