"""Cookie / storage_state 持久化管理。

social-auto-upload 用 Playwright 的 storage_state JSON 文件存登录态（含 cookie + localStorage）。
本模块统一管理这些文件的路径，落在 <home>/data/cookies/<platform>/<account>.json。

被 worker 子进程和主进程共享，故不依赖 FastAPI。
"""
from __future__ import annotations

import os
from pathlib import Path

from app.utils.paths import get_writable_backend_root


def _cookies_root() -> Path:
    """cookie 存储根目录：<writable_backend_root>/data/cookies。

    frozen 下 writable_backend_root = exe 同级目录（由 start_backend.py 设 LX_SMARTCLIP_HOME）。
    """
    return get_writable_backend_root() / "data" / "cookies"


def cookie_dir_for(platform: str) -> Path:
    """某个平台下所有账号 cookie 所在目录。"""
    d = _cookies_root() / platform
    d.mkdir(parents=True, exist_ok=True)
    return d


def cookie_file_for(platform: str, account: str = "main") -> Path:
    """某个平台某账号的 storage_state 文件绝对路径。"""
    # account 做简单清洗，避免路径穿越
    safe = "".join(c for c in account if c.isalnum() or c in ("_", "-")) or "main"
    return cookie_dir_for(platform) / f"{safe}.json"


def list_accounts(platform: str) -> list[dict]:
    """列出某平台已登录的账号（按 cookie 文件存在性 + 修改时间）。

    返回 [{"account": "main", "cookie_file": "...", "login_status": "logged_in|expired"}]。
    login_status 这里仅依据文件是否存在粗判；精确判定需各平台 check 逻辑。
    """
    result: list[dict] = []
    d = cookie_dir_for(platform)
    for f in sorted(d.glob("*.json")):
        result.append({
            "account": f.stem,
            "cookie_file": str(f),
            "login_status": "logged_in",  # 粗判，精确判定走 /accounts/{p}/check
        })
    return result


def remove_account(platform: str, account: str) -> bool:
    """删除某账号的 cookie 文件。返回是否实际删除了。"""
    f = cookie_file_for(platform, account)
    if f.exists():
        try:
            f.unlink()
            return True
        except OSError:
            return False
    return False


def has_account(platform: str, account: str = "main") -> bool:
    return cookie_file_for(platform, account).exists()


def is_logged_in(platform: str, account: str = "main") -> bool:
    """粗判是否已登录（cookie 文件存在即视为已登录，精确判定各平台单独实现）。"""
    return has_account(platform, account)
