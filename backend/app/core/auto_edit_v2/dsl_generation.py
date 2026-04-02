from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import HTTPException
from pydantic import ValidationError

from app.core.llm import LLMClient
from app.models.auto_edit_timeline import StrategyDSL

logger = logging.getLogger(__name__)


_DSL_SYS_PROMPT = """你是一位专业的视频剪辑策略规划师。
你需要把用户需求抽象成“可编译的剪辑策略 DSL”。

要求（必须遵守）：
- 只输出 JSON，不要解释文字，不要 Markdown。
- 输出必须能被 Pydantic StrategyDSL 校验通过。
- 字段尽量短且受控：不要发散到剪辑方案/Plan，不要输出 clip_id。
"""


_DSL_SCHEMA_HINT = """
输出 JSON 结构示例（仅示例，不要照抄文本）：
{
  "dsl_version": "1",
  "goal": "string",
  "mode_hint": "auto|voiceover|original",
  "target_duration_sec": 60,
  "style": {"pace":"fast|medium|slow","tone":"energetic|neutral|calm","structure":["hook","context","highlight","cta"]},
  "preferences": {"prefer_asr": true, "prefer_vlm_when_no_asr": true, "avoid_repetition": true},
  "constraints": {"respect_user_video_order": false, "max_events_per_clip": 6, "tier_budget_ratio": {"tier1":0.7,"tier2":0.25,"tier3":0.05}}
}
"""


def _extract_json(raw: str) -> str:
    import re

    raw = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
    if "```" in raw:
        parts = raw.split("```")
        if len(parts) > 1:
            candidate = parts[1]
            if candidate.lstrip().startswith("json"):
                candidate = candidate.split("\n", 1)[1] if "\n" in candidate else ""
            raw = candidate.strip() or raw
    s = raw.find("{")
    e = raw.rfind("}")
    if s != -1 and e != -1 and e > s:
        return raw[s : e + 1]
    return raw


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
        max_tokens=min(int(cfg.get("max_tokens") or 20480), 4096),
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

    cleaned = _extract_json(raw)
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

