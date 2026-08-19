"""工作流 API 请求模型。

definition 故意保持 raw dict：校验走 core.workflow.schema 的结构化校验器，
错误信息（field/message）比 Pydantic 默认报错更适合前端定位与 LLM 自修正。
"""

from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, Field


class WorkflowDefinitionRequest(BaseModel):
    definition: Dict[str, Any] = Field(..., description="工作流定义 JSON（结构见 /api/workflow/actions 目录）")


class WorkflowValidateRequest(BaseModel):
    definition: Dict[str, Any]


class WorkflowRunRequest(BaseModel):
    inputs: Dict[str, Any] = Field(default_factory=dict, description="运行输入，按定义 params 声明校验")
