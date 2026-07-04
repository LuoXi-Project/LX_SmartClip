"""Playwright/patchright 依赖自检（仿 check_whisper_deps.py）。

用法：
    python check_playwright_deps.py [browsers_path]

检查：
1. patchright（或 playwright）pip 包可 import
2. browsers_path（默认取 PLAYWRIGHT_BROWSERS_PATH 环境变量）下存在 chromium-* 目录
   且含 chrome-win/chrome.exe（Windows）或 chrome-linux/chrome（非 Windows）

退出码：0=通过，1=失败。被 prepare_playwright.ps1 和 build 脚本调用。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def check_import() -> str | None:
    """返回可用的库名（patchright 优先），失败返回 None。"""
    for mod in ("patchright", "playwright"):
        try:
            __import__(mod)
            return mod
        except ImportError:
            continue
    return None


def check_browser(browsers_path: str) -> tuple[bool, str]:
    """检查 browsers_path 下是否有可用的 chromium。

    兼容两种目录结构：
    - 旧版：chromium-<rev>/chrome-win/chrome.exe
    - 新版：chromium-<rev>/chrome-win64/chrome.exe（patchright/playwright >= 1.50）
    """
    root = Path(browsers_path)
    if not root.is_dir():
        return False, f"浏览器目录不存在: {root}"

    # Windows 下的候选子目录名（按新旧版本优先级）
    win_subdirs = ("chrome-win64", "chrome-win")
    nix_subdirs = ("chrome-linux",)

    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not entry.name.startswith("chromium-"):
            continue
        subdirs = win_subdirs if os.name == "nt" else nix_subdirs
        exe_name = "chrome.exe" if os.name == "nt" else "chrome"
        for sub in subdirs:
            exe = entry / sub / exe_name
            if exe.is_file():
                return True, str(entry)

    return False, f"未在 {root} 找到含 chrome 可执行文件的 chromium-* 目录"


def main() -> int:
    browsers_path = (
        sys.argv[1] if len(sys.argv) > 1
        else (os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "")
    )

    mod = check_import()
    if not mod:
        print("patchright/playwright: NOT installed")
        print("请运行: pip install patchright")
        return 1

    # 版本号（尽量取，失败不致命）
    try:
        import importlib.metadata as md
        ver = md.version(mod)
    except Exception:
        ver = "?"
    print(f"{mod}={ver}")

    if not browsers_path:
        print("browsers_path 未指定（无参数且 PLAYWRIGHT_BROWSERS_PATH 未设置）")
        # 仅库已装也返回 0，便于开发期不强依赖浏览器
        return 0

    ok, detail = check_browser(browsers_path)
    if ok:
        print(f"chromium_ok=true path={detail}")
        return 0
    else:
        print(f"chromium_ok=false ({detail})")
        return 1


if __name__ == "__main__":
    sys.exit(main())
