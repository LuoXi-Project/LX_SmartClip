from __future__ import annotations

import logging

import aiosqlite

from app.db.schema import CURRENT_SCHEMA_VERSION, SCHEMA_META_TABLE, SCHEMA_VERSION_KEY

logger = logging.getLogger(__name__)


async def _table_exists(db: aiosqlite.Connection, name: str) -> bool:
    cur = await db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    )
    row = await cur.fetchone()
    return row is not None


async def _get_schema_version(db: aiosqlite.Connection) -> int | None:
    if not await _table_exists(db, "schema_meta"):
        return None
    cur = await db.execute(
        "SELECT value FROM schema_meta WHERE key = ?",
        (SCHEMA_VERSION_KEY,),
    )
    row = await cur.fetchone()
    if not row:
        return None
    try:
        return int(str(row[0]))
    except (TypeError, ValueError):
        return None


async def _set_schema_version(db: aiosqlite.Connection, version: int) -> None:
    await db.execute(
        """
        INSERT INTO schema_meta (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (SCHEMA_VERSION_KEY, str(version)),
    )


async def _adopt_legacy_database(db: aiosqlite.Connection) -> None:
    """已有业务表但无 schema_meta：视为已完成历史兼容补丁，直接标记为 v1。"""
    has_core = await _table_exists(db, "videos") and await _table_exists(db, "config")
    if not has_core:
        await _set_schema_version(db, 0)
        return
    await _set_schema_version(db, 1)
    logger.info("已采纳 legacy 数据库，schema_version=1")


async def run_migrations(db: aiosqlite.Connection) -> int:
    """
    按序执行 schema 迁移，返回最终 schema 版本。
    新增迁移：在 MIGRATIONS 注册，并在 CURRENT_SCHEMA_VERSION 递增。
    """
    await db.execute(SCHEMA_META_TABLE)

    current = await _get_schema_version(db)
    if current is None:
        await _adopt_legacy_database(db)
        current = await _get_schema_version(db)
        if current is None:
            current = 0

    from app.db.migrations import MIGRATIONS

    while current < CURRENT_SCHEMA_VERSION:
        nxt = current + 1
        fn = MIGRATIONS.get(nxt)
        if fn is None:
            raise RuntimeError(f"缺少 schema 迁移 v{nxt}")
        logger.info("执行数据库迁移 v%s -> v%s", current, nxt)
        await fn(db)
        await _set_schema_version(db, nxt)
        current = nxt

    return current


async def read_installed_schema_version() -> int:
    import aiosqlite

    from app.db.database import DB_PATH

    async with aiosqlite.connect(DB_PATH) as db:
        v = await _get_schema_version(db)
        return v if v is not None else 0
