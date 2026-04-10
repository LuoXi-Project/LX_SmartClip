from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


SummaryMode = Literal["asr", "vlm", "asr_vlm"]


class SummaryTemplate(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    system_prompt: str
    user_prompt_template: str
    output_schema_hint: Optional[str] = None
    created_at: str
    updated_at: str


class SummaryTemplateUpsertRequest(BaseModel):
    id: Optional[str] = Field(None, description="为空则后端生成")
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    system_prompt: str = Field(..., min_length=1)
    user_prompt_template: str = Field(..., min_length=1)
    output_schema_hint: Optional[str] = None


class SummaryGenerateRequest(BaseModel):
    video_id: str = Field(..., min_length=1)
    mode: SummaryMode = Field("asr_vlm", description="总结数据来源：asr/vlm/asr_vlm")
    template_id: str = Field("default_general", description="使用的总结模板 ID")
    user_goal: str = Field("通用总结", description="用户目标/用途：如复盘/写文案/提取重点/会议纪要等")
    extra_instructions: str = Field("", description="额外约束/偏好（可选）")

    # 超长分段参数
    chunk_max_chars: int = Field(6000, ge=1500, le=20000)
    chunk_overlap_chars: int = Field(400, ge=0, le=3000)
    max_chunks: int = Field(30, ge=1, le=200)

    # 提示词注入：允许前端注入额外变量供模板使用
    prompt_vars: dict[str, Any] = Field(default_factory=dict)


class VideoSummary(BaseModel):
    id: str
    video_id: str
    template_id: str
    mode: SummaryMode
    status: str
    input_fingerprint: Optional[str] = None
    summary_json: Optional[dict[str, Any]] = None
    summary_markdown: Optional[str] = None
    prompt_snapshot_json: Optional[dict[str, Any]] = None
    created_at: str
    updated_at: str


class VideoSummaryUpdateRequest(BaseModel):
    summary_json: Optional[dict[str, Any]] = None
    summary_markdown: Optional[str] = None
    source: Literal["user", "llm"] = "user"

