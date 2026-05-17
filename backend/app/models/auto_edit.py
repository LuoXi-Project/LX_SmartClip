"""auto_edit 模块的数据模型定义。"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator
from app.models.subtitle import (
    ClipTrimPart,
    SubtitleStyle,
    TtsVideoAlignConfig,
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
    # 成片跳过该段（口播快剪/一键成片）；字幕与时间轴按剩余段落顺序连续拼接
    exclude_from_output: bool = False
    # 前端可编辑：覆盖该段的成片时长（秒），用于更可控的节奏/字幕时长
    override_duration_sec: Optional[float] = None
    # 原声导出增强：当为单个 clip 的“内部片段”时，用于 ffmpeg -ss 截取。
    # 默认 None：保持旧行为（只按 duration_sec 截取，不偏移）。
    clip_start_offset_sec: Optional[float] = None
    # 多 clip 顺序拼接（与 realize 管线 clip_trims 一致）；存在时优先于单段 clip_start_offset_sec
    clip_trims: Optional[List[ClipTrimPart]] = None
    audio_mode: Literal["original", "tts", "mute"] = "original"
    subtitle: SubtitlePlan
    transition: Optional[TransitionPlan] = None


class BGMPlan(BaseModel):
    enabled: bool = False
    source: Literal["library", "user", "ai"] = "library"
    track_id: Optional[str] = None
    track_ids: Optional[List[str]] = None
    track_volumes_db: Optional[dict[str, float]] = None
    volume_db: float = -12.0
    loop: bool = True
    fade_in_sec: float = 0.8
    fade_out_sec: float = 1.0
    timeline_segments: Optional[List[dict]] = None


class Constraints(BaseModel):
    max_clip_per_segment: int = 3
    match_strategy: Literal["asr+vlm", "asr", "vlm"] = "asr+vlm"
    respect_user_video_order: bool = False
    # 混剪「轮播全部素材」：成片内全部 clip 的播放顺序（与方案分段无关，避免仅轮播 2～3 个）
    mix_playlist_clip_ids: Optional[List[str]] = None


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
    template_preset: Optional[str] = Field(
        None,
        description="模板剪辑预设ID（matchMode=template 时使用），例如 ecommerce/marketing/tech_review/knowledge",
    )
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
    # Timeline Engine 长视频分批参数（任务级）：前端可按具体视频类型选择预设或手动覆盖
    # content_style 仅用于命中默认档位；其余字段为空时使用该档位默认值
    content_style: Optional[Literal["generic", "ecommerce", "voiceover", "commentary"]] = Field(
        None,
        description="内容风格档位（任务级），用于推导 events 分批默认参数",
    )
    events_max_clips_per_batch: Optional[int] = Field(
        None,
        ge=5,
        description="每批最多 clip 数（任务级覆盖）",
    )
    events_max_chars_per_batch: Optional[int] = Field(
        None,
        ge=4000,
        description="每批最多字符数（任务级覆盖）",
    )
    events_batch_overlap_clips: Optional[int] = Field(
        None,
        ge=0,
        description="相邻批次重叠 clip 数（任务级覆盖）",
    )
    events_max_batches: Optional[int] = Field(
        None,
        ge=1,
        description="最多处理批次数（任务级覆盖）",
    )


class MixEditPlanRequest(BaseModel):
    """混剪：多素材分级编排 + 原声/全静音模式。"""

    video_ids: List[str] = Field(..., description="选中视频 ID，顺序影响默认编排优先级")
    mix_audio_mode: Literal["keep_original", "mute_all_original"] = Field(
        "keep_original",
        description="模式一：保留素材原声；模式二：关闭全部原声",
    )
    voice_merge_strategy: Literal["strict_single", "same_voice_concat"] = Field(
        "same_voice_concat",
        description="模式一下的人声策略：严格单路 / 同人声自由拼接（仅 keep_original 生效）",
    )
    mute_audio_track: Literal["ai_tts_asr", "ai_tts_llm", "bgm_only", "ai_tts"] = Field(
        "ai_tts_llm",
        description=(
            "模式二音轨：ai_tts_asr=沿用 ASR 原文 TTS；"
            "ai_tts_llm=AI 生成旁白文案再 TTS；bgm_only=仅 BGM。"
            "（ai_tts 为旧值，等同 ai_tts_asr）"
        ),
    )
    target_duration_sec: Optional[float] = Field(
        None,
        ge=5.0,
        le=7200.0,
        description="可选目标成片时长（秒），用于提示超长方案",
    )
    user_prompt: Optional[str] = Field(
        None,
        description="剪辑诉求；模式二选 ai_tts_llm 时必填，用于 AI 生成旁白",
    )

    @field_validator("mute_audio_track", mode="before")
    @classmethod
    def _normalize_mute_audio_track(cls, v: object) -> object:
        if v == "ai_tts":
            return "ai_tts_asr"
        return v

    @model_validator(mode="after")
    def _require_prompt_for_llm_tts(self) -> "MixEditPlanRequest":
        if self.mix_audio_mode == "mute_all_original" and self.mute_audio_track == "ai_tts_llm":
            if not (self.user_prompt or "").strip():
                raise ValueError("选择「AI 生成文案配音」时请填写剪辑诉求")
        return self


class VoiceoverQuickCutRequest(BaseModel):
    """口播快剪：基于 clips.asr_text 生成原声 Plan（当前成片仍为片段级；句级时间见 clips.asr_segments）。"""

    video_ids: List[str] = Field(..., description="选中视频 ID，顺序即成片片段顺序")
    strategy: Literal["asr_fast", "standard", "semantic", "audio_activity_fast"] = Field(
        "asr_fast",
        description="asr_fast=仅保留有 ASR 的片段；standard≈asr_fast；semantic=LLM 分块筛选句子；audio_activity_fast=按音频活动(静音检测)粗剪",
    )
    user_prompt: Optional[str] = Field(None, description="智能快剪必填：剪辑诉求，用于 LLM 筛选句子")
    target_duration_sec: Optional[float] = Field(
        None,
        ge=5.0,
        le=7200.0,
        description="成片目标总时长（秒）；不设时尝试从 user_prompt 解析（如「2分钟」「120秒」）",
    )
    allow_overlapping_source_timeline: bool = Field(
        False,
        description="是否允许同一素材视频 (video_id) 下多段成片在源文件绝对时间上重叠（默认否；否时先裁切重叠再合并相接段，跨 clip 用 clip_trims 导出）",
    )
    activity_db_threshold: float = Field(
        -36.0,
        ge=-70.0,
        le=-5.0,
        description="audio_activity_fast: 静音检测阈值(dB)，越高越敏感（更容易判为静音）",
    )
    activity_min_silence_sec: float = Field(
        0.25,
        ge=0.05,
        le=2.0,
        description="audio_activity_fast: 识别为静音的最短持续时长(秒)",
    )
    activity_min_keep_sec: float = Field(
        0.35,
        ge=0.1,
        le=10.0,
        description="audio_activity_fast: 保留语音片段最短时长(秒)",
    )
    activity_merge_gap_sec: float = Field(
        0.2,
        ge=0.0,
        le=2.0,
        description="audio_activity_fast: 相邻语音段间隔小于该值时自动合并(秒)",
    )
    activity_head_pad_sec: float = Field(
        0.08,
        ge=0.0,
        le=1.0,
        description="audio_activity_fast: 每段前置补偿时长(秒)",
    )
    activity_tail_pad_sec: float = Field(
        0.12,
        ge=0.0,
        le=1.0,
        description="audio_activity_fast: 每段后置补偿时长(秒)",
    )
    activity_keep_ranges: Optional[List[dict]] = Field(
        None,
        description="audio_activity_fast: 可选，前端预计算的“保留区间”（绝对时间秒）。格式：[{\"video_id\":\"...\",\"start\":0.0,\"end\":1.0}]。提供时优先使用该区间生成方案（用于 pitch 轨调参）。",
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
    # 为 True 时：即使 plan.mode 为 original，也走 TTS 成片管线（用于口播快剪「重新配音」）
    force_tts_pipeline: bool = False
    # 与 force_tts_pipeline / voiceover 成片配合：画面与 TTS 时长对齐策略；None 表示沿用渲染默认（循环拼接素材）
    tts_align: Optional[TtsVideoAlignConfig] = None


class AutoEditRealizeResponse(BaseModel):
    mode: Literal["voiceover", "original"]
    filename: str
    url: str


class AutoEditExportJianyingDraftRequest(BaseModel):
    """一键成片方案 → 仅导出剪映草稿（字段与 realize 对齐，不含成片）。"""

    plan: Plan
    project_name: Optional[str] = None
    include_subtitle: bool = True
    style: Optional[SubtitleStyle] = None
    force_tts_pipeline: bool = False
    tts_align: Optional[TtsVideoAlignConfig] = None
