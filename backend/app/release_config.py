from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _bundled_paths(filename: str) -> list[Path]:
    paths: list[Path] = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass = Path(getattr(sys, "_MEIPASS"))  # type: ignore[arg-type]
        paths.append(meipass / filename)
        paths.append(meipass / "app" / filename)
    paths.append(Path(__file__).resolve().parent / filename)
    paths.append(_repo_root() / filename)
    return paths


@lru_cache(maxsize=1)
def get_release_config() -> dict:
    for path in _bundled_paths("release.config.json"):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {
        "release_repo": "",
        "asset_name_template": "LX_SmartClip-{version}-win64.zip",
        "product_name": "LX SmartClip",
    }


def get_release_repo() -> str:
    return str(get_release_config().get("release_repo") or "").strip()


def asset_name_for_version(version: str) -> str:
    tpl = str(get_release_config().get("asset_name_template") or "LX_SmartClip-{version}-win64.zip")
    v = version[1:] if version.startswith("v") else version
    return tpl.replace("{version}", v)
