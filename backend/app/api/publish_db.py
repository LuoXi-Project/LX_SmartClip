"""发布任务与账号的数据访问层（aiosqlite 手写 SQL）。

仿 process_db.py 范式：get_db_conn() + dict(row)。
任务表存进度/结果，账号表存登录态。
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from app.db.database import get_db_conn

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str = "pt") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ── 任务 ──────────────────────────────────────────────────────────────────
async def create_task(
    *,
    video_path: str,
    video_name: str | None,
    items_json: str,
) -> str:
    """创建发布任务记录，返回 task_id。"""
    task_id = _new_id("pt")
    db = await get_db_conn()
    try:
        await db.execute(
            """INSERT INTO publish_tasks (id, video_path, video_name, items_json, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
            (task_id, video_path, video_name, items_json, _now_iso(), _now_iso()),
        )
        await db.commit()
    finally:
        await db.close()
    return task_id


async def get_task(task_id: str) -> dict | None:
    db = await get_db_conn()
    try:
        cur = await db.execute("SELECT * FROM publish_tasks WHERE id = ?", (task_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def list_tasks(limit: int = 50, offset: int = 0) -> list[dict]:
    db = await get_db_conn()
    try:
        cur = await db.execute(
            "SELECT * FROM publish_tasks ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def update_task_status(
    task_id: str,
    *,
    status: str | None = None,
    pid: int | None = None,
    progress_json: str | None = None,
    result_json: str | None = None,
    log_append: str | None = None,
) -> None:
    """更新任务字段（仅传非 None 的字段）。log 用追加方式。"""
    sets: list[str] = ["updated_at = ?"]
    params: list = [_now_iso()]
    if status is not None:
        sets.append("status = ?")
        params.append(status)
    if pid is not None:
        sets.append("pid = ?")
        params.append(pid)
    if progress_json is not None:
        sets.append("progress_json = ?")
        params.append(progress_json)
    if result_json is not None:
        sets.append("result_json = ?")
        params.append(result_json)

    if log_append:
        sets.append("log = log || ?")
        params.append(log_append)

    params.append(task_id)
    db = await get_db_conn()
    try:
        await db.execute(f"UPDATE publish_tasks SET {', '.join(sets)} WHERE id = ?", params)
        await db.commit()
    finally:
        await db.close()


async def set_task_log(task_id: str, log: str) -> None:
    """整体覆盖任务日志（而非追加）。"""
    db = await get_db_conn()
    try:
        await db.execute(
            "UPDATE publish_tasks SET log = ?, updated_at = ? WHERE id = ?",
            (log, _now_iso(), task_id),
        )
        await db.commit()
    finally:
        await db.close()


# ── 账号 ──────────────────────────────────────────────────────────────────
async def upsert_account(
    *,
    platform: str,
    account: str,
    display_name: str | None = None,
    login_status: str = "logged_in",
    last_error: str | None = None,
) -> None:
    """新增或更新账号登录态。"""
    db = await get_db_conn()
    try:
        existing = await db.execute(
            "SELECT id FROM publish_accounts WHERE platform = ? AND account = ?",
            (platform, account),
        )
        row = await existing.fetchone()
        now = _now_iso()
        if row:
            sets = ["login_status = ?", "updated_at = ?"]
            params: list = [login_status, now]
            if display_name is not None:
                sets.append("display_name = ?")
                params.append(display_name)
            # last_error 处理：传非 None 字符串 → 更新；登录成功时 → 清空历史错误
            if last_error is not None:
                sets.append("last_error = ?")
                params.append(last_error)
            elif login_status == "logged_in":
                sets.append("last_error = NULL")
            if login_status == "logged_in":
                sets.append("last_login_at = ?")
                params.append(now)
            params += [platform, account]
            await db.execute(
                f"UPDATE publish_accounts SET {', '.join(sets)} WHERE platform = ? AND account = ?",
                params,
            )
        else:
            await db.execute(
                """INSERT INTO publish_accounts
                   (id, platform, account, display_name, login_status, last_login_at, last_error, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_new_id("pa"), platform, account, display_name, login_status,
                 now if login_status == "logged_in" else None, last_error, now, now),
            )
        await db.commit()
    finally:
        await db.close()


async def list_accounts(platform: str | None = None) -> list[dict]:
    db = await get_db_conn()
    try:
        if platform:
            cur = await db.execute(
                "SELECT * FROM publish_accounts WHERE platform = ? ORDER BY account",
                (platform,),
            )
        else:
            cur = await db.execute("SELECT * FROM publish_accounts ORDER BY platform, account")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def delete_account(platform: str, account: str) -> bool:
    db = await get_db_conn()
    try:
        cur = await db.execute(
            "DELETE FROM publish_accounts WHERE platform = ? AND account = ?",
            (platform, account),
        )
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def touch_account_used(platform: str, account: str) -> None:
    """更新账号最后使用时间。"""
    db = await get_db_conn()
    try:
        await db.execute(
            "UPDATE publish_accounts SET last_used_at = ?, updated_at = ? WHERE platform = ? AND account = ?",
            (_now_iso(), _now_iso(), platform, account),
        )
        await db.commit()
    finally:
        await db.close()


async def get_account(platform: str, account: str) -> dict | None:
    """精确查单个账号记录，不存在返回 None。"""
    db = await get_db_conn()
    try:
        cur = await db.execute(
            "SELECT * FROM publish_accounts WHERE platform = ? AND account = ?",
            (platform, account),
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def update_display_name(platform: str, account: str, display_name: str | None) -> bool:
    """更新账号自定义显示名称。

    用户重命名专用：无条件 SET（区别于登录路径的"兜底自动命名"语义）。
    传 None / 空串 → 清空自定义名（回退到自动命名）。返回是否命中。
    """
    db = await get_db_conn()
    try:
        cur = await db.execute(
            "UPDATE publish_accounts SET display_name = ?, updated_at = ? WHERE platform = ? AND account = ?",
            (display_name, _now_iso(), platform, account),
        )
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()
