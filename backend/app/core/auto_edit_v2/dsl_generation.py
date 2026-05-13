from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import HTTPException
from pydantic import ValidationError

from app.core.llm import LLMClient
from app.core.llm.prompts.auto_edit_v2_dsl import _DSL_SYS_PROMPT, _DSL_SCHEMA_HINT
from app.core.llm.response_utils import extract_json_object
from app.models.auto_edit_timeline import StrategyDSL

logger = logging.getLogger(__name__)


async def call_llm_for_strategy_dsl(
    *,
    cfg: dict[str, Any],
    user_prompt: str,
    mode_hint: str,
    target_duration_sec: Optional[int],
) -> StrategyDSL:
    llm = LLMClient(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        temperature=min(float(cfg.get("temperature") or 0.7), 0.5),
        max_tokens=min(int(cfg.get("max_tokens") or 20480), 65536),
        timeout=3600,
    )

    user_lines = [
        f"用户需求：{(user_prompt or '').strip()}",
        f"模式倾向：{mode_hint}",
    ]
    if target_duration_sec:
        user_lines.append(f"目标时长：{int(target_duration_sec)} 秒")

    messages = [
        {"role": "system", "content": _DSL_SYS_PROMPT},
        {"role": "user", "content": "\n".join(user_lines) + "\n\n" + _DSL_SCHEMA_HINT},
    ]
    raw = await llm.chat(messages)
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=502, detail="LLM 返回 DSL 为空")

    cleaned = extract_json_object(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json

            data = json.loads(repair_json(cleaned))
            logger.warning("strategy DSL JSON 修复成功")
        except Exception as e:
            logger.error("strategy DSL JSON 解析失败: %s", e)
            raise HTTPException(status_code=502, detail="LLM 返回的 DSL JSON 无法解析")

    try:
        return StrategyDSL(**data)
    except ValidationError as e:
        logger.error("strategy DSL 验证失败: %s", e)
        raise HTTPException(status_code=502, detail="LLM 返回的 DSL 结构不符合预期")

