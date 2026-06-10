from __future__ import annotations

from collections.abc import Awaitable, Callable

import aiosqlite

MigrationFn = Callable[[aiosqlite.Connection], Awaitable[None]]


async def migrate_v1_baseline(db: aiosqlite.Connection) -> None:
    """v0 -> v1：基线版本，历史兼容逻辑仍在 init_db 中执行。"""
    _ = db


# 版本号 -> 迁移函数（从 version-1 升到 version）
MIGRATIONS: dict[int, MigrationFn] = {
    1: migrate_v1_baseline,
}
