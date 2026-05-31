import asyncio
import sqlite3

from app.db.database import DB_PATH
from app.db.init_db import init_db
from app.agent.session_store import create_session, get_session, patch_workspace


async def main() -> None:
    await init_db()
    conn = sqlite3.connect(DB_PATH)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    conn.close()
    assert "agent_sessions" in tables
    assert "agent_messages" in tables

    ws = await create_session(title="Test", video_ids=["v1"])
    ws2 = await patch_workspace(ws.session_id, {"title": "Updated"})
    assert ws2.title == "Updated"
    loaded = await get_session(ws.session_id)
    assert loaded is not None
    assert loaded.title == "Updated"
    print("agent session_store ok", ws.session_id)


if __name__ == "__main__":
    asyncio.run(main())
