"""auto_edit 模块的数据模型定义。"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator
from app.models.subtitle import (
    SubtitleStyle,
)


class PlanKeepFlags(BaseModel):
    clips: bool = False
    subtitles: bool = False
    transitions: bool = False
    bgm: bool = False


class TimingHint(BaseModel):
    start: float
    end: float


class SubtitlePlan(BaseModel):
    strategy: Literal["auto", "asr", "rewrite", "none"] = "auto"
    text: str
    source: Literal["asr", "llm", "vlm", "user"] = "llm"
    timing_hint: Optional[TimingHint] = None

    @field_validator("source", mode="before")
    @classmethod
    def _normalize_subtitle_source(cls, v: object) -> object:
        """
        LLM 可能会把来源写成组合（例如 `asr+vlm`）。
        下游当前只使用 `subtitle.text`，因此这里做归一化以通过 Plan 校验。
        """
        if not isinstance(v, str):
            return v
        v = v.strip()
        if not v:
            return v

        # 典型问题：`asr+vlm` 不在 SubtitlePlan.source 的枚举范围内
        # 归一化策略：优先取最左侧 token（asr / llm / vlm / user）
        if "+" in v:
            return v.split("+", 1)[0].strip()
        return v


class TransitionPlan(BaseModel):
    type: Literal["hard_cut", "cross_dissolve", "fade_in", "fade_out"] = "hard_cut"
    duration_sec: float = 0.3


class ClipRef(BaseModel):
    clip_id: str
    video_id: str
    weight: float = 1.0


class SegmentPlan(BaseModel):
    id: str
    chapter_id: Optional[str] = None
    order: int
    clip_group: List[ClipRef]
    selected_clip_ids: List[str]
    start_time_sec: float
    end_time_sec: float
    # 前端可编辑：覆盖该段的成片时长（秒），用于更可控的节奏/字幕时长
    override_duration_sec: Optional[float] = None
    audio_mode: Literal["original", "tts", "mute"] = "original"
    subtitle: SubtitlePlan
    transition: Optional[TransitionPlan] = None


class BGMPlan(BaseModel):
    enabled: bool = False
    source: Literal["library", "user", "ai"] = "library"
    track_id: Optional[str] = None
    volume_db: float = -12.0
    loop: bool = True
    fade_in_sec: float = 0.8
    fade_out_sec: float = 1.0


class Constraints(BaseModel):
    max_clip_per_segment: int = 3
    match_strategy: Literal["asr+vlm", "asr", "vlm"] = "asr+vlm"
    respect_user_video_order: bool = False


class Plan(BaseModel):
    plan_id: str
    title: str
    summary: str
    # Timeline Engine 方案补充的“素材视频元信息”（兼容字段：旧数据/旧前端可忽略）
    video_title: Optional[str] = None
    video_description: Optional[str] = None
    mode: Literal["auto", "voiceover", "original"] = "auto"
    target_duration_sec: Optional[float] = None
    estimated_duration_sec: Optional[float] = None
    chapters: Optional[List[dict]] = None
    segments: List[SegmentPlan]
    bgm: Optional[BGMPlan] = None
    constraints: Optional[Constraints] = None
    keep_flags: Optional[PlanKeepFlags] = None


class AutoEditPlanRequest(BaseModel):
    video_ids: List[str] = Field(..., description="选中视频 ID 列表")
    user_prompt: str = Field(..., min_length=1, description="用户提示词/需求")
    mode: Literal["auto", "voiceover", "original"] = "auto"
    target_duration_sec: Optional[int] = Field(
        None, ge=10, le=600, description="目标时长（秒）"
    )
    num_plans: int = Field(3, ge=1, le=5, description="候选方案数量")
    allow_cross_video: bool = True
    subtitle_policy: Literal["auto", "asr", "rewrite", "none"] = "auto"
    transition_policy: Literal["auto", "hard_cut", "soft"] = "auto"
    bgm_policy: Literal["auto", "none", "user", "ai"] = "auto"
    plan_keep_flags: Optional[PlanKeepFlags] = None
    prev_plan_id: Optional[str] = None
    prev_plan: Optional[Plan] = None
    # 低侵入升级开关：默认 False，保持旧行为（LLM 直接生成 Plan）
    use_timeline_engine: bool = Field(
        False,
        description="是否启用“事件级时间轴”新引擎（DSL→Events→Timeline→Plan），默认关闭",
    )
    # 可解释性输出：第一版仅用于调试（API 暂不保证返回该字段）
    explain: bool = Field(
        False,
        description="是否生成可解释中间产物（events/tiers/timeline）用于调试与回放，默认关闭",
    )


class AutoEditPlanResponse(BaseModel):
    plans: List[Plan]


class AutoEditPlanSessionResponse(BaseModel):
    session_id: str
    stream_url: str


class AutoEditRealizeRequest(BaseModel):
    plan: Plan
    project_name: Optional[str] = None
    include_subtitle: bool = True
    style: Optional[SubtitleStyle] = None


class AutoEditRealizeResponse(BaseModel):
    mode: Literal["voiceover", "original"]
    filename: str
    url: str
