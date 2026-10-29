"""Agent 行为偏好（config 表存取）：思维链开关等。

独立于 /api/config 的通用键值：用 INSERT OR REPLACE 自建行，
避免依赖 init_db 预置键（PATCH /api/config 对不存在的 key 会 404）。
"""

from __future__ import annotations

from app.db.database import get_db_conn

COT_ENABLED_KEY = "agent_cot_enabled"


async def load_cot_enabled() -> bool:
    """思维链开关；未配置默认开启（保持既有行为）。"""
    db = await get_db_conn()
    try:
        cur = await db.execute("SELECT value FROM config WHERE key = ?", (COT_ENABLED_KEY,))
        row = await cur.fetchone()
        if not row or row["value"] is None or not str(row["value"]).strip():
            return True
        return str(row["value"]).strip().lower() in ("true", "1", "on")
    finally:
        await db.close()


async def save_cot_enabled(enabled: bool) -> None:
    db = await get_db_conn()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO config (key, value, type, label, options) "
            "VALUES (?, ?, 'bool', 'Agent 思维链开关', NULL)",
            (COT_ENABLED_KEY, "true" if enabled else "false"),
        )
        await db.commit()
    finally:
        await db.close()
