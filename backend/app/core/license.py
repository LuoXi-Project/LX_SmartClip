"""卡密鉴权：与 secret.py 对接，卡密持久化在 SQLite config.license_card。

默认并始终「强制鉴权」：缺失 config.json 或未配置 卡密服务器.API地址 时，业务接口一律拒绝，
避免删配置或参数配置绕过。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional, Tuple

import aiosqlite

from app.db.database import DB_PATH

logger = logging.getLogger(__name__)

try:
    import secret as _secret
except ImportError:  # pragma: no cover
    _secret = None  # type: ignore

_SESSION_TTL_SEC = 3600
_last_ok_monotonic: float = 0.0

def has_card_server_config() -> bool:
    if _secret is None:
        return False
    cfg = _secret.get_config()
    srv = cfg.get("卡密服务器") or {}
    return bool((srv.get("API地址") or "").strip())


def is_license_enforced() -> bool:
    return True


def _session_memory_ok() -> bool:
    if _last_ok_monotonic <= 0:
        return False
    return (time.monotonic() - _last_ok_monotonic) < _SESSION_TTL_SEC


def touch_session() -> None:
    global _last_ok_monotonic
    _last_ok_monotonic = time.monotonic()


def clear_session() -> None:
    global _last_ok_monotonic
    _last_ok_monotonic = 0.0


async def get_stored_card() -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT value FROM config WHERE key = ?", ("license_card",)
        ) as c:
            row = await c.fetchone()
    v = row["value"] if row else ""
    return (v or "").strip()


async def set_stored_card(card: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE config SET value = ? WHERE key = ?",
            (card.strip(), "license_card"),
        )
        await db.commit()


async def ensure_license_valid() -> bool:
    if not is_license_enforced():
        return True
    if not has_card_server_config():
        return False
    card = await get_stored_card()
    if not card:
        return False
    if _session_memory_ok():
        return True
    if _secret is None:
        logger.error("卡密模块未加载（secret 不可用）")
        return False
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, lambda: _secret.card_login(card)
        )
    except Exception as e:
        logger.error("卡密验证异常: %s", e)
        return False
    if result:
        touch_session()
        return True
    clear_session()
    return False


async def activate_license(card: str) -> Tuple[bool, str]:
    card = card.strip()
    if not card:
        return False, "卡密不能为空"
    if is_license_enforced() and not has_card_server_config():
        return (
            False,
            "缺少卡密服务器配置：请在 backend 目录放置 config.json，填写 卡密服务器.API地址",
        )
    if _secret is None:
        return False, "服务端未配置卡密模块"
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, lambda: _secret.card_login(card)
        )
    except Exception as e:
        logger.error("卡密激活异常: %s", e)
        return False, f"验证过程出错: {e}"
    if not result:
        return False, "卡密验证失败，请检查网络与卡密是否正确"
    await set_stored_card(card)
    touch_session()
    return True, "激活成功"


async def unbind_license(card: str) -> Tuple[bool, str, Optional[dict]]:
    card = card.strip()
    if not card:
        return False, "卡密不能为空", None
    if is_license_enforced() and not has_card_server_config():
        return (
            False,
            "缺少卡密服务器配置：请在 backend 目录放置 config.json，填写 卡密服务器.API地址",
            None,
        )
    if _secret is None:
        return False, "服务端未配置卡密模块", None
    loop = asyncio.get_event_loop()
    try:
        raw = await loop.run_in_executor(
            None, lambda: _secret.card_unbind(card)
        )
    except Exception as e:
        logger.error("卡密解绑异常: %s", e)
        return False, f"解绑过程出错: {e}", None
    if isinstance(raw, dict) and raw.get("code") == 0 and raw.get("success"):
        await set_stored_card("")
        clear_session()
        return True, "解绑成功", raw
    if isinstance(raw, dict) and raw.get("ret") == -1:
        return False, str(raw.get("msg") or "解绑失败"), raw
    msg = "解绑失败"
    if isinstance(raw, dict):
        inner = raw.get("data") or {}
        if isinstance(inner, dict) and inner.get("msg"):
            msg = str(inner["msg"])
    return False, msg, raw if isinstance(raw, dict) else None
