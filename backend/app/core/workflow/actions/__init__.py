"""动作注册表：工作流可调度的能力单元。

每个 ActionSpec 自描述（输入/输出 schema + 示例），既是前端组合参考，
也是后期对话式 Agent 的「工具说明书」（GET /api/workflow/actions 直接暴露）。
新增能力 = 用 @action 装饰一个 async 函数，任何工作流即可引用。
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from ..context import WorkflowContext


class WorkflowActionError(RuntimeError):
    """动作业务失败（信息面向用户 / LLM，可直接展示）。"""


@dataclass
class ActionSpec:
    name: str
    title: str
    description: str
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    example: dict = field(default_factory=dict)
    run: Callable[["WorkflowContext", dict], Awaitable[dict]] | None = None


# 动作名 -> ActionSpec
ACTIONS: dict[str, ActionSpec] = {}

# 动作实现子模块（导入即注册）
_ACTION_MODULES = ("ingest", "process", "auto_edit_actions", "match_render")

_loaded = False


def ensure_actions_loaded() -> None:
    """幂等加载全部动作模块（避免与 schema/api 的循环导入，延迟到首次使用）。"""
    global _loaded
    if _loaded:
        return
    for mod in _ACTION_MODULES:
        importlib.import_module(f".{mod}", package=__name__)
    _loaded = True


def action(
    name: str,
    *,
    title: str,
    description: str,
    input_schema: dict | None = None,
    output_schema: dict | None = None,
    example: dict | None = None,
):
    """注册一个工作流动作。run 签名: async def run(ctx, params: dict) -> dict。"""

    def deco(fn: Callable[["WorkflowContext", dict], Awaitable[dict]]):
        if name in ACTIONS:
            raise ValueError(f"工作流动作重复注册: {name}")
        ACTIONS[name] = ActionSpec(
            name=name,
            title=title,
            description=description,
            input_schema=input_schema or {},
            output_schema=output_schema or {},
            example=example or {},
            run=fn,
        )
        return fn

    return deco


def catalog() -> list[dict]:
    """动作目录（LLM / 前端组合工作流的说明书面）。"""
    ensure_actions_loaded()
    return [
        {
            "name": s.name,
            "title": s.title,
            "description": s.description,
            "input_schema": s.input_schema,
            "output_schema": s.output_schema,
            "example": s.example,
        }
        for s in ACTIONS.values()
    ]


def run_action(ctx: "WorkflowContext", name: str, params: dict) -> Awaitable[dict]:
    ensure_actions_loaded()
    spec = ACTIONS.get(name)
    if spec is None or spec.run is None:
        raise WorkflowActionError(f"未知工作流动作: {name}")
    return spec.run(ctx, params)
