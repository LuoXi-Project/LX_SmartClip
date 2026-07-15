"""ASR 结果 LLM 校准器。

调用 LLM 修正 ASR 识别错误（同音/形近错字、标点、断句），同时：
- 保留原句级时间轴的 start/end，只更新每句 text；
- 校准后 asr_text 由各句 text 拼接，保证全文↔句级一致；
- 无 segments 时降级为整段校准。

返回结构统一为 dict，供 API 层 diff/写库使用。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, List

from app.core.llm import LLMClient
from app.core.llm.prompts.asr_correct import SYSTEM_PROMPT, build_user_message

logger = logging.getLogger(__name__)


def _strip_think(raw: str) -> str:
    """去除 thinking 模型的 <think>...</think> 块。"""
    return re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()


def _extract_json_object(raw: str) -> dict:
    """从 LLM 返回中提取首个 JSON 对象并解析（兼容 markdown 代码块）。"""
    raw = _strip_think(raw)
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else parts[0]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start : end + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        from json_repair import repair_json

        return json.loads(repair_json(raw))


def _join_segments_text(segments: List[dict]) -> str:
    return "".join((s.get("text") or "") for s in segments)


async def correct_transcript(
    llm: LLMClient,
    asr_text: str,
    segments: List[dict],
    *,
    temperature: float = 0.2,
    max_tokens: int | None = None,
    topic: str | None = None,
    context: str | None = None,
    hint: str | None = None,
) -> dict[str, Any]:
    """
    用 LLM 校准 ASR 文本。

    Args:
        llm: 已配置的 LLMClient
        asr_text: 原始全文
        segments: 原始句级 [{start,end,text}]；可为空
        temperature: 校准温度（默认 0.2，偏低以求稳定）
        max_tokens: 可选 max_tokens 覆盖
        topic: 视频主题/标题（可选）；用于领域专有名词判断
            （如「面积纸」→「面巾纸」），单看一句难判错字时尤其重要
        context: 同视频其他片段的参考台词（可选）；帮助 LLM 理解整体内容
        hint: 用户自定义倾向提示词（可选）；优先级最高，用于指定领域词汇、
            专有名词、口音特点等

    Returns:
        {
            "original_text": str,
            "corrected_text": str,
            "original_segments": list[dict],
            "corrected_segments": list[dict],   # 保留原 start/end，仅 text 被替换
            "changed": bool,
        }
    """
    original_segments = [
        {
            "start": float(s.get("start", 0.0) or 0.0),
            "end": float(s.get("end", 0.0) or 0.0),
            "text": str(s.get("text", "") or ""),
        }
        for s in (segments or [])
    ]
    original_text = (asr_text or "").strip()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_user_message(
                original_text,
                original_segments,
                topic=topic,
                context=context,
                hint=hint,
            ),
        },
    ]

    content = await llm.chat(messages, temperature=temperature, max_tokens=max_tokens)
    data = _extract_json_object(content)

    # ---- 句级校准分支 ----
    if original_segments:
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ValueError("LLM 返回缺少 items 数组")

        # index -> text 映射
        idx_map: dict[int, str] = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            idx = it.get("index")
            text = it.get("text")
            if idx is None or not isinstance(text, str):
                continue
            try:
                idx_map[int(idx)] = text.strip()
            except (TypeError, ValueError):
                continue

        # 逐句替换 text，保留 start/end；缺编号时回退原句
        corrected_segments: list[dict] = []
        for i, seg in enumerate(original_segments):
            new_text = idx_map.get(i)
            if new_text is None:
                # 容错：若 LLM 漏了某句，保留原文，避免丢句
                new_text = seg["text"]
            corrected_segments.append(
                {"start": seg["start"], "end": seg["end"], "text": new_text}
            )
        corrected_text = _join_segments_text(corrected_segments)
    else:
        # ---- 整段校准分支 ----
        corrected_text = ""
        if isinstance(data, dict):
            t = data.get("text")
            if isinstance(t, str):
                corrected_text = t.strip()
        if not corrected_text:
            raise ValueError("LLM 返回缺少 text 字段")
        corrected_segments = []

    changed = corrected_text != original_text or any(
        cs.get("text") != orig.get("text")
        for cs, orig in zip(corrected_segments, original_segments)
    )

    return {
        "original_text": original_text,
        "corrected_text": corrected_text,
        "original_segments": original_segments,
        "corrected_segments": corrected_segments,
        "changed": changed,
    }
