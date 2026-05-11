import asyncio
import logging

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.db.database import get_db_conn
from app.models.config import ConfigUpdate, ModelsRequest
from app.utils.folder_picker import pick_folder_native_blocking
from app.utils.paths import normalize_jianying_parent_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"])

_CONFIG_EXCLUDE_KEYS = frozenset({"license_card"})


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
            if row["key"] not in _CONFIG_EXCLUDE_KEYS
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
        if body.key in _CONFIG_EXCLUDE_KEYS:
            raise HTTPException(
                status_code=403,
                detail="该配置项请使用 /api/license 接口管理",
            )
        val = body.value
        if body.key == "jianying_draft_parent_dir":
            val = normalize_jianying_parent_dir(val or "")
        await db.execute(
            "UPDATE config SET value = ? WHERE key = ?",
            (val, body.key),
        )
        await db.commit()
        return {"key": body.key, "value": val}
    finally:
        await db.close()


@router.post("/pick-folder")
async def pick_folder(request: Request):
    """
    在本机弹出系统文件夹选择框，返回规范化后的绝对路径。
    仅允许访问本机后端（127.0.0.1 / ::1），避免远程调用误触服务端桌面。
    """
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1"):
        raise HTTPException(
            status_code=403,
            detail="文件夹选择仅在后端运行于本机且浏览器访问本机地址时可用。",
        )
    raw = await asyncio.to_thread(
        pick_folder_native_blocking,
        "选择剪映草稿父目录（导出的草稿子文件夹将创建在此目录下）",
    )
    if not raw:
        return {"path": "", "cancelled": True}
    return {"path": normalize_jianying_parent_dir(raw), "cancelled": False}


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
