"""多向量子空间文本构造（pipeline 与 backfill 共用，避免拼接逻辑漂移）。

3 个"新"子空间的文本拼装规则（legacy 子空间不在此构造，由旧库兼容读入）：
  - asr:      asr_text + keywords       （具体台词 + 实体关键词）
  - vlm:      vlm_description           （纯视觉画面）
  - abstract: abstract_summary + emotion_tags （抽象主题 + 情绪）

设计要点：
- 每路独立拼接，任一路为空则该子空间不出现在返回 dict 中（调用方据此决定是否 embed）。
- keywords/emotion_tags 接受 list[str] 或 JSON 字符串（DB 里是 JSON 字符串）。
- 与旧 _build_text（5 路全混合）保持字段来源一致，只是拆分到不同子空间。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Union

# 主动写入的子空间（legacy 不在此列，仅由旧库兼容读入）
WRITABLE_SUBSPACES = ("asr", "vlm", "abstract")


def _join_tags(raw: Any) -> str:
    """把 list[str] 或 JSON 字符串 flatten 成空格分隔的纯文本。"""
    if not raw:
        return ""
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
        except (TypeError, ValueError):
            return raw.strip()
    else:
        v = raw
    if isinstance(v, list):
        return " ".join(str(x).strip() for x in v if str(x).strip())
    return str(v).strip()


def _clean(s: Any) -> str:
    return (str(s) if s is not None else "").strip()


def build_sub_texts(
    *,
    asr_text: str = "",
    vlm_description: str = "",
    abstract_summary: str = "",
    keywords: Union[str, Iterable[str], None] = None,
    emotion_tags: Union[str, Iterable[str], None] = None,
) -> Dict[str, str]:
    """构造 3 个子空间的输入文本。

    Returns:
        {"asr": str, "vlm": str, "abstract": str}，空文本的子空间仍以空串出现，
        由调用方决定是否对空串跳过 embed。
    """
    asr = _clean(asr_text)
    kw = _clean(_join_tags(keywords))
    asr_full = " ".join(p for p in (asr, kw) if p)

    vlm = _clean(vlm_description)

    summary = _clean(abstract_summary)
    emo = _clean(_join_tags(emotion_tags))
    abstract_full = " ".join(p for p in (summary, emo) if p)

    return {
        "asr": asr_full,
        "vlm": vlm,
        "abstract": abstract_full,
    }


def non_empty_subspaces(sub_texts: Dict[str, str]) -> List[str]:
    """返回非空子空间名列表（调用方据此决定要 embed 哪几路）。"""
    return [s for s in WRITABLE_SUBSPACES if sub_texts.get(s, "").strip()]


def build_legacy_text(
    *,
    asr_text: str = "",
    vlm_description: str = "",
    abstract_summary: str = "",
    keywords: Union[str, Iterable[str], None] = None,
    emotion_tags: Union[str, Iterable[str], None] = None,
) -> str:
    """旧版 5 路全混合文本（向后兼容 backfill 的历史行为，仅特殊场景使用）。"""
    subs = build_sub_texts(
        asr_text=asr_text,
        vlm_description=vlm_description,
        abstract_summary=abstract_summary,
        keywords=keywords,
        emotion_tags=emotion_tags,
    )
    return " ".join(subs[s] for s in WRITABLE_SUBSPACES if subs[s]).strip()
