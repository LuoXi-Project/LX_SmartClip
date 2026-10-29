from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from app.models.agent import ToolResult, ToolRisk, WorkspaceState

logger = logging.getLogger(__name__)

ToolHandler = Callable[["AgentContext", dict[str, Any]], Awaitable[ToolResult]]


@dataclass
class AgentContext:
    session_id: str
    workspace: WorkspaceState
    api_base_url: str = ""
    # 受信任的外部（MCP）工具名集合：auto 档下免确认（第 3 期由 mcp_manager 填充）
    external_trusted: set[str] = field(default_factory=set)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    risk: ToolRisk
    handler: ToolHandler


REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> None:
    REGISTRY[spec.name] = spec


def get_openai_tools() -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for spec in REGISTRY.values():
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
        )
    return tools


def _is_external_tool(name: str) -> bool:
    """外部 MCP 桥接工具（第 3 期启用，命名空间 mcp__<server>__<tool>）。"""
    return name.startswith("mcp__")


def needs_confirm(spec: ToolSpec, ctx: AgentContext) -> bool:
    """按权限档位判定是否需要用户确认。

    - L0/L1（只读 / 工作区写入）：任何档位直接放行
    - L3（不可逆危险操作，如发布、删除）：任何档位都必须确认
    - L2（长任务 / 成片 / 导出 / 外部工具）：
      - ask（默认）：需确认，但本会话已授权（session_granted）的工具除外
      - auto：内置工具放行；外部 MCP 工具仅受信任（trusted）的放行
      - full：全部放行
    """
    if spec.risk in ("L0", "L1"):
        return False
    if spec.risk == "L3":
        return True
    perms = ctx.workspace.permissions
    if perms.mode == "full":
        return False
    if perms.mode == "auto":
        if _is_external_tool(spec.name):
            return spec.name not in ctx.external_trusted
        return False
    # ask
    if _is_external_tool(spec.name):
        # 外部工具在 ask 档下 session_granted 同样生效
        return spec.name not in perms.session_granted and spec.name not in ctx.external_trusted
    return spec.name not in perms.session_granted


async def invoke(name: str, args: dict[str, Any], ctx: AgentContext) -> ToolResult:
    spec = REGISTRY.get(name)
    if not spec:
        return ToolResult(ok=False, summary="", error=f"未知工具: {name}")
    try:
        return await spec.handler(ctx, args)
    except Exception as e:
        logger.exception("tool %s failed", name)
        return ToolResult(ok=False, summary="", error=str(e))
