"""音频库账号 Cookie / 登录态持久化（仿 publisher/_cookie.py）。

cookie 落盘：<writable_backend_root>/data/audio_cookies/<source>/<account>.json

网易云 cookie 文件格式（双份，便于 provider 读 + 重登复用）：
    {
      "cookies": {"MUSIC_U": "...", "__csrf": "...", ...},  # provider 读这个
      "storage_state": {...},                                # patchright 扫码登录产物
      "login_info": {"userId": ..., "nickname": ..., "vipType": ...}
    }

酷我免登录，无 cookie 文件；账号面板里酷我账号的 login_status 固定 'guest'。

被 worker 子进程和主进程共享，故不依赖 FastAPI。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from app.utils.paths import get_writable_backend_root

logger = logging.getLogger("audio_library.cookie")


def _cookies_root() -> Path:
    """cookie 存储根目录：<writable_backend_root>/data/audio_cookies。"""
    return get_writable_backend_root() / "data" / "audio_cookies"


def cookie_dir_for(source: str) -> Path:
    """某个音乐源下所有账号 cookie 所在目录。"""
    d = _cookies_root() / source
    d.mkdir(parents=True, exist_ok=True)
    return d


def cookie_file_for(source: str, account: str = "main") -> Path:
    """某个音乐源某账号的 cookie 文件绝对路径。account 做清洗防穿越。"""
    safe = "".join(c for c in account if c.isalnum() or c in ("_", "-")) or "main"
    return cookie_dir_for(source) / f"{safe}.json"


def load_cookie_bundle(source: str, account: str = "main") -> Optional[dict]:
    """读取账号 cookie 文件全部内容（含 cookies / storage_state / login_info）。

    文件不存在返回 None。
    """
    f = cookie_file_for(source, account)
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("读取 cookie 文件失败 %s: %s", f, e)
        return None


def list_accounts(source: str) -> list[dict]:
    """列出某音乐源已登录的账号（按 cookie 文件存在性 + 修改时间粗判登录态）。

    返回 [{"account": "main", "cookie_file": "...", "login_status": "logged_in"}]。
    精确判定需各 provider 的 check_login（如网易云调 /api/nuser/account/get）。
    """
    result: list[dict] = []
    d = _cookies_root() / source
    if not d.is_dir():
        return result
    for f in sorted(d.glob("*.json")):
        result.append({
            "account": f.stem,
            "cookie_file": str(f),
            "login_status": "logged_in",  # 粗判，精确判定走 /accounts/{source}/check
        })
    return result


def remove_account(source: str, account: str) -> bool:
    """删除某账号的 cookie 文件。返回是否实际删除了。"""
    f = cookie_file_for(source, account)
    if f.exists():
        try:
            f.unlink()
            return True
        except OSError:
            return False
    return False


def has_account(source: str, account: str = "main") -> bool:
    return cookie_file_for(source, account).exists()


def is_logged_in(source: str, account: str = "main") -> bool:
    """粗判：cookie 文件存在即视为已登录。酷我免登录，永远 False（用 guest 状态）。"""
    return has_account(source, account)
