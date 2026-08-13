"""音频库账号与任务的数据访问层（仿 publish_db.py，aiosqlite 手写 SQL）。

针对 audio_accounts + audio_tasks 两张表。
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.db.database import get_db_conn

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str = "at") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ── 任务 ──────────────────────────────────────────────────────────────────
async def create_task(
    *,
    job_type: str,
    source: str,
    account: str | None = None,
    payload_json: str = "{}",
) -> str:
    task_id = _new_id("at")
    db = await get_db_conn()
    try:
        await db.execute(
            """INSERT INTO audio_tasks (id, job_type, source, account, payload_json, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (task_id, job_type, source, account, payload_json, _now_iso(), _now_iso()),
        )
        await db.commit()
    finally:
        await db.close()
    return task_id


async def get_task(task_id: str) -> dict | None:
    db = await get_db_conn()
    try:
        cur = await db.execute("SELECT * FROM audio_tasks WHERE id = ?", (task_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def list_tasks(limit: int = 50, offset: int = 0) -> list[dict]:
    db = await get_db_conn()
    try:
        cur = await db.execute(
            "SELECT * FROM audio_tasks ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def update_task(
    task_id: str,
    *,
    status: str | None = None,
    pid: int | None = None,
    payload_json: str | None = None,
    progress_json: str | None = None,
    result_json: str | None = None,
    log_append: str | None = None,
) -> None:
    """更新任务字段（仅传非 None）。log 追加。"""
    sets: list[str] = ["updated_at = ?"]
    params: list = [_now_iso()]
    if status is not None:
        sets.append("status = ?")
        params.append(status)
    if pid is not None:
        sets.append("pid = ?")
        params.append(pid)
    if payload_json is not None:
        sets.append("payload_json = ?")
        params.append(payload_json)
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
        await db.execute(f"UPDATE audio_tasks SET {', '.join(sets)} WHERE id = ?", params)
        await db.commit()
    finally:
        await db.close()


async def set_task_log(task_id: str, log: str) -> None:
    db = await get_db_conn()
    try:
        await db.execute(
            "UPDATE audio_tasks SET log = ?, updated_at = ? WHERE id = ?",
            (log, _now_iso(), task_id),
        )
        await db.commit()
    finally:
        await db.close()


# ── 账号 ──────────────────────────────────────────────────────────────────
async def upsert_account(
    *,
    source: str,
    account: str,
    display_name: str | None = None,
    login_status: str = "logged_in",
    last_error: str | None = None,
) -> None:
    """新增或更新账号登录态。"""
    db = await get_db_conn()
    try:
        existing = await db.execute(
            "SELECT id FROM audio_accounts WHERE source = ? AND account = ?",
            (source, account),
        )
        row = await existing.fetchone()
        now = _now_iso()
        if row:
            sets = ["login_status = ?", "updated_at = ?"]
            params: list = [login_status, now]
            if display_name is not None:
                sets.append("display_name = ?")
                params.append(display_name)
            if last_error is not None:
                sets.append("last_error = ?")
                params.append(last_error)
            elif login_status == "logged_in":
                sets.append("last_error = NULL")
            if login_status == "logged_in":
                sets.append("last_login_at = ?")
                params.append(now)
            params += [source, account]
            await db.execute(
                f"UPDATE audio_accounts SET {', '.join(sets)} WHERE source = ? AND account = ?",
                params,
            )
        else:
            await db.execute(
                """INSERT INTO audio_accounts
                   (id, source, account, display_name, login_status, last_login_at, last_error, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (_new_id("aa"), source, account, display_name, login_status,
                 now if login_status == "logged_in" else None, last_error, now, now),
            )
        await db.commit()
    finally:
        await db.close()


async def list_accounts(source: str | None = None) -> list[dict]:
    db = await get_db_conn()
    try:
        if source:
            cur = await db.execute(
                "SELECT * FROM audio_accounts WHERE source = ? ORDER BY account",
                (source,),
            )
        else:
            cur = await db.execute("SELECT * FROM audio_accounts ORDER BY source, account")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def delete_account(source: str, account: str) -> bool:
    db = await get_db_conn()
    try:
        cur = await db.execute(
            "DELETE FROM audio_accounts WHERE source = ? AND account = ?",
            (source, account),
        )
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def touch_account_used(source: str, account: str) -> None:
    db = await get_db_conn()
    try:
        await db.execute(
            "UPDATE audio_accounts SET last_used_at = ?, updated_at = ? WHERE source = ? AND account = ?",
            (_now_iso(), _now_iso(), source, account),
        )
        await db.commit()
    finally:
        await db.close()


async def get_account(source: str, account: str) -> dict | None:
    db = await get_db_conn()
    try:
        cur = await db.execute(
            "SELECT * FROM audio_accounts WHERE source = ? AND account = ?",
            (source, account),
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def update_display_name(source: str, account: str, display_name: str | None) -> bool:
    db = await get_db_conn()
    try:
        cur = await db.execute(
            "UPDATE audio_accounts SET display_name = ?, updated_at = ? WHERE source = ? AND account = ?",
            (display_name, _now_iso(), source, account),
        )
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()
