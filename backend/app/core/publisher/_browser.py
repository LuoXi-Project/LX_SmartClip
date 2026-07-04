"""浏览器引擎定位：优先用户本地 Chrome/Edge，包内 Chromium 兜底。

决策依据：
- 本地浏览器指纹真实、版本自动更新、已登录态可复用，对风控更友好
- 包内 Chromium 仅在用户机器上没有 Chrome/Edge 时兜底
- patchright 默认要求 channel="chromium"，但支持 channel="chrome"/"msedge" 复用本地安装

注意：本模块被 worker 子进程和主进程共享，必须保持轻量（不 import playwright/patchright）。
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class BrowserKind(str, Enum):
    """实际命中的浏览器类型。"""
    LOCAL_CHROME = "chrome"        # 用户本地 Chrome（channel="chrome"）
    LOCAL_EDGE = "msedge"          # 用户本地 Edge（channel="msedge"）
    BUNDLED_CHROMIUM = "chromium"  # 包内/Playwright 自带 Chromium
    NONE = "none"                  # 找不到任何可用浏览器


@dataclass
class ResolvedBrowser:
    """解析后的浏览器配置，传给 patchright.launch()。"""
    kind: BrowserKind
    channel: Optional[str]         # patchright launch channel 参数；chromium 时为 None
    executable_path: Optional[str]  # 显式可执行路径；用 channel 时为 None
    display_label: str             # 给前端展示的中文名


def _windows_local_chrome_path() -> Optional[str]:
    """查找用户本地 Chrome 可执行文件（仅 Windows）。"""
    if os.name != "nt":
        return None
    # 标准安装路径
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    # 注册表
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as k:
                    val, _ = winreg.QueryValueEx(k, "")
                    if val and os.path.isfile(val):
                        return val
            except OSError:
                continue
    except Exception:
        pass
    return None


def _windows_local_edge_path() -> Optional[str]:
    """查找用户本地 Edge 可执行文件（仅 Windows）。"""
    if os.name != "nt":
        return None
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe") as k:
                    val, _ = winreg.QueryValueEx(k, "")
                    if val and os.path.isfile(val):
                        return val
            except OSError:
                continue
    except Exception:
        pass
    return None


def resolve_browser() -> ResolvedBrowser:
    """按优先级解析浏览器引擎。

    顺序：用户显式环境变量 LX_PUBLISHER_BROWSER > 本地 Chrome > 本地 Edge > 包内 Chromium。

    用户可用环境变量 LX_PUBLISHER_BROWSER=chrome|msedge|chromium 强制指定。
    """
    forced = (os.environ.get("LX_PUBLISHER_BROWSER") or "").strip().lower()
    if forced in ("chrome", "msedge", "chromium"):
        if forced == "chrome":
            p = _windows_local_chrome_path()
            if p:
                return ResolvedBrowser(BrowserKind.LOCAL_CHROME, "chrome", None, "本地 Chrome")
        elif forced == "msedge":
            p = _windows_local_edge_path()
            if p:
                return ResolvedBrowser(BrowserKind.LOCAL_EDGE, "msedge", None, "本地 Edge")
        # forced=chromium 或强制项未找到本地安装 → 走包内
        return ResolvedBrowser(BrowserKind.BUNDLED_CHROMIUM, None, None, "内置 Chromium")

    # 默认优先级：Chrome > Edge > 包内
    chrome_p = _windows_local_chrome_path()
    if chrome_p:
        return ResolvedBrowser(BrowserKind.LOCAL_CHROME, "chrome", None, "本地 Chrome")

    edge_p = _windows_local_edge_path()
    if edge_p:
        return ResolvedBrowser(BrowserKind.LOCAL_EDGE, "msedge", None, "本地 Edge")

    return ResolvedBrowser(BrowserKind.BUNDLED_CHROMIUM, None, None, "内置 Chromium")


def build_launch_kwargs(resolved: ResolvedBrowser, headless: bool) -> dict:
    """根据解析结果生成 patchright.chromium.launch() 的 kwargs。

    patchright 在用 channel 模式时会自动定位本地安装的 Chrome/Edge，
    无需 executable_path；走包内 Chromium 时 channel=None 由 patchright 自行查找。
    """
    kwargs: dict = {
        "headless": headless,
        "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    }
    if resolved.channel:
        kwargs["channel"] = resolved.channel
    if resolved.executable_path:
        kwargs["executable_path"] = resolved.executable_path
    return kwargs


def is_ready() -> bool:
    """检查浏览器引擎是否就绪（本地浏览器或包内 Chromium 至少有一个）。"""
    # 本地 Chrome/Edge 任意一个在即就绪
    if _windows_local_chrome_path() or _windows_local_edge_path():
        return True
    # 否则查包内 Chromium（PLAYWRIGHT_BROWSERS_PATH 下的 chromium-* 目录）
    browsers_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or ""
    if browsers_path and os.path.isdir(browsers_path):
        # 兼容新旧目录结构：chrome-win64（新版）/ chrome-win（旧版）
        subdirs = ("chrome-win64", "chrome-win") if os.name == "nt" else ("chrome-linux",)
        exe_name = "chrome.exe" if os.name == "nt" else "chrome"
        for name in os.listdir(browsers_path):
            if name.startswith("chromium-"):
                for sub in subdirs:
                    exe = os.path.join(browsers_path, name, sub, exe_name)
                    if os.path.isfile(exe):
                        return True
    return False


def status_dict() -> dict:
    """给前端 /api/publish/status 用：返回当前浏览器引擎命中情况。"""
    resolved = resolve_browser()
    return {
        "ready": is_ready(),
        "kind": resolved.kind.value,
        "label": resolved.display_label,
        "channel": resolved.channel,
        "has_local_chrome": _windows_local_chrome_path() is not None,
        "has_local_edge": _windows_local_edge_path() is not None,
        # 包内 Chromium 是否可用（与 PLAYWRIGHT_BROWSERS_PATH 绑定）
        "has_bundled_chromium": bool(
            (os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "")
            and os.path.isdir(os.environ["PLAYWRIGHT_BROWSERS_PATH"])
        ),
    }
