"""影视解说一键成片 · 任务模型。"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.auto_edit import Plan

FilmMode = Literal["precise", "lightweight"]
FilmStyle = Literal["suspense", "humor", "deep", "fast"]
FilmJobStatus = Literal[
    "pending",
    "parsing",
    "scripting",
    "aligning",
    "planning",
    "rendering",
    "done",
    "failed",
    "cancelled",
]


class FilmCommentaryCreateRequest(BaseModel):
    video_id: str = Field(..., description="素材库视频 ID")
    mode: FilmMode = Field("precise", description="precise=VLM+ASR；lightweight=仅 ASR+通识")
    style: FilmStyle = Field("suspense", description="解说风格")
    target_duration_sec: int = Field(300, ge=60, le=1800, description="目标成片时长（秒）")
    auto_render: bool = Field(True, description="对齐完成后自动 TTS 配音出片")
    include_subtitle: bool = Field(True, description="出片是否烧录字幕")


class FilmSentence(BaseModel):
    index: int
    text: str
    tag: Optional[str] = None


class FilmAlignment(BaseModel):
    sentence_index: int
    clip_id: str
    video_id: str
    start_time: float
    end_time: float
    score: float = 0.0
    reason: str = ""


class FilmCommentaryJob(BaseModel):
    id: str
    video_id: str
    video_name: Optional[str] = None
    status: FilmJobStatus
    current_step: Optional[str] = None
    mode: FilmMode
    style: FilmStyle
    target_duration_sec: int
    auto_render: bool
    include_subtitle: bool
    progress: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    storyline: Optional[Dict[str, Any]] = None
    sentences: List[FilmSentence] = Field(default_factory=list)
    alignments: List[FilmAlignment] = Field(default_factory=list)
    plan: Optional[Plan] = None
    output_url: Optional[str] = None
    output_filename: Optional[str] = None
    created_at: str
    updated_at: str
    finished_at: Optional[str] = None


class FilmCommentaryJobListResponse(BaseModel):
    items: List[FilmCommentaryJob]
    total: int


class FilmCommentaryOpenMatchRequest(BaseModel):
    """携带 Plan 跳转智能剪辑工作台（可选）。"""
    pass
