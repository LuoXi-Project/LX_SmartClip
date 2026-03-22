import aiosqlite
import os
from typing import AsyncGenerator

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "smartclip.db")
DB_PATH = os.path.abspath(DB_PATH)


async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def get_db_conn() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db
