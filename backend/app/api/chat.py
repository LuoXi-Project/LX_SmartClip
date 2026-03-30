import json as _json
import logging
import urllib.request as _urllib
from typing import Optional

import aiosqlite
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.db.database import DB_PATH

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _get_proxy() -> Optional[str]:
    """读取系统代理，httpx 不会自动使用系统代理，需要手动传入。"""
    proxies = _urllib.getproxies()
    return proxies.get("https") or proxies.get("http") or None


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    stream: Optional[bool] = True


async def _read_cfg(db: aiosqlite.Connection, key: str, default: str = "") -> str:
    async with db.execute("SELECT value FROM config WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
    return row[0] if row else default


@router.post("/completions")
async def chat_completions(req: ChatRequest):
    """
    使用系统已配置的 VLM/LLM provider 进行对话。
    读取 vlm_base_url / vlm_api_key / vlm_model (或 llm_model) 作为对话模型。
    支持流式 (stream=true) 和非流式两种模式。
    """
    async with aiosqlite.connect(DB_PATH) as db:
        base_url  = await _read_cfg(db, "vlm_base_url",  "")
        api_key   = await _read_cfg(db, "vlm_api_key",   "")
        llm_model = await _read_cfg(db, "llm_model",     "")
        vlm_model = await _read_cfg(db, "vlm_model",     "")

    model = llm_model or vlm_model
    if not base_url or not api_key or not model:
        raise HTTPException(
            status_code=400,
            detail="LLM 未配置，请在设置页面配置 VLM Base URL / API Key / 模型名称"
        )

    endpoint = base_url.rstrip("/") + "/chat/completions"
    req_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    proxy = _get_proxy()
    # logger.info("Chat endpoint: %s, model: %s, proxy: %s", endpoint, model, proxy)

    messages = [
        {"role": m.role, "content": m.content} for m in req.messages
    ]

    body = {
        "model": model,
        "messages": messages,
        "stream": req.stream,
        "temperature": 0.7,
        "max_tokens": 20480,
    }

    if req.stream:
        async def _stream():
            try:
                async with httpx.AsyncClient(timeout=60, proxy=proxy) as client:
                    async with client.stream("POST", endpoint, headers=req_headers, json=body) as resp:
                        if resp.status_code != 200:
                            err = await resp.aread()
                            logger.error("LLM stream error %s: %s", resp.status_code, err[:200])
                            yield ("data: " + _json.dumps({
                                "error": str(resp.status_code),
                                "detail": err[:100].decode(errors="replace")
                            }) + "\n\n").encode()
                            return
                        async for chunk in resp.aiter_bytes():
                            yield chunk
            except httpx.RequestError as e:
                logger.error("Chat stream connect error: %s", e)
                yield ("data: " + _json.dumps({
                    "error": "connect_error",
                    "detail": f"无法连接到 LLM 服务: {e}"
                }) + "\n\n").encode()

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    else:
        try:
            async with httpx.AsyncClient(timeout=60, proxy=proxy) as client:
                resp = await client.post(endpoint, headers=req_headers, json=body)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text[:300])
            return resp.json()
        except httpx.RequestError as e:
            logger.error("Chat request error: %s", e)
            raise HTTPException(status_code=502, detail=f"请求 LLM 失败: {str(e)}")
