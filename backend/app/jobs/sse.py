"""统一的 SSE 命名事件构造（Convention 1：event:<name>\\ndata:<json>）。

把此前散落在 auto_edit.py:292 / orchestrator.py:145 的私有 _build_sse_event / _sse
提升为公共 helper，供 jobs 与后续迁移的命名事件 SSE 端点复用。
"""

import json


def sse_event(event: str, payload) -> str:
    """构造一条 SSE 帧：`event: <name>\\ndata: <json>\\n\\n`。"""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def sse_comment(text: str = "keep-alive") -> str:
    """SSE 注释帧，用于刷新响应头 / 心跳。"""
    return f": {text}\n\n"
