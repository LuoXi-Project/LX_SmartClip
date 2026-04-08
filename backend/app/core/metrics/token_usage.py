from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Dict, Optional


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def add(self, other: "TokenUsage") -> None:
        self.prompt_tokens += int(other.prompt_tokens or 0)
        self.completion_tokens += int(other.completion_tokens or 0)
        self.total_tokens += int(other.total_tokens or 0)

    def to_dict(self) -> Dict[str, int]:
        return {
            "prompt_tokens": int(self.prompt_tokens or 0),
            "completion_tokens": int(self.completion_tokens or 0),
            "total_tokens": int(self.total_tokens or 0),
        }


@dataclass
class TokenAccumulator:
    calls: int = 0
    usage: TokenUsage = field(default_factory=TokenUsage)
    # 可选：当供应商不返回 usage 时的估算值（例如 VLM 图片 tokens）
    estimated_total_tokens: int = 0

    def add_call(self, usage: Optional[TokenUsage] = None, *, estimated_total_tokens: int = 0) -> None:
        self.calls += 1
        if usage is not None:
            self.usage.add(usage)
        if estimated_total_tokens:
            self.estimated_total_tokens += int(estimated_total_tokens)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # dataclass 嵌套会把 TokenUsage 展开成 dict，但类型是 Any；这里统一键名
        d["usage"] = self.usage.to_dict()
        # 展平到常用字段，前端渲染更方便
        d["prompt_tokens"] = d["usage"]["prompt_tokens"]
        d["completion_tokens"] = d["usage"]["completion_tokens"]
        d["total_tokens"] = d["usage"]["total_tokens"]
        return d


def _safe_int(v: Any) -> int:
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return 0


def _model_dump(resp: Any) -> Optional[dict]:
    """
    兼容 pydantic / openai SDK 对象：优先 model_dump，否则退回 __dict__。
    """
    try:
        fn = getattr(resp, "model_dump", None)
        if callable(fn):
            return fn()
    except Exception:
        pass
    try:
        d = getattr(resp, "__dict__", None)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def extract_usage(resp: Any) -> Optional[TokenUsage]:
    """
    从不同形态的响应中尽量提取 usage。

    兼容：
    - resp.usage.prompt_tokens / completion_tokens / total_tokens
    - dict: {"usage": {...}} 或直接包含 prompt_tokens 等键
    - model_dump() 后的 dict
    """
    if resp is None:
        return None

    # 1) attribute style
    try:
        usage_obj = getattr(resp, "usage", None)
        if usage_obj is not None:
            pt = _safe_int(getattr(usage_obj, "prompt_tokens", 0))
            ct = _safe_int(getattr(usage_obj, "completion_tokens", 0))
            tt = _safe_int(getattr(usage_obj, "total_tokens", 0))
            if pt or ct or tt:
                return TokenUsage(pt, ct, tt)
    except Exception:
        pass

    # 2) dict style
    data: Any = resp
    if not isinstance(data, dict):
        data = _model_dump(resp)
    if not isinstance(data, dict):
        return None

    usage = data.get("usage", data)
    if not isinstance(usage, dict):
        return None

    pt = _safe_int(usage.get("prompt_tokens", 0))
    ct = _safe_int(usage.get("completion_tokens", 0))
    tt = _safe_int(usage.get("total_tokens", 0))
    if pt or ct or tt:
        return TokenUsage(pt, ct, tt)
    return None

