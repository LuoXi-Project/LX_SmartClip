"""MCP 桥接单元测试：本地 stdio 测试服务器 → 注册/调用/trusted/清理全链路。

测试服务器用 mcp SDK 服务端（FastMCP）实现，暴露 add 工具；
管理器经 stdio 子进程连接、列举、桥接进 REGISTRY 并调用。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio

from app.agent import mcp_manager
from app.agent.tool_registry import REGISTRY, AgentContext, invoke, needs_confirm
from app.models.agent import WorkspaceState

_TEST_SERVER = Path(__file__).parent / "_mcp_test_server.py"

_SERVER_CFG = {
    "id": "test",
    "name": "测试工具",
    "transport": "stdio",
    "command": sys.executable,
    "args": [str(_TEST_SERVER)],
    "enabled": True,
    "trusted": False,
    "timeout_sec": 15,
}


@pytest_asyncio.fixture(autouse=True)
async def _cleanup():
    from app.agent.tools import register_all_tools

    register_all_tools()   # 内置工具注册（REGISTRY 进程级，幂等）
    yield
    await mcp_manager.delete_server("test")
    await mcp_manager.delete_server("broken")   # bad-server 用例的遗留
    await mcp_manager.shutdown()


@pytest.mark.asyncio
async def test_stdio_bridge_full_flow():
    # 1) 保存配置并同步注册表
    saved = await mcp_manager.upsert_server(_SERVER_CFG)
    assert saved["id"] == "test"
    stats = await mcp_manager.sync_registry()
    assert stats["tools"] >= 1

    full = "mcp__test__add"
    spec = REGISTRY.get(full)
    assert spec is not None, "桥接工具应注册进 REGISTRY"
    assert spec.description.startswith("[MCP·测试工具]")
    assert spec.risk == "L2"
    # 入参 schema 来自 MCP inputSchema
    assert spec.parameters.get("properties", {}).get("a")

    # 2) 权限联动：ask 档需确认，trusted 后放行
    ws = WorkspaceState(session_id="s")
    ctx = AgentContext(session_id="s", workspace=ws)
    assert needs_confirm(spec, ctx) is True
    ctx.external_trusted = {full}
    assert needs_confirm(spec, ctx) is False

    # 3) 实际调用（走 stdio 子进程）
    result = await invoke(full, {"a": 2, "b": 3}, ctx)
    assert result.ok, result.error
    assert "5" in result.summary


@pytest.mark.asyncio
async def test_bad_server_skipped_builtin_intact():
    await mcp_manager.upsert_server(_SERVER_CFG)
    await mcp_manager.upsert_server(
        {
            "id": "broken",
            "name": "坏服务器",
            "transport": "stdio",
            "command": sys.executable,
            "args": ["-c", "import sys; sys.exit(1)"],
            "enabled": True,
        }
    )
    stats = await mcp_manager.sync_registry()
    assert stats["tools"] >= 1          # test server 的工具仍在
    assert "mcp__broken__anything" not in REGISTRY
    assert "list_videos" in REGISTRY    # 内置工具不受影响


@pytest.mark.asyncio
async def test_delete_server_removes_tools():
    await mcp_manager.upsert_server(_SERVER_CFG)
    await mcp_manager.sync_registry()
    assert "mcp__test__add" in REGISTRY
    assert await mcp_manager.delete_server("test") is True
    await mcp_manager.sync_registry()
    assert "mcp__test__add" not in REGISTRY


@pytest.mark.asyncio
async def test_test_connection_endpoint_logic():
    result = await mcp_manager.test_server(_SERVER_CFG)
    assert result["ok"] is True, result.get("error")
    assert any(t["name"] == "add" for t in result["tools"])


def test_normalize_validation():
    with pytest.raises(ValueError):
        mcp_manager._normalize_entry({"id": "x", "transport": "stdio"})   # 缺 command
    with pytest.raises(ValueError):
        mcp_manager._normalize_entry({"id": "x", "transport": "ftp"})     # 未知传输
    ok = mcp_manager._normalize_entry(
        {"id": "ABC", "transport": "http", "url": "http://a/mcp"}
    )
    assert ok["id"] == "abc" and ok["timeout_sec"] == 60
