from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx
from app.db.database import get_db_conn
import logging

logger = logging.getLogger(__name__)

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


class ModelsRequest(BaseModel):
    base_url: str
    api_key: str


@router.post("/models")
async def proxy_list_models(body: ModelsRequest):
    """代理请求第三方 API 的 /models 接口，避免浏览器 CORS/DNS 限制"""
    url = body.base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {body.api_key}"}
    logger.info(f"请求 URL: {url}")
    logger.info(f"请求 Headers: {headers}")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)
        data = resp.json()
        # 兼容 OpenAI 格式 {data: [{id: ...}]} 和 {models: [{id: ...}]}
        if isinstance(data.get("data"), list):
            models = sorted(m["id"] for m in data["data"] if "id" in m)
        elif isinstance(data.get("models"), list):
            models = sorted(m["id"] for m in data["models"] if "id" in m)
        else:
            models = []
        return {"models": models}
    except httpx.RequestError as e:
        logger.error(f"请求失败: {e}")
        raise HTTPException(status_code=502, detail=f"请求失败: {str(e)}")
