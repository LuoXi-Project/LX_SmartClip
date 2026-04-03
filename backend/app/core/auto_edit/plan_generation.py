from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError

from app.core.llm import LLMClient
from app.core.llm.prompts.auto_edit_plan import SYSTEM_PROMPT, SCHEMA_HINT, build_user_message
from app.models.auto_edit import AutoEditPlanRequest, AutoEditPlanResponse

logger = logging.getLogger(__name__)


def _extract_json_array(raw: str) -> str:
    """从可能含有思维链/Markdown 的返回中，提取 JSON 文本。"""
    import re

    raw = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
    if "```" in raw:
        parts = raw.split("```")
        # 取中间部分作为代码块
        if len(parts) > 1:
            candidate = parts[1]
            if candidate.lstrip().startswith("json"):
                candidate = candidate.split("\n", 1)[1] if "\n" in candidate else ""
            raw = candidate.strip() or raw

    # 兜底：从第一个 { 到最后一个 } 的范围
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start : end + 1]
    return raw


async def call_llm_for_plans(cfg: dict[str, Any], context: str, req: AutoEditPlanRequest) -> AutoEditPlanResponse:
    llm = LLMClient(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        temperature=cfg["temperature"],
        max_tokens=cfg["max_tokens"],
        timeout=3600,
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_user_message(context, req) + "\n\n" + SCHEMA_HINT,
        },
    ]

    raw = await llm.chat(messages)
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=502, detail="LLM 返回内容为空")
    logger.debug("auto_edit raw LLM output: %s", raw[:500])
    cleaned = _extract_json_array(raw)

    # 尝试直接解析 JSON
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # 尝试使用 json_repair 做一次修复
        try:
            from json_repair import repair_json

            data = json.loads(repair_json(cleaned))
            logger.warning("auto_edit LLM JSON 修复成功")
        except Exception as e:
            logger.error("auto_edit JSON 解析失败: %s", e)
            raise HTTPException(status_code=502, detail="LLM 返回的 JSON 无法解析")

    try:
        return AutoEditPlanResponse(**data)
    except ValidationError as e:
        logger.error("auto_edit Plan 验证失败: %s", e)
        raise HTTPException(status_code=502, detail="LLM 返回的 Plan 结构不符合预期")

