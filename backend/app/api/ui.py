"""UI 偏好（新手指引等），存于 config 表，与端口/前端 origin 无关。"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db.database import get_db_conn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ui", tags=["ui"])

ONBOARDING_CONFIG_KEY = "ui_onboarding_v1"
ONBOARDING_VERSION = 1


class OnboardingPayload(BaseModel):
    status: str = Field(..., description="pending | completed | skipped")
    version: int = ONBOARDING_VERSION


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_onboarding(raw: str | None) -> dict:
    if not raw or not str(raw).strip():
        return {"version": ONBOARDING_VERSION, "status": "pending", "updated_at": None}
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("not object")
    except (json.JSONDecodeError, ValueError):
        logger.warning("ui_onboarding_v1 解析失败，回退为 pending")
        return {"version": ONBOARDING_VERSION, "status": "pending", "updated_at": None}
    status = str(data.get("status") or "pending")
    if status not in ("pending", "completed", "skipped"):
        status = "pending"
    return {
        "version": int(data.get("version") or ONBOARDING_VERSION),
        "status": status,
        "updated_at": data.get("updated_at"),
    }


async def _ensure_onboarding_key(db) -> None:
    await db.execute(
        "INSERT OR IGNORE INTO config (key, value, type, label, options) VALUES (?,?,?,?,?)",
        (ONBOARDING_CONFIG_KEY, "", "string", "新手指引状态（内部）", None),
    )


@router.get("/onboarding")
async def get_onboarding():
    db = await get_db_conn()
    try:
        await _ensure_onboarding_key(db)
        cursor = await db.execute(
            "SELECT value FROM config WHERE key = ?", (ONBOARDING_CONFIG_KEY,)
        )
        row = await cursor.fetchone()
        return _parse_onboarding(row["value"] if row else None)
    finally:
        await db.close()


@router.put("/onboarding")
async def put_onboarding(body: OnboardingPayload):
    if body.status not in ("pending", "completed", "skipped"):
        raise HTTPException(status_code=400, detail="status 无效")
    payload = {
        "version": ONBOARDING_VERSION,
        "status": body.status,
        "updated_at": _now_iso(),
    }
    raw = json.dumps(payload, ensure_ascii=False)
    db = await get_db_conn()
    try:
        await _ensure_onboarding_key(db)
        cursor = await db.execute(
            "SELECT key FROM config WHERE key = ?", (ONBOARDING_CONFIG_KEY,)
        )
        if await cursor.fetchone() is None:
            raise HTTPException(status_code=404, detail="onboarding config missing")
        await db.execute(
            "UPDATE config SET value = ? WHERE key = ?",
            (raw, ONBOARDING_CONFIG_KEY),
        )
        await db.commit()
        return payload
    finally:
        await db.close()
