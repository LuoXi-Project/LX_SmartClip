"""HyperFrames 渲染运行时解析：Node / node_modules / Chromium / FFmpeg。

解析顺序（对齐 bin_paths.py 惯例：env 覆盖 → 打包内置 → 开发仓库 → PATH）：
- node：NODE_BIN → 打包目录 node/node.exe → PATH
- node_modules：打包 motion-runtime/node_modules（dist 随包、零 npm）→
  开发环境 <data>/motion/node_modules（首用 bootstrap 安装）
- Chromium：HF_CHROME_PATH → 仓库/包内 ms-playwright 的 chromium-*（优先全量版，
  回退 headless_shell）→ 不下载 Puppeteer 自带浏览器
- FFmpeg/FFprobe：复用 bin_paths.ffmpeg_bin()/ffprobe_bin()，经环境变量注入渲染桥
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import sys
from pathlib import Path
from typing import Any

from app.utils.bin_paths import (
    apply_default_ffmpeg_environment,
    apply_default_playwright_environment,
    ffmpeg_bin,
    ffprobe_bin,
    resolve_binary,
)

logger = logging.getLogger(__name__)

BRIDGE_DIR = Path(__file__).resolve().parent / "bridge"
PRODUCER_TESTED_VERSION = "0.9.52"   # 实测通过的版本（bridge/package.json 同步 pin）
_BOOTSTRAP_LOCK = asyncio.Lock()


class MotionRuntimeError(RuntimeError):
    """动效运行时不就绪（附带缺失项清单与指引）。"""

    def __init__(self, missing: list[str]):
        self.missing = missing
        hint = "；".join(missing)
        super().__init__(
            f"动效渲染运行时不就绪：{hint}。"
            "开发环境可调 POST /api/motion/runtime/bootstrap 自动安装依赖（需 Node 22+）；"
            "打包版请联系发行方检查随包 Node 运行时。"
        )


def workspace_dir() -> Path:
    """可写工作区：<data>/motion（合成、依赖、渲染桥都在这里运行）。"""
    from app.utils.paths import get_data_dir

    d = Path(get_data_dir()) / "motion"
    d.mkdir(parents=True, exist_ok=True)
    return d


def compositions_dir() -> Path:
    d = workspace_dir() / "compositions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def node_bin() -> str:
    """Node 可执行文件（env NODE_BIN → 打包 → PATH）。"""
    return resolve_binary("node")


def _packaged_node_modules_candidates() -> list[Path]:
    """打包版随包 node_modules 候选目录（motion-runtime）。"""
    cands: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cands.append(Path(meipass) / "motion-runtime" / "node_modules")
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        cands.append(exe_dir / "motion-runtime" / "node_modules")
        cands.append(exe_dir / "_internal" / "motion-runtime" / "node_modules")
    return cands


def node_modules_dir() -> Path | None:
    """渲染依赖目录：打包内置优先，其次工作区自装。"""
    for c in _packaged_node_modules_candidates():
        if (c / "@hyperframes" / "producer").is_dir():
            return c
    local = workspace_dir() / "node_modules"
    if (local / "@hyperframes" / "producer").is_dir():
        return local
    return None


def producer_entry() -> Path | None:
    """producer 的 ESM 入口绝对路径（render.mjs 动态 import 用）。"""
    nm = node_modules_dir()
    if not nm:
        return None
    entry = nm / "@hyperframes" / "producer" / "dist" / "index.js"
    return entry if entry.is_file() else None


def runtime_iife_path() -> Path | None:
    """HyperFrames 浏览器 runtime IIFE（iframe 预览注入用）。"""
    nm = node_modules_dir()
    if not nm:
        return None
    p = nm / "@hyperframes" / "core" / "dist" / "hyperframe.runtime.iife.js"
    return p if p.is_file() else None


def _chrome_rel_paths() -> list[list[str]]:
    """ms-playwright 下 chromium-*/ 内 chrome 可执行文件的相对路径候选。"""
    if sys.platform.startswith("win"):
        return [["chrome-win64", "chrome.exe"], ["chrome-win", "chrome.exe"]]
    if sys.platform == "darwin":
        return [["chrome-mac", "Contents", "MacOS", "Google Chrome for Testing"]]
    return [["chrome-linux", "chrome"], ["chrome-linux64", "chrome"]]


def _headless_shell_rel_paths() -> list[list[str]]:
    if sys.platform.startswith("win"):
        return [["chrome-headless-shell-win64", "chrome-headless-shell.exe"]]
    return [["chrome-headless-shell-linux64", "chrome-headless-shell"]]


def chromium_executable() -> str | None:
    """可执行 Chromium：env HF_CHROME_PATH → ms-playwright 全量版 → headless_shell。

    优先全量 Chromium（实测 producer 渲染通过，兼容 WebGL/shader 转场）。
    """
    env_path = (os.getenv("HF_CHROME_PATH") or "").strip()
    if env_path and os.path.isfile(env_path):
        return env_path

    apply_default_playwright_environment()
    browsers_root = (os.getenv("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
    roots = [browsers_root] if browsers_root else []
    # 开发仓库兜底：<repo>/playwright/ms-playwright（runtime.py → motion → core → app → backend → repo）
    if not getattr(sys, "frozen", False):
        roots.append(str(Path(__file__).resolve().parents[4] / "playwright" / "ms-playwright"))
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        # 全量 chromium 优先（版本号倒序取最新）
        for rel in _chrome_rel_paths():
            for exe in sorted(glob.glob(os.path.join(root, "chromium-*", *rel)), reverse=True):
                if os.path.isfile(exe):
                    return os.path.abspath(exe)
        for rel in _headless_shell_rel_paths():
            for exe in sorted(
                glob.glob(os.path.join(root, "chromium_headless_shell-*", *rel)), reverse=True
            ):
                if os.path.isfile(exe):
                    return os.path.abspath(exe)
    return None


def render_bridge_path() -> Path:
    """渲染桥脚本：工作区副本（与 node_modules 同目录便于解析），bootstrap 时落盘。"""
    return workspace_dir() / "render.mjs"


def _ensure_bridge_files() -> None:
    """把 bridge/package.json + render.mjs 同步到工作区（幂等，内容变更时覆盖）。"""
    ws = workspace_dir()
    src_pkg = BRIDGE_DIR / "package.json"
    dst_pkg = ws / "package.json"
    if not dst_pkg.is_file() or dst_pkg.read_text(encoding="utf-8") != src_pkg.read_text(encoding="utf-8"):
        dst_pkg.write_text(src_pkg.read_text(encoding="utf-8"), encoding="utf-8")
    src_mjs = BRIDGE_DIR / "render.mjs"
    dst_mjs = render_bridge_path()
    if not dst_mjs.is_file() or dst_mjs.read_text(encoding="utf-8") != src_mjs.read_text(encoding="utf-8"):
        dst_mjs.write_text(src_mjs.read_text(encoding="utf-8"), encoding="utf-8")


def runtime_status() -> dict[str, Any]:
    """运行时就绪态（GET /api/motion/runtime/status 数据源）。"""
    apply_default_ffmpeg_environment()
    node = node_bin()
    node_ok = bool(node) and os.path.isfile(node)
    nm = node_modules_dir()
    chrome = chromium_executable()
    ff = ffmpeg_bin()
    fp = ffprobe_bin()
    ff_ok = os.path.isfile(ff) and os.path.isfile(fp)
    deps_source = None
    if nm:
        for c in _packaged_node_modules_candidates():
            if c == nm:
                deps_source = "bundled"
                break
        deps_source = deps_source or "workspace"
    missing: list[str] = []
    if not node_ok:
        missing.append("未找到 Node.js（需要 22+，可设 NODE_BIN 指定）")
    if not nm:
        missing.append("渲染依赖未安装（@hyperframes/producer）")
    if not chrome:
        missing.append("未找到 Chromium（可设 HF_CHROME_PATH 指定）")
    if not ff_ok:
        missing.append("未找到 FFmpeg/FFprobe")
    return {
        "ready": not missing,
        "missing": missing,
        "node": {"ok": node_ok, "path": node if node_ok else None},
        "node_modules": {"ok": bool(nm), "dir": str(nm) if nm else None, "source": deps_source},
        "chromium": {"ok": bool(chrome), "path": chrome},
        "ffmpeg": {"ok": ff_ok, "path": ff if ff_ok else None},
        "producer_version": PRODUCER_TESTED_VERSION,
    }


async def bootstrap_runtime(*, on_log=None) -> dict[str, Any]:
    """开发环境自装依赖：npm install 到 <data>/motion（幂等，带进度回调）。

    - PUPPETEER_SKIP_DOWNLOAD=1：不下载 Puppeteer 自带浏览器，用仓库 Chromium
    - 打包版已有内置依赖时直接返回就绪
    """
    async with _BOOTSTRAP_LOCK:
        status = runtime_status()
        if status["ready"]:
            return status
        if not status["node"]["ok"]:
            raise MotionRuntimeError(status["missing"])
        _ensure_bridge_files()
        ws = workspace_dir()

        def _log(line: str) -> None:
            logger.info("[motion-bootstrap] %s", line)
            if on_log:
                on_log(line)

        env = os.environ.copy()
        env["PUPPETEER_SKIP_DOWNLOAD"] = "1"
        env["PUPPETEER_SKIP_CHROMIUM_DOWNLOAD"] = "1"
        _log("npm install（@hyperframes/producer 等，约 1~2 分钟）…")
        proc = await asyncio.create_subprocess_exec(
            "npm", "install", "--omit", "dev", "--no-fund", "--no-audit",
            cwd=str(ws), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        async for raw in proc.stdout:
            _log(raw.decode("utf-8", errors="replace").rstrip()[-300:])
        code = await proc.wait()
        if code != 0:
            raise MotionRuntimeError([f"npm install 失败（exit {code}）"])
        return runtime_status()


def ensure_ready() -> None:
    """渲染前检查：不就绪抛 MotionRuntimeError（附带缺失项）。"""
    status = runtime_status()
    if not status["ready"]:
        raise MotionRuntimeError(status["missing"])
    _ensure_bridge_files()
