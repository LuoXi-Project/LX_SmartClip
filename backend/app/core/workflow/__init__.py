"""工作流引擎：声明式 JSON 定义 + 动作注册表 + 后台编排执行。

模块布局：
- schema.py   定义契约（dataclass ↔ JSON 同构）+ 强校验器 + 安全 when 求值器
- actions/    动作注册表（包装现有能力，自描述 schema 供 LLM/前端组合）
- context.py  执行上下文（模板解析 / 子 job 接力 / 级联取消）
- engine.py   执行引擎（作为 async_jobs kind=workflow 后台协程运行）
- store.py    workflows / workflow_runs 表访问 + 内置同步 + 启动对账
- builtin.py  内置工作流（代码即默认值，启动同步进 DB，is_builtin=1）
"""

from .schema import (
    ParamSpec,
    WorkflowDef,
    WorkflowDefError,
    WorkflowStep,
    resolve_run_inputs,
    validate_workflow_def,
)

__all__ = [
    "ParamSpec",
    "WorkflowDef",
    "WorkflowDefError",
    "WorkflowStep",
    "resolve_run_inputs",
    "validate_workflow_def",
]
