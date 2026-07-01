"""片段智能标注（enrich）

用途：
  为每个 clip 生成「旁白适配摘要 + 关键词 + 情绪标签」三件结构化标注，
  抹平「旁白文案（抽象层）↔ 画面/台词（具体层）」的表征鸿沟。

为什么需要：
  纯 embedding 把「旁白」与「画面/台词」放在同一语义空间检索，
  但旁白是创作者视角的抽象叙述（如"决然离去/现实重压"），
  画面/台词是场景视角的具体内容（如"摔门离开/争吵"），
  两者词汇几乎不重叠，跨层检索命中率必然低。
  enrich 让索引侧主动产出与旁白同抽象层的表述，从源头补齐这一鸿沟。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.llm import LLMClient
from app.core.llm.response_utils import extract_json_object

logger = logging.getLogger(__name__)

# 单项标注的长度上限，避免索引膨胀 / embedding 噪声
_MAX_SUMMARY_LEN = 120
_MAX_KEYWORDS = 8
_MAX_EMO_TAGS = 5


def _truncate_list(items: list[str], limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for it in items:
        s = str(it).strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _normalize(data: Any) -> dict[str, Any]:
    """把 LLM 返回归一化为 {abstract_summary, keywords, emotion_tags}，非法字段一律空值。"""
    if not isinstance(data, dict):
        return {"abstract_summary": "", "keywords": [], "emotion_tags": []}

    summary = str(data.get("abstract_summary") or data.get("summary") or "").strip()
    if len(summary) > _MAX_SUMMARY_LEN:
        summary = summary[:_MAX_SUMMARY_LEN].rstrip()

    raw_kw = data.get("keywords") or data.get("tags") or []
    keywords = _truncate_list(raw_kw if isinstance(raw_kw, list) else [raw_kw], _MAX_KEYWORDS)

    raw_em = data.get("emotion_tags") or data.get("emotions") or []
    emotions = _truncate_list(
        raw_em if isinstance(raw_em, list) else [raw_em], _MAX_EMO_TAGS
    )

    return {"abstract_summary": summary, "keywords": keywords, "emotion_tags": emotions}


async def enrich_clip(
    llm: LLMClient,
    *,
    asr_text: str,
    vlm_description: str,
) -> dict[str, Any]:
    """
    用 LLM 给单个 clip 生成结构化标注。

    Args:
        llm: 已初始化的 LLMClient（async）
        asr_text: 原片台词
        vlm_description: VLM 画面描述

    Returns:
        {"abstract_summary": str, "keywords": list[str], "emotion_tags": list[str]}
        任一字段失败时为空，不抛异常（pipeline 不应因标注失败而中断）。
    """
    asr = (asr_text or "").strip()
    vlm = (vlm_description or "").strip()
    if not asr and not vlm:
        return {"abstract_summary": "", "keywords": [], "emotion_tags": []}

    system_prompt = (
        "你是一位影视解说素材标注专家。给你一段视频片段的「原片台词」和「画面描述」（场景视角的具体内容），"
        "你要推断这个片段适合配合什么样的「旁白解说」（创作视角的抽象叙述），"
        "以便后续用旁白文案检索素材时能精准命中。\n"
        "请输出 JSON 对象，包含三个字段：\n"
        '  "abstract_summary": 一句话说明「这个画面适合讲什么主题/情节的旁白」，'
        "用抽象、总结性的表述（如「离别与抉择」「职场博弈」「生死营救」），"
        "而不是复述画面动作；不超过 30 字。\n"
        '  "keywords": 3-8 个关键词，覆盖场景类型、人物动作、核心物件、主题词'
        "（抽象主题词与具体元素都要有）。\n"
        '  "emotion_tags": 1-5 个情绪/氛围标签（如 紧张、温馨、悲伤、搞笑、震撼、压抑、热血）。\n'
        "只返回 JSON 对象，不要任何额外文字或解释。"
    )

    user_prompt = (
        f"原片台词：{asr or '（无台词）'}\n"
        f"画面描述：{vlm or '（无画面描述）'}\n\n"
        "请输出 JSON。"
    )

    try:
        raw = await llm.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        cleaned = extract_json_object(raw if isinstance(raw, str) else "")
        data = json.loads(cleaned)
        return _normalize(data)
    except Exception as e:
        logger.warning("enrich_clip 标注失败（返回空值，不阻断）: %s", e)
        return {"abstract_summary": "", "keywords": [], "emotion_tags": []}
