"""Agent 偏好（思维链开关）单元测试：存取、提示词组装、流式思考段 gate。"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from app.agent import prefs
from app.agent.orchestrator import COT_OFF_INSTRUCTION, _emit_stream_delta, build_executor_system
from app.agent.prompts.executor import EXECUTOR_SYSTEM
from app.db.database import get_db_conn


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():
    yield
    db = await get_db_conn()
    await db.execute("DELETE FROM config WHERE key = ?", (prefs.COT_ENABLED_KEY,))
    await db.commit()
    await db.close()


@pytest.mark.asyncio
async def test_cot_default_true_when_unconfigured():
    assert await prefs.load_cot_enabled() is True


@pytest.mark.asyncio
async def test_cot_roundtrip():
    await prefs.save_cot_enabled(False)
    assert await prefs.load_cot_enabled() is False
    await prefs.save_cot_enabled(True)
    assert await prefs.load_cot_enabled() is True


@pytest.mark.asyncio
async def test_cot_parses_stored_strings():
    for stored, expected in (("true", True), ("false", False), ("1", True), ("0", False), ("", True)):
        db = await get_db_conn()
        await db.execute(
            "INSERT OR REPLACE INTO config (key, value, type, label) VALUES (?, ?, 'bool', 'x')",
            (prefs.COT_ENABLED_KEY, stored),
        )
        await db.commit()
        await db.close()
        assert await prefs.load_cot_enabled() is expected, stored


def test_build_executor_system():
    assert build_executor_system("", True) == EXECUTOR_SYSTEM
    off = build_executor_system("", False)
    assert off == EXECUTOR_SYSTEM + COT_OFF_INSTRUCTION
    assert "思考模式已关闭" in off
    # 技能清单正常拼接
    both = build_executor_system("\n\n## 可用技能\n- a", False)
    assert both.startswith(EXECUTOR_SYSTEM)
    assert "可用技能" in both and "思考模式已关闭" in both


def test_stream_gate_drops_reasoning_when_off():
    """思考段在思维链关闭时被静默丢弃，开启时正常进 reasoning 通道。

    思考块以空行（\\n\\n）结束（与流式协议一致）。
    """
    # 开启：思考行 → reasoning_delta
    events = _emit_stream_delta("思考：先看素材\n", in_reasoning=[False], cot_enabled=True)
    assert events and events[0][0] == "reasoning_delta"
    # 关闭：同样内容 → 丢弃（无事件）
    in_r = [False]
    events = _emit_stream_delta("思考：先看素材\n", in_reasoning=in_r, cot_enabled=False)
    assert events == []
    # 关闭后思考段结束（空行）的正正常正文仍输出
    events = _emit_stream_delta("\n\n正文结论", in_reasoning=in_r, cot_enabled=False)
    assert events and events[0][0] == "message_delta"
    assert "正文结论" in events[0][1]["content"]


def _unused_asyncio():   # noqa: ANN001 — 保留引用避免误删 import
    return asyncio
