"""文案 → 画面检索意图（Visual Intent）扩展。

旁白/解说文案是抽象层叙述（例如「他感到无比绝望」），与素材侧表征
（ASR 台词 / VLM 画面描述）词面几乎不重叠，直接用原文做检索会系统性错配。
本模块在检索前把每段文案改写成「画面意图描述」（主体/动作/场景/情绪/景别），
用意图句替代原文参与召回与精排，抹平「旁白 ↔ 画面」的表征鸿沟。

所有函数都是同步实现（内部使用同步 OpenAI 客户端），供线程池调用；
LLM 调用失败时返回 None / 原文，绝不阻塞主流程。
"""

from __future__ import annotations

import json
import logging
from typing import Callable, List, Mapping, Optional, Sequence

from app.core.llm.response_utils import extract_json_object

logger = logging.getLogger(__name__)

# 过短的文案（如单个词）改写收益低且易失真，直接跳过
_MIN_TEXT_LEN = 4

_INTENT_SYS_PROMPT = (
    "你是短视频画面编导。用户会给出若干旁白/解说句子，"
    "请把每一句改写成「用于视频素材检索的画面意图描述」。\n"
    "要求：\n"
    "- 具体可视：包含主体、动作、场景、情绪、景别中的 2~4 项；\n"
    "- 15~40 字，中文；不要照抄原句，不要输出台词或评论；\n"
    "- 意图必须忠实于原句语义，不得新增原句没有的信息；\n"
    "- 只输出 JSON：{\"intents\":[\"...\",\"...\"]}，与输入句子逐条对应。"
)


def _build_messages(segments: Sequence[str]) -> List[dict]:
    lines = "\n".join(f"{i}. {t.strip()}" for i, t in enumerate(segments, 1))
    user = f"【旁白句子】\n{lines}\n\n请输出与上述 {len(segments)} 句逐一对应的画面意图 JSON。"
    return [
        {"role": "system", "content": _INTENT_SYS_PROMPT},
        {"role": "user", "content": user},
    ]


def _default_chat_fn(llm_cfg: Mapping) -> Callable[[List[dict]], str]:
    """默认同步 OpenAI 兼容客户端；llm_cfg 需含 base_url / api_key / model。"""
    from openai import OpenAI

    client = OpenAI(
        api_key=llm_cfg["api_key"],
        base_url=llm_cfg["base_url"],
        timeout=float(llm_cfg.get("timeout", 60) or 60),
    )
    model = llm_cfg["model"]

    def _chat(messages: List[dict]) -> str:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.3,
            max_tokens=min(int(llm_cfg.get("max_tokens") or 4096), 8192),
        )
        return str(resp.choices[0].message.content or "")

    return _chat


def _normalize_intent(raw: object) -> Optional[str]:
    """单条意图清洗：去空白、限长；非法输入返回 None。"""
    if not isinstance(raw, str):
        return None
    t = raw.strip()
    if not t:
        return None
    if len(t) > 120:
        t = t[:120]
    return t


def parse_intents_payload(raw: str, expected_n: int) -> List[Optional[str]]:
    """解析 LLM 输出为与输入等长的意图列表；解析失败或长度不符时返回全 None。"""
    if not raw or not raw.strip():
        return [None] * expected_n
    cleaned = extract_json_object(raw)
    try:
        data = json.loads(cleaned)
    except Exception:
        try:
            from json_repair import repair_json

            data = json.loads(repair_json(cleaned))
        except Exception as e:
            logger.warning("[VisualIntent] JSON 解析失败，回退原文检索: %s", e)
            return [None] * expected_n

    intents_raw = data.get("intents") if isinstance(data, dict) else None
    if not isinstance(intents_raw, list):
        # 容错：直接给了字符串数组
        if isinstance(data, list):
            intents_raw = data
        else:
            logger.warning("[VisualIntent] 输出缺少 intents 数组，回退原文检索")
            return [None] * expected_n

    out: List[Optional[str]] = [_normalize_intent(x) for x in intents_raw]
    # 长度对齐：不足补 None，超长截断（保持逐条对应关系）
    if len(out) < expected_n:
        out.extend([None] * (expected_n - len(out)))
    return out[:expected_n]


def expand_visual_intents_sync(
    llm_cfg: Mapping,
    segments: Sequence[str],
    *,
    chat_fn: Optional[Callable[[List[dict]], str]] = None,
) -> List[Optional[str]]:
    """批量把旁白句子改写为画面意图（一次 LLM 调用）。

    返回与 segments 等长的列表；某条失败/非法时对应位置为 None（调用方回退原文）。
    """
    texts = [str(s or "").strip() for s in segments]
    if not texts:
        return []
    results: List[Optional[str]] = [None] * len(texts)
    eligible_idx = [i for i, t in enumerate(texts) if len(t) >= _MIN_TEXT_LEN]
    if not eligible_idx:
        return results

    chat = chat_fn or _default_chat_fn(llm_cfg)
    try:
        raw = chat(_build_messages([texts[i] for i in eligible_idx]))
    except Exception as e:
        logger.warning("[VisualIntent] LLM 调用失败，回退原文检索: %s", e)
        return results

    parsed = parse_intents_payload(raw, len(eligible_idx))
    for pos, i in enumerate(eligible_idx):
        results[i] = parsed[pos]
    filled = sum(1 for r in results if r)
    logger.info("[VisualIntent] 画面意图改写完成：%d/%d 条", filled, len(texts))
    return results


def expand_visual_intent_sync(
    llm_cfg: Mapping,
    text: str,
    *,
    chat_fn: Optional[Callable[[List[dict]], str]] = None,
) -> Optional[str]:
    """单句改写；失败返回 None（调用方回退原文）。"""
    res = expand_visual_intents_sync(llm_cfg, [text], chat_fn=chat_fn)
    return res[0] if res else None
