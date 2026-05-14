"""智能视频大纲（ASR 为主，可选 VLM）—— API 与持久化模型。"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class SmartOutlineRequest(BaseModel):
    max_clips: int = Field(
        default=120,
        ge=1,
        le=200,
        description="参与分析的 clip 数量上限",
    )


class SmartOutlineTopic(BaseModel):
    title: str
    start_sec: float = Field(..., description="话题起点（全片时间轴，秒）")
    end_sec: float = Field(..., description="话题终点（全片时间轴，秒）")
    summary: Optional[str] = None


class SmartOutlineClipScore(BaseModel):
    clip_id: str
    start_time: float
    end_time: float
    excitement: float = Field(..., ge=0.0, le=1.0, description="精彩度 0~1")
    reason: Optional[str] = None


class SmartOutlineMeta(BaseModel):
    context_clip_count: int
    clips_with_asr: int
    clips_with_vlm: int
    note: str = "分析以 ASR 台词为主；若存在 VLM 画面描述则作辅助，不得喧宾夺主。"


class SmartOutlineResponse(BaseModel):
    video_id: str
    video_title: str
    outline_markdown: str
    topics: List[SmartOutlineTopic]
    clip_scores: List[SmartOutlineClipScore]
    meta: SmartOutlineMeta


class SmartOutlineBundle(BaseModel):
    """GET 用：无记录时 outline 为 null。"""

    outline: Optional[SmartOutlineResponse] = None
    updated_at: Optional[str] = None


class SmartOutlineGenerateResponse(SmartOutlineResponse):
    """生成并落库后返回。"""

    updated_at: str
