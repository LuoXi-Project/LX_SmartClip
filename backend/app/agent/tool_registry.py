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
    confirm_granted: set[str] = field(default_factory=set)


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


def needs_confirm(spec: ToolSpec, ctx: AgentContext) -> bool:
    if spec.risk in ("L0", "L1"):
        return False
    if spec.name in ctx.confirm_granted:
        return False
    return spec.risk in ("L2", "L3")


async def invoke(name: str, args: dict[str, Any], ctx: AgentContext) -> ToolResult:
    spec = REGISTRY.get(name)
    if not spec:
        return ToolResult(ok=False, summary="", error=f"未知工具: {name}")
    try:
        return await spec.handler(ctx, args)
    except Exception as e:
        logger.exception("tool %s failed", name)
        return ToolResult(ok=False, summary="", error=str(e))
