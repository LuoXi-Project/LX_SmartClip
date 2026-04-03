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


def extract_json_object(raw: str) -> str:
    """
    从 LLM 返回文本中尽量提取 JSON 对象文本（形如 `{...}`）。

    适配：
    - 可能夹杂 `<think>...</think>`
    - 可能使用 Markdown ``` 代码块（code fence 内可能带 `json` 标记）
    - 兜底：取第一个 `{` 到最后一个 `}`
    """
    cleaned = strip_thinking_tags(raw)

    # 如果出现 code fence，优先取 fence 内内容
    if "```" in cleaned:
        parts = cleaned.split("```")
        if len(parts) > 1:
            candidate = parts[1]
            cand = candidate.lstrip()
            if cand.startswith("json"):
                # 去掉开头的 "json" 标识，剩下的通常就是 JSON
                cand = cand[4:]
                if cand.startswith("\n"):
                    cand = cand[1:]
            cleaned = cand.strip() or cleaned

    # 兜底：截取第一个 { 到最后一个 }
    s = cleaned.find("{")
    e = cleaned.rfind("}")
    if s != -1 and e != -1 and e > s:
        return cleaned[s : e + 1]
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

