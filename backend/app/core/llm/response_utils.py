from __future__ import annotations

import re
from typing import Any

_THINK_RE = re.compile(
    r"<think>[\s\S]*?</think>|<redacted_thinking>[\s\S]*?</redacted_thinking>",
    flags=re.IGNORECASE,
)


def strip_thinking_tags(raw: str) -> str:
    """
    清洗 LLM 返回里的思维链/被遮挡思维内容，避免干扰后续 JSON 解析。
    """
    return _THINK_RE.sub("", raw or "").strip()


def _clean_llm_json_text(raw: str) -> str:
    """去除思维链与 Markdown 代码块包裹。"""
    cleaned = strip_thinking_tags(raw)
    if "```" not in cleaned:
        return cleaned
    parts = cleaned.split("```")
    if len(parts) <= 1:
        return cleaned
    candidate = parts[1]
    cand = candidate.lstrip()
    if cand.startswith("json"):
        cand = cand[4:]
        if cand.startswith("\n"):
            cand = cand[1:]
    return cand.strip() or cleaned


def _extract_balanced(text: str, start: int, open_ch: str, close_ch: str) -> str | None:
    """按括号深度提取完整 JSON 片段（忽略字符串内的括号）。"""
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_json_value(raw: str) -> str:
    """
    从 LLM 返回中提取 JSON 对象或数组（优先最早出现的 `[` / `{`）。

    相比「第一个 { 到最后一个 }」可避免数组响应被截成多段对象导致 Extra data。
    """
    cleaned = _clean_llm_json_text(raw)
    positions: list[tuple[int, str, str]] = []
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        pos = cleaned.find(open_ch)
        if pos != -1:
            positions.append((pos, open_ch, close_ch))
    if not positions:
        return cleaned
    positions.sort(key=lambda x: x[0])
    start, open_ch, close_ch = positions[0]
    chunk = _extract_balanced(cleaned, start, open_ch, close_ch)
    if chunk:
        return chunk
    if open_ch == "{":
        e = cleaned.rfind("}")
        if e > start:
            return cleaned[start : e + 1]
    return cleaned


def extract_json_object(raw: str) -> str:
    """
    从 LLM 返回文本中尽量提取 JSON 对象文本（形如 `{...}`）。

    适配：
    - 可能夹杂 `<think>...</think>`
    - 可能使用 Markdown ``` 代码块（code fence 内可能带 `json` 标记）
    - 兜底：括号匹配提取首个完整 `{...}`
    """
    cleaned = _clean_llm_json_text(raw)
    start = cleaned.find("{")
    if start == -1:
        return cleaned
    chunk = _extract_balanced(cleaned, start, "{", "}")
    if chunk:
        return chunk
    e = cleaned.rfind("}")
    if e > start:
        return cleaned[start : e + 1]
    return cleaned


def is_llm_unauthorized_error(err: Exception) -> bool:
    """
    判断是否为鉴权/令牌过期类错误。

    用于：避免把 401 这类“必然失败”的异常吞掉导致前端静默。
    """
    t = str(err)
    tl = t.lower()
    return ("401" in t) or ("unauthorized" in tl) or ("token expired" in tl) or ("令牌已过期" in t)


def ensure_dict(obj: Any) -> dict[str, Any] | None:
    return obj if isinstance(obj, dict) else None

