"""从提示词或参数解析「成片目标时长」，用于智能快剪等。"""
from __future__ import annotations

import re
from typing import Optional

# 成片合理区间（秒）
MIN_TARGET_SEC = 5.0
MAX_TARGET_SEC = 7200.0


def parse_duration_seconds_from_text(text: str) -> Optional[float]:
    """
    从自然语言中抽取时长（秒）。支持示例：
    - 120秒、120s、约90秒钟
    - 2分钟、2分、3min、大约2.5分钟
    - 1分30秒、2分半（=150秒）
    """
    if not text or not str(text).strip():
        return None
    t = str(text)

    # 1分30秒 / 01分05秒
    m = re.search(r"(\d+)\s*分\s*(\d+(?:\.\d+)?)\s*秒", t)
    if m:
        sec = float(m.group(1)) * 60.0 + float(m.group(2))
        return sec if sec >= MIN_TARGET_SEC else None

    # N分半（如 两分半）
    m = re.search(r"(?:约|大概|大约)?\s*(\d+)\s*分\s*半", t)
    if m:
        sec = float(m.group(1)) * 60.0 + 30.0
        return sec if sec >= MIN_TARGET_SEC else None

    # 纯秒：120秒、120s
    m = re.search(r"(?:约|大概|大约)?\s*(\d+(?:\.\d+)?)\s*(?:秒钟|秒)(?!钟)", t, re.I)
    if not m:
        m = re.search(r"(?:约|大概|大约)?\s*(\d+(?:\.\d+)?)\s*s\b", t, re.I)
    if m:
        sec = float(m.group(1))
        return sec if sec >= MIN_TARGET_SEC else None

    # 分钟：2分钟、2分、2.5min
    m = re.search(r"(?:约|大概|大约)?\s*(\d+(?:\.\d+)?)\s*(?:分钟|分)(?!钟)", t)
    if not m:
        m = re.search(r"(?:约|大概|大约)?\s*(\d+(?:\.\d+)?)\s*min\b", t, re.I)
    if m:
        sec = float(m.group(1)) * 60.0
        return sec if sec >= MIN_TARGET_SEC else None

    # 中文分钟（常见：两分钟、五分钟、十分钟；不含复合如「十二分钟」）
    _CN_MIN = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    m = re.search(r"(一|二|两|三|四|五|六|七|八|九|十)\s*分钟", t)
    if m:
        d = _CN_MIN.get(m.group(1))
        if d:
            sec = float(d * 60)
            return sec if sec >= MIN_TARGET_SEC else None

    return None


def clamp_target_duration_sec(sec: Optional[float]) -> Optional[float]:
    if sec is None:
        return None
    try:
        v = float(sec)
    except (TypeError, ValueError):
        return None
    if v < MIN_TARGET_SEC:
        return None
    return max(MIN_TARGET_SEC, min(MAX_TARGET_SEC, v))


def resolve_voiceover_target_duration_sec(
    *,
    explicit_sec: Optional[float],
    user_prompt: Optional[str],
) -> Optional[float]:
    """
    优先使用请求体中的 target_duration_sec；否则尝试从 user_prompt 解析。
    """
    c = clamp_target_duration_sec(explicit_sec)
    if c is not None:
        return c
    parsed = parse_duration_seconds_from_text(user_prompt or "")
    return clamp_target_duration_sec(parsed)
