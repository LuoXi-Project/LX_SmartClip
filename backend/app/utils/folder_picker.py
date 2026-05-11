"""本机原生文件夹选择（供设置页配置路径）；需在运行后端的机器上弹出对话框。"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from typing import Optional

logger = logging.getLogger(__name__)


def pick_folder_native_blocking(prompt: str = "选择文件夹") -> Optional[str]:
    """
    阻塞调用系统文件夹对话框；取消或失败时返回 None。
    Windows：PowerShell + WinForms；macOS：osascript；Linux：zenity（若可用）。
    """
    if sys.platform == "win32":
        return _pick_folder_windows(prompt)
    if sys.platform == "darwin":
        return _pick_folder_macos(prompt)
    return _pick_folder_linux_zenity(prompt)


def _pick_folder_windows(prompt: str) -> Optional[str]:
    safe = (prompt or "选择文件夹").replace("'", "''")
    ps = rf"""
Add-Type -AssemblyName System.Windows.Forms
$f = New-Object System.Windows.Forms.FolderBrowserDialog
$f.Description = '{safe}'
$f.ShowNewFolderButton = $true
if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
    [Console]::Out.WriteLine($f.SelectedPath)
}}
"""
    ps_exe = shutil.which("powershell.exe") or shutil.which("powershell")
    if not ps_exe:
        logger.warning("未找到 powershell，无法打开文件夹选择框")
        return None
    try:
        kw: dict = dict(
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        if sys.platform == "win32":
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        r = subprocess.run(
            [ps_exe, "-NoProfile", "-STA", "-NonInteractive", "-Command", ps],
            **kw,
        )
        out = (r.stdout or "").strip()
        if out and os.path.isdir(out):
            return os.path.normpath(out)
    except Exception as e:
        logger.warning("Windows 文件夹对话框失败: %s", e)
    return None


def _pick_folder_macos(prompt: str) -> Optional[str]:
    safe = (prompt or "选择文件夹").replace("\\", "\\\\").replace('"', '\\"')
    script = f'return POSIX path of (choose folder with prompt "{safe}")'
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=600,
        )
        out = (r.stdout or "").strip()
        if out and os.path.isdir(out):
            return os.path.normpath(out)
    except Exception as e:
        logger.warning("macOS 文件夹对话框失败: %s", e)
    return None


def _pick_folder_linux_zenity(prompt: str) -> Optional[str]:
    zen = shutil.which("zenity") or shutil.which("kdialog")
    if not zen:
        logger.warning("未找到 zenity/kdialog，无法打开文件夹选择框")
        return None
    try:
        if os.path.basename(zen).lower() == "zenity":
            r = subprocess.run(
                [zen, "--file-selection", "--directory", f"--title={prompt}"],
                capture_output=True,
                text=True,
                timeout=600,
            )
        else:
            r = subprocess.run(
                [zen, "--getexistingdirectory", "."],
                capture_output=True,
                text=True,
                timeout=600,
            )
        out = (r.stdout or "").strip()
        if out and os.path.isdir(out):
            return os.path.normpath(out)
    except Exception as e:
        logger.warning("Linux 文件夹对话框失败: %s", e)
    return None

