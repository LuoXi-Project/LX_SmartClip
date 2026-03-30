"""copy_gen.py — 文案智能生成 API

根据选中视频的 ASR + VLM 内容，调用 LLM 自动生成文案段落。
支持流式 (SSE) 输出。
"""
from __future__ import annotations

import json
import logging
import urllib.request as _urllib
from typing import List, Optional

import aiosqlite
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.db.database import DB_PATH

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/copy-gen", tags=["copy-gen"])


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

def _get_proxy() -> Optional[str]:
    proxies = _urllib.getproxies()
    return proxies.get("https") or proxies.get("http") or None


async def _read_cfg(db: aiosqlite.Connection, key: str, default: str = "") -> str:
    async with db.execute("SELECT value FROM config WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
    return row[0] if row else default


# ────────────────────────────────────────────────────────────
# Schema
# ────────────────────────────────────────────────────────────

class CopyGenRequest(BaseModel):
    video_ids: List[str] = Field(..., description="选中视频 ID 列表")
    user_prompt: str = Field(..., min_length=1, description="用户诉求 / 模板指令")
    style: Optional[str] = Field(None, description="风格提示，如 '活泼' '专业' '悬疑'")
    max_segments: int = Field(5, ge=1, le=20, description="期望拆分段落数")
    stream: bool = Field(True, description="是否流式输出")


# ────────────────────────────────────────────────────────────
# Context builder
# ────────────────────────────────────────────────────────────

async def _build_video_context(db: aiosqlite.Connection, video_ids: List[str]) -> str:
    """
    从数据库查询选中视频下所有 clip 的 ASR 台词与 VLM 画面描述，
    拼成结构化文本作为 LLM system context。
    最多取前 60 个片段，每段截断到 200 字符，避免 context 过长。
    """
    placeholders = ",".join(["?"] * len(video_ids))
    sql = f"""
        SELECT c.id, v.name AS video_name,
               c.start_time, c.end_time,
               c.asr_text, c.vlm_description
        FROM clips c
        JOIN videos v ON v.id = c.video_id
        WHERE c.video_id IN ({placeholders})
          AND (c.asr_text IS NOT NULL OR c.vlm_description IS NOT NULL)
        ORDER BY v.name, c.start_time
        LIMIT 60
    """
    async with db.execute(sql, video_ids) as cur:
        rows = await cur.fetchall()

    if not rows:
        return "（未找到有效的 ASR 或 VLM 识别内容）"

    lines: list[str] = []
    cur_video = None
    for row in rows:
        if row["video_name"] != cur_video:
            cur_video = row["video_name"]
            lines.append(f"\n【视频：{cur_video}】")
        t0 = _fmt_time(row["start_time"])
        t1 = _fmt_time(row["end_time"])
        asr = (row["asr_text"] or "").strip()[:200]
        vlm = (row["vlm_description"] or "").strip()[:200]
        parts = []
        if asr:
            parts.append(f"台词：{asr}")
        if vlm:
            parts.append(f"画面：{vlm}")
        if parts:
            lines.append(f"  [{t0}→{t1}] " + " | ".join(parts))

    return "\n".join(lines)


def _fmt_time(s: float) -> str:
    m, sec = divmod(int(s), 60)
    return f"{m}:{sec:02d}"


# ────────────────────────────────────────────────────────────
# Prompt builder
# ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """你是一位专业的视频文案创作师。
用户会给你提供一段或多段视频的 ASR 语音识别台词和 VLM 画面描述内容，
以及用户的创作诉求（如主题、风格、目的）。

你的任务：
1. 深度理解视频内容（台词 + 画面）。
2. 根据用户诉求，撰写吸引人的视频文案。
3. 将文案按段落拆分，每段对应一个视频片段或一个叙事节拍。
4. 每段之间用空行分隔，不要有编号或序号前缀。
5. 文案要自然流畅、有感染力，符合短视频风格。
6. 只输出文案内容，不要输出任何解释或元信息。"""


def _build_user_message(context: str, req: CopyGenRequest) -> str:
    style_hint = f"\n风格要求：{req.style}" if req.style else ""
    return (
        f"以下是视频的识别内容：\n{context}\n\n"
        f"---\n"
        f"用户诉求：{req.user_prompt}{style_hint}\n"
        f"请将文案拆分为约 {req.max_segments} 段（每段空行分隔），每段对应一个叙事节拍。"
    )


# ────────────────────────────────────────────────────────────
# Route
# ────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate_copy(req: CopyGenRequest):
    """
    根据选中视频内容 + 用户诉求，通过 LLM 生成文案段落。
    支持 stream=true 返回 SSE，stream=false 返回 JSON。
    """
    if not req.video_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个视频")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        base_url = await _read_cfg(db, "vlm_base_url", "")
        api_key  = await _read_cfg(db, "vlm_api_key",  "")
        llm_model = await _read_cfg(db, "llm_model",   "")
        vlm_model = await _read_cfg(db, "vlm_model",   "")
        model = llm_model or vlm_model

        if not base_url or not api_key or not model:
            raise HTTPException(
                status_code=400,
                detail="LLM 未配置，请在设置页面配置 VLM Base URL / API Key / 模型名称"
            )

        context = await _build_video_context(db, req.video_ids)

    endpoint = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    proxy = _get_proxy()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": _build_user_message(context, req)},
    ]
    body = {
        "model": model,
        "messages": messages,
        "stream": req.stream,
        "temperature": 0.85,
        "max_tokens": 20480,
    }

    if req.stream:
        async def _sse():
            try:
                async with httpx.AsyncClient(timeout=90, proxy=proxy) as client:
                    async with client.stream("POST", endpoint, headers=headers, json=body) as resp:
                        if resp.status_code != 200:
                            err = await resp.aread()
                            yield ("data: " + json.dumps({
                                "error": str(resp.status_code),
                                "detail": err[:120].decode(errors="replace")
                            }) + "\n\n").encode()
                            return
                        async for chunk in resp.aiter_bytes():
                            yield chunk
            except httpx.RequestError as e:
                logger.error("copy_gen stream error: %s", e)
                yield ("data: " + json.dumps({
                    "error": "connect_error",
                    "detail": f"无法连接到 LLM 服务: {e}"
                }) + "\n\n").encode()

        return StreamingResponse(
            _sse(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    else:
        try:
            async with httpx.AsyncClient(timeout=90, proxy=proxy) as client:
                resp = await client.post(endpoint, headers=headers, json=body)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail=resp.text[:300])
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return {"copy": content}
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"请求 LLM 失败: {str(e)}")
