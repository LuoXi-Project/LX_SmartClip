from __future__ import annotations

import json
import logging

import aiosqlite

from app.agent.prompts.router import ROUTER_SYSTEM
from app.core.llm import LLMClient, LLMConfig
from app.core.llm.response_utils import extract_json_object
from app.db.database import DB_PATH
from app.models.agent import RouterOutput

logger = logging.getLogger(__name__)


async def classify_route(*, user_message: str, workspace_summary: str) -> RouterOutput:
    async with aiosqlite.connect(DB_PATH) as db:
        cfg = await LLMConfig.get_llm_params_with_defaults(
            db,
            base_url_key="llm_base_url",
            api_key_key="llm_api_key",
            model_key="llm_model",
            fallback_model_key="vlm_model",
            default_temperature=0.2,
            default_max_tokens=512,
        )
    llm = LLMClient(**cfg)
    messages = [
        {"role": "system", "content": ROUTER_SYSTEM},
        {
            "role": "user",
            "content": f"【工作区】\n{workspace_summary}\n\n【用户】\n{user_message}",
        },
    ]
    raw = await llm.chat(messages)
    try:
        data = json.loads(extract_json_object(raw))
        return RouterOutput(**data)
    except Exception as e:
        logger.warning("router parse failed: %s raw=%s", e, raw[:200])
        return RouterOutput(route="execute", reason="路由解析失败，按执行处理")
