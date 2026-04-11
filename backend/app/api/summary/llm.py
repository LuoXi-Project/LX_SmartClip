"""视频总结：LLM 调用封装。"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import HTTPException

from app.core.llm import LLMClient
from app.core.llm.response_utils import extract_json_object

from .utils import strip_markdown_fences

logger = logging.getLogger(__name__)


async def call_llm_json(llm: LLMClient, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    raw = await llm.chat(messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}])
    cleaned = extract_json_object(raw if isinstance(raw, str) else "")
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error("summary json parse failed: %s", e)
        raise HTTPException(status_code=502, detail="LLM 返回 JSON 解析失败")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="LLM 返回 JSON 非对象")
    return data


async def call_llm_markdown(llm: LLMClient, *, system_prompt: str, user_prompt: str) -> str:
    raw = await llm.chat(messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}])
    s = raw if isinstance(raw, str) else str(raw or "")
    s = strip_markdown_fences(s.strip())
    return s.strip() + "\n"
