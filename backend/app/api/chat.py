import logging
import aiosqlite
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.models.chat import ChatRequest, ChatMessage

from app.db.database import DB_PATH
from app.core.llm import LLMConfig, LLMClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/completions")
async def chat_completions(req: ChatRequest):
    """
    使用系统已配置的 LLM provider 进行对话。
    读取 llm_base_url / llm_api_key / llm_model (或 vlm_model) 作为对话模型。
    支持流式 (stream=true) 和非流式两种模式。
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cfg = await LLMConfig.get_llm_params_with_defaults(
                db,
                base_url_key="llm_base_url",
                api_key_key="llm_api_key",
                model_key="llm_model",
                fallback_model_key="vlm_model",
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    messages = [
        {"role": m.role, "content": m.content} for m in req.messages
    ]

    if req.stream:
        async def _stream():
            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(
                    api_key=cfg["api_key"],
                    base_url=cfg["base_url"],
                    timeout=600.0,
                )
                stream = await client.chat.completions.create(
                    model=cfg["model"],
                    messages=messages,
                    temperature=cfg["temperature"],
                    max_tokens=cfg["max_tokens"],
                    stream=True,
                )
                async for chunk in stream:
                    # 转为 SSE 格式透传
                    import json as _json
                    data = chunk.model_dump()
                    yield ("data: " + _json.dumps(data, ensure_ascii=False) + "\n\n").encode()
                yield b"data: [DONE]\n\n"
            except Exception as e:
                import json as _json
                logger.error("Chat stream error: %s", e)
                yield ("data: " + _json.dumps({
                    "error": "stream_error",
                    "detail": str(e),
                }) + "\n\n").encode()

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    else:
        try:
            llm = LLMClient(
                base_url=cfg["base_url"],
                api_key=cfg["api_key"],
                model=cfg["model"],
                temperature=cfg["temperature"],
                max_tokens=cfg["max_tokens"],
            )
            content = await llm.chat(messages)
            return {
                "choices": [{
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                    "index": 0,
                }]
            }
        except Exception as e:
            logger.error("Chat request error: %s", e)
            raise HTTPException(status_code=502, detail=f"请求 LLM 失败: {str(e)}")
