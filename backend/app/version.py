from __future__ import annotations

import json
import re
import sys
from functools import lru_cache
from pathlib import Path


_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][\w.-]+)?$")


def _repo_root() -> Path:
    # backend/app/version.py -> repo root
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def get_app_version() -> str:
    for path in _bundled_version_paths():
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            v = str(data.get("app_version") or "").strip()
            if v:
                return v
        except Exception:
            continue

    version_file = _repo_root() / "VERSION"
    if version_file.is_file():
        v = version_file.read_text(encoding="utf-8-sig").strip().splitlines()[0].strip()
        if v:
            return v

    return "0.0.0-dev"


def _bundled_version_paths() -> list[Path]:
    paths: list[Path] = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass = Path(getattr(sys, "_MEIPASS"))  # type: ignore[arg-type]
        paths.append(meipass / "version.json")
        paths.append(meipass / "app" / "version.json")
    paths.append(Path(__file__).resolve().parent / "version.json")
    return paths


@lru_cache(maxsize=1)
def get_schema_version() -> int:
    from app.db.schema import CURRENT_SCHEMA_VERSION

    for path in _bundled_version_paths():
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            sv = data.get("schema_version")
            if isinstance(sv, int):
                return sv
        except Exception:
            continue
    return CURRENT_SCHEMA_VERSION


def parse_semver(version: str) -> tuple[int, int, int, str | None]:
    raw = (version or "").strip()
    if raw.startswith("v"):
        raw = raw[1:]
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:[-+](.+))?$", raw)
    if not m:
        return (0, 0, 0, None)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4))


def compare_versions(a: str, b: str) -> int:
    """Return -1 if a<b, 0 if equal, 1 if a>b (ignores pre-release for simplicity)."""
    ma, mi, pa, pre_a = parse_semver(a)
    mb, mj, pb, pre_b = parse_semver(b)
    if (ma, mi, pa) != (mb, mj, pb):
        return -1 if (ma, mi, pa) < (mb, mj, pb) else 1
    if pre_a == pre_b:
        return 0
    if pre_a and not pre_b:
        return -1
    if pre_b and not pre_a:
        return 1
    return -1 if pre_a < pre_b else (1 if pre_a > pre_b else 0)
