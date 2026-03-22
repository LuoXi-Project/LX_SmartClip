from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.db.database import get_db_conn

router = APIRouter(prefix="/api/config", tags=["config"])


class ConfigUpdate(BaseModel):
    key: str
    value: str


@router.get("")
async def get_config():
    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT key, value, type, label, options FROM config"
        )
        rows = await cursor.fetchall()
        return {
            row["key"]: {
                "value": row["value"],
                "type": row["type"],
                "label": row["label"],
                "options": row["options"],
            }
            for row in rows
        }
    finally:
        await db.close()


@router.patch("")
async def update_config(body: ConfigUpdate):
    db = await get_db_conn()
    try:
        # 先确认 key 存在
        cursor = await db.execute(
            "SELECT key FROM config WHERE key = ?", (body.key,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(
                status_code=404, detail=f"Config key '{body.key}' not found"
            )
        # 执行更新
        await db.execute(
            "UPDATE config SET value = ? WHERE key = ?",
            (body.value, body.key),
        )
        await db.commit()
        return {"key": body.key, "value": body.value}
    finally:
        await db.close()
