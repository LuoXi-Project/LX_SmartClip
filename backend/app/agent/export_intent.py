from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

ExportIntentKind = Literal["realize", "jianying", "tts_realize"]


@dataclass(frozen=True)
class ExportIntent:
    kind: ExportIntentKind
    force_tts_pipeline: bool = False


_REALIZE_PATTERNS = (
    re.compile(r"按当前方案成片"),
    re.compile(r"^(导出成片|生成成片|开始成片|直接成片|一键成片|成片导出)$"),
    re.compile(r"^(导出|生成|开始).{0,6}成片"),
)

_JIANYING_PATTERNS = (
    re.compile(r"导出剪映草稿"),
    re.compile(r"剪映草稿"),
    re.compile(r"^导出剪映"),
)

_TTS_PATTERNS = (
    re.compile(r"不保留原声"),
    re.compile(r"tts\s*配音", re.I),
    re.compile(r"重新配音"),
    re.compile(r"配音导出"),
)


def detect_export_intent(message: str) -> ExportIntent | None:
    """识别用户明确的导出/成片意图，供 orchestrator 规则短路（不依赖 LLM）。"""
    text = (message or "").strip()
    if not text or len(text) > 80:
        return None

    if any(p.search(text) for p in _TTS_PATTERNS):
        return ExportIntent(kind="tts_realize", force_tts_pipeline=True)

    if any(p.search(text) for p in _JIANYING_PATTERNS):
        return ExportIntent(kind="jianying", force_tts_pipeline=False)

    if any(p.search(text) for p in _REALIZE_PATTERNS):
        return ExportIntent(kind="realize", force_tts_pipeline=False)

    return None
