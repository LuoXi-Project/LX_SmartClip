from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class ReplicaIngestRequest(BaseModel):
    url: str = Field(..., min_length=5, description="要下载的复刻参考视频链接（支持 yt-dlp 支持的站点）")
    title: Optional[str] = Field(None, description="可选：参考视频标题（用于 UI 展示/存库）")
    # MVP：先只做视频+音频合流，保证后续 ffmpeg 切分/ASR 可用
    download_mode: Literal["best"] = "best"
    max_download_duration_sec: Optional[int] = Field(
        None,
        ge=30,
        le=6000,
        description="可选：下载后如果时长超过该值，会裁剪前段（不保证严格逐帧精确）",
    )


class ReplicaIngestResponse(BaseModel):
    video_id: str
    name: str
    status: str


class ReplicaGenerateTemplateRequest(BaseModel):
    skip_vlm: bool = True
    max_clips: int = Field(80, ge=5, le=300, description="引用片段数量上限（基于 asr_text 聚合）")


class ReplicaTemplateDraft(BaseModel):
    template_id: str
    template_json: Dict[str, Any]
    template_guide: str
    status: Literal["draft"]


class ReplicaConfirmTemplateRequest(BaseModel):
    name: Optional[str] = Field(None, description="模板名称（可选，建议填写便于检索）")
    template_guide: str = Field(..., min_length=10, description="用户确认后的模板引导文本（可编辑）")
    template_json: Optional[Dict[str, Any]] = Field(
        None,
        description="可选：用户是否覆盖模板 JSON（默认保留生成结果的 JSON）",
    )


class ReplicaTemplateConfirmed(BaseModel):
    template_id: str
    template_json: Dict[str, Any]
    template_guide: str
    status: Literal["confirmed"]


class ReplicaTemplateGetResponse(BaseModel):
    template_id: str
    name: Optional[str] = None
    source_video_id: str
    source_url: Optional[str]
    template_json: Dict[str, Any]
    template_guide: str
    pace: Optional[str]
    tone: Optional[str]
    structure: Optional[Any]
    status: Literal["draft", "confirmed"]


class ReplicaTemplateListItem(BaseModel):
    template_id: str
    name: Optional[str] = None
    source_video_id: str
    source_url: Optional[str] = None
    pace: Optional[str] = None
    tone: Optional[str] = None
    status: Literal["draft", "confirmed"]
    created_at: str
    updated_at: str
    guide_preview: str


class ReplicaTemplateListResponse(BaseModel):
    items: list[ReplicaTemplateListItem]
    total: int
    page: int
    page_size: int
    total_pages: int

