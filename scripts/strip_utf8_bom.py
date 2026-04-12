#!/usr/bin/env python3
"""
递归去除 .py 文件开头的 UTF-8 BOM（EF BB BF）。

PyArmor 等工具会用 ast.parse 解析源码，行首 BOM 会触发
SyntaxError: invalid non-printable character U+FEFF。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BOM = b"\xef\xbb\xbf"
SKIP_DIR_NAMES = frozenset(
    {
        "venv",
        ".venv",
        "__pycache__",
        ".git",
        "node_modules",
        "dist",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "_pyarmor_pyinstaller",
        "_nuitka",
    }
)


def iter_py_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() == ".py" else []
    out: list[Path] = []
    for p in path.rglob("*.py"):
        if any(part in SKIP_DIR_NAMES for part in p.parts):
            continue
        out.append(p)
    return out


def strip_file(path: Path, *, dry_run: bool) -> bool:
    data = path.read_bytes()
    if not data.startswith(BOM):
        return False
    if not dry_run:
        path.write_bytes(data[len(BOM) :])
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="去除 .py 文件 UTF-8 BOM")
    parser.add_argument(
        "paths",
        nargs="*",
        help="目录或 .py 文件；省略时默认扫描仓库 backend/",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只列出需要修改的文件，不写盘",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent

    if args.paths:
        targets = [Path(p).expanduser().resolve() for p in args.paths]
    else:
        targets = [repo_root / "backend"]

    fixed: list[Path] = []
    try:
        for t in targets:
            if not t.exists():
                print(f"跳过（不存在）: {t}", file=sys.stderr)
                continue
            for py in iter_py_files(t):
                if strip_file(py, dry_run=args.dry_run):
                    fixed.append(py)
    except OSError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"将去除 BOM: {len(fixed)} 个文件")
    else:
        print(f"已去除 BOM: {len(fixed)} 个文件")
    for p in fixed:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
