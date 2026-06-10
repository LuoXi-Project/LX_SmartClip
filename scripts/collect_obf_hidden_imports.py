"""Scan PyArmor obf/ tree and emit dotted module names for PyInstaller --hidden-import."""
from __future__ import annotations

import sys
from pathlib import Path


def module_name_from_py(obf_root: Path, py_file: Path) -> str | None:
    try:
        rel = py_file.relative_to(obf_root)
    except ValueError:
        return None
    parts = list(rel.parts)
    if not parts or not parts[-1].endswith(".py"):
        return None
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]
    if not parts:
        return None
    return ".".join(parts)


def collect(obf_dir: Path) -> list[str]:
    obf_dir = obf_dir.resolve()
    names: set[str] = set()
    for py in sorted(obf_dir.rglob("*.py")):
        mod = module_name_from_py(obf_dir, py)
        if mod:
            names.add(mod)
    return sorted(names)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: collect_obf_hidden_imports.py <obf_dir>", file=sys.stderr)
        return 2
    obf_dir = Path(sys.argv[1])
    if not obf_dir.is_dir():
        print(f"obf dir not found: {obf_dir}", file=sys.stderr)
        return 1
    for name in collect(obf_dir):
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
