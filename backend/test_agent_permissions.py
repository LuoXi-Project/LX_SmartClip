"""执行权限三档（ask/auto/full）单元测试。

档位语义：
- L0/L1 只读与工作区写入：任何档位放行
- L3 不可逆操作：任何档位都必须确认（安全底线）
- L2 长任务/成片/导出：ask 需确认（session_granted 豁免）/ auto 放行 / full 放行
- 外部 MCP 工具（mcp__ 前缀）：ask 需确认；auto 仅 trusted 放行；full 放行
"""

from __future__ import annotations

from app.agent.tool_registry import AgentContext, ToolSpec, needs_confirm
from app.models.agent import AgentPermissions, ChatRequest, WorkspaceState


def _spec(name: str, risk: str) -> ToolSpec:
    return ToolSpec(name=name, description="", parameters={}, risk=risk, handler=None)  # type: ignore[arg-type]


def _ctx(mode: str = "ask", granted: list[str] | None = None, trusted: set[str] | None = None) -> AgentContext:
    ws = WorkspaceState(session_id="s", permissions=AgentPermissions(mode=mode, session_granted=granted or []))  # type: ignore[arg-type]
    return AgentContext(session_id="s", workspace=ws, external_trusted=trusted or set())


REALIZE = _spec("realize_plan", "L2")
PROCESS = _spec("start_process_job", "L2")
DANGER = _spec("publish_video", "L3")
READ = _spec("list_videos", "L0")
MCP = _spec("mcp__fs__read_file", "L2")


def test_l0_l1_always_pass():
    for mode in ("ask", "auto", "full"):
        assert needs_confirm(READ, _ctx(mode)) is False


def test_l2_ask_requires_confirm():
    assert needs_confirm(REALIZE, _ctx("ask")) is True
    assert needs_confirm(PROCESS, _ctx("ask")) is True


def test_l2_ask_session_granted_passes():
    assert needs_confirm(REALIZE, _ctx("ask", granted=["realize_plan"])) is False


def test_l3_always_confirms_regardless_of_mode_or_grant():
    for mode in ("ask", "auto", "full"):
        assert needs_confirm(DANGER, _ctx(mode)) is True
    # 即便已 session_granted，L3 仍确认
    assert needs_confirm(DANGER, _ctx("ask", granted=["publish_video"])) is True


def test_l2_auto_passes():
    assert needs_confirm(REALIZE, _ctx("auto")) is False


def test_l2_full_passes():
    assert needs_confirm(REALIZE, _ctx("full")) is False
    assert needs_confirm(PROCESS, _ctx("full")) is False


def test_mcp_tool_ask_confirms():
    assert needs_confirm(MCP, _ctx("ask")) is True


def test_mcp_tool_auto_only_trusted_passes():
    assert needs_confirm(MCP, _ctx("auto")) is True
    assert needs_confirm(MCP, _ctx("auto", trusted={"mcp__fs__read_file"})) is False


def test_mcp_tool_full_passes():
    assert needs_confirm(MCP, _ctx("full")) is False


def test_mcp_tool_ask_trusted_or_granted_passes():
    assert needs_confirm(MCP, _ctx("ask", trusted={"mcp__fs__read_file"})) is False
    assert needs_confirm(MCP, _ctx("ask", granted=["mcp__fs__read_file"])) is False


def test_default_permissions_is_ask():
    """旧会话工作区 JSON 无 permissions 字段 → pydantic 默认 ask，行为不变。"""
    ws = WorkspaceState(session_id="s")
    assert ws.permissions.mode == "ask"
    assert ws.permissions.session_granted == []


def test_chat_request_grant_session_default_false():
    req = ChatRequest(message="继续")
    assert req.grant_session is False
