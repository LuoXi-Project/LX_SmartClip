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


def build_launch_kwargs(resolved: ResolvedBrowser, headless: bool, proxy: dict | None = None) -> dict:
    """根据解析结果生成 patchright.chromium.launch() 的 kwargs。

    patchright 在用 channel 模式时会自动定位本地安装的 Chrome/Edge，
    无需 executable_path；走包内 Chromium 时 channel=None 由 patchright 自行查找。

    Args:
        proxy: patchright 的 proxy 字典 {server, username?, password?}，None=不走代理。
            用于解决本机开了代理（VPN）但自动化浏览器不继承系统代理、
            导致目标站静态资源（如 B站 s1.hdslb.com 的 JS chunk）加载失败的问题。
    """
    kwargs: dict = {
        "headless": headless,
        "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    }
    if resolved.channel:
        kwargs["channel"] = resolved.channel
    if resolved.executable_path:
        kwargs["executable_path"] = resolved.executable_path
    if proxy and proxy.get("server"):
        kwargs["proxy"] = proxy
    return kwargs


def _detect_system_proxy() -> str | None:
    """探测系统代理地址，返回形如 http://127.0.0.1:7890 的字符串，无则 None。

    探测顺序：
    1. 环境变量 HTTP_PROXY / HTTPS_PROXY（很多代理工具/CLI 会设置）
    2. Windows 注册表 IE/系统代理设置（ProxyEnable + ProxyServer，覆盖系统级 GUI 代理）

    用于自动化浏览器继承系统代理，避免目标站静态资源（B站 s1.hdslb.com 等）
    因未走代理而 ChunkLoadError。
    """
    # 1) 环境变量
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val

    # 2) Windows 注册表：系统级代理（IE 选项 / Windows 设置里的代理）
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            ) as k:
                enabled, _ = winreg.QueryValueEx(k, "ProxyEnable")
                if not enabled:
                    return None
                server, _ = winreg.QueryValueEx(k, "ProxyServer")
                server = (server or "").strip()
                if not server:
                    return None
                # ProxyServer 可能是 "127.0.0.1:7890" 或 "http=...;https=..." 多协议格式
                if "=" in server:
                    # 取 https 优先，否则 http，否则第一个
                    parts = dict(p.split("=", 1) for p in server.split(";") if "=" in p)
                    for proto in ("https", "http"):
                        if parts.get(proto):
                            server = parts[proto]
                            break
                    else:
                        server = next(iter(parts.values()))
                # 补 scheme
                if "://" not in server:
                    server = "http://" + server
                return server
        except Exception:
            return None
    return None


def get_publish_proxy(explicit: str | None = None) -> dict | None:
    """获取发布浏览器要用的代理（patchright proxy 结构）。

    Args:
        explicit: 用户在设置页填的代理地址（publish_browser_proxy）。
                  留空 → 自动探测系统代理；填 "none"/"off"/"direct" → 显式不走代理；
                  填地址 → 强制用该地址。
    Returns:
        patchright proxy dict {server} 或 None（不走代理）。
    """
    raw = (explicit or "").strip()
    if not raw:
        # 留空：自动探测系统代理
        server = _detect_system_proxy()
        return {"server": server} if server else None
    if raw.lower() in ("none", "off", "direct", "无", "禁用"):
        return None
    # 补 scheme
    if "://" not in raw:
        raw = "http://" + raw
    return {"server": raw}


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
        # 当前会探测到的代理（供前端展示，便于用户确认代理是否生效）
        "detected_proxy": _detect_system_proxy(),
    }


async def read_publish_proxy_config() -> dict | None:
    """读 config 表的 publish_browser_proxy，返回 patchright proxy dict 或 None。

    留空 → 自动探测系统代理；填 none → 直连；填地址 → 强制。
    供 generic.py / douyin.py 在 launch 前统一调用。
    """
    try:
        import aiosqlite
        from app.db.database import DB_PATH
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT value FROM config WHERE key = ?", ("publish_browser_proxy",)
            ) as cur:
                row = await cur.fetchone()
        explicit = (row[0] if row else "") or ""
    except Exception:
        explicit = ""
    return get_publish_proxy(explicit)
