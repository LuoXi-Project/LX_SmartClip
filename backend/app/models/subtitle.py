"""subtitle.py — 字幕相关的数据模型（Pydantic schemas）。"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class TtsVideoAlignConfig(BaseModel):
    """成片段落：画面时长与系统 TTS 配音不一致时的对齐策略（主要针对「配音长于所选画面」）。"""

    policy: Literal[
        "freeze_last_frame",
        "loop_video_to_cover",
        "stretch_audio",
        "stretch_video",
    ] = Field(
        "freeze_last_frame",
        description="freeze_last_frame=不加速画面，末尾定格直至配音结束；loop_video_to_cover=重复拼接所选素材直至盖住配音；stretch_audio=变速压缩/拉伸配音以贴合画面时长；stretch_video=变速拉伸/压缩画面以贴合配音时长",
    )
    max_audio_atempo: float = Field(
        2.0,
        ge=1.0,
        le=4.0,
        description="stretch_audio：允许的最大配音加速倍数（越大越急促）",
    )
    min_audio_atempo: float = Field(
        0.5,
        ge=0.25,
        le=1.0,
        description="stretch_audio：允许的最小配音减速倍数（越小越拖沓）",
    )
    max_video_pts_factor: float = Field(
        2.0,
        ge=1.0,
        le=4.0,
        description="stretch_video：画面「变慢」时 setpts 倍数上限（约为慢放倍率上限）",
    )
    min_video_pts_factor: float = Field(
        0.5,
        ge=0.25,
        le=1.0,
        description="stretch_video：画面「变快」时 setpts 倍数下限（约为快放倍率上限）",
    )


class ClipTrimPart(BaseModel):
    """单条素材在切片文件内的使用区间（与前端出入点一致）。"""

    clip_id: str
    clip_start_sec: float = 0.0
    duration_sec: float


class SubtitleSegmentInput(BaseModel):
    copy_text: str
    clip_id: str
    clip_ids: Optional[List[str]] = None
    tts_filename: Optional[str] = None
    # 用于“原声导出”精确裁剪：表示从该 clip 内部的起点（秒）开始截取。
    # 仅建议在当前实现支持的场景使用（例如 quick-cut 单 clip）。
    clip_start_sec: Optional[float] = None
    # 可控时长：当用户在前端手动调整段落时长时使用（单位秒）。
    # 注：对 TTS 段落如强制缩短会截断音频；对非 TTS 段落会裁剪视频输出以对齐字幕时间轴。
    duration_sec: Optional[float] = None
    # 多选素材时每条 clip 的入点与使用时长；存在时优先于单段的 clip_start_sec/duration_sec。
    clip_trims: Optional[List[ClipTrimPart]] = None
    # 成片字幕时间轴用时长（秒）；由 TTS 对齐策略推导后写入，优先于 ffprobe(TTS) 与 duration_sec 的 min 规则
    timeline_duration_sec: Optional[float] = None


class SubtitleStyle(BaseModel):
    font_name: str = "Arial"
    font_size: int = 24
    font_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_width: float = 2.0
    shadow: float = 1.0
    bold: bool = False
    italic: bool = False
    position: str = "bottom"  # bottom | center | top
    margin_v: int = 20
    pos_x_pct: float = 50.0
    pos_y_pct: float = 90.0
    background: bool = False
    background_pad_x: float = 6.0
    background_pad_y: float = 3.0
    background_opacity: int = 55
    max_chars_per_line: int = 20


class GenerateSRTRequest(BaseModel):
    segments: List[SubtitleSegmentInput]
    style: Optional[SubtitleStyle] = None
    use_tts_timing: bool = True


class SRTEntry(BaseModel):
    index: int
    start: float
    end: float
    text: str
    clip_id: str


class GenerateSRTResponse(BaseModel):
    srt_content: str
    entries: List[SRTEntry]
    total_duration: float
    timing_source: str


class BurnSubtitleResponse(BaseModel):
    filename: str
    url: str
    jianying_draft_filename: Optional[str] = None
    jianying_draft_url: Optional[str] = None


class BgmTimelineSegment(BaseModel):
    start_sec: float
    end_sec: float
    track_id: Optional[str] = None
    volume_db: Optional[float] = None


class BgmMixConfig(BaseModel):
    enabled: bool = False
    track_id: Optional[str] = None
    track_ids: Optional[List[str]] = None
    track_volumes_db: Optional[dict[str, float]] = None
    volume_db: float = -12.0
    loop: bool = True
    fade_in_sec: float = 0.8
    fade_out_sec: float = 1.0
    timeline_segments: Optional[List[BgmTimelineSegment]] = None


class BurnSubtitleRequest(BaseModel):
    segments: List[SubtitleSegmentInput]
    srt_content: str
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    project_name: Optional[str] = "smartclip_subtitled"
    also_export_jianying_draft: bool = Field(
        False,
        description="为 True 时在成片生成后额外导出剪映草稿 ZIP（与成片同源时间轴与素材）",
    )
    export_backend: Optional[str] = None  # ffmpeg | moviepy（留空则使用 config.export_backend）
    # 默认：成片阶段会按 TTS 校验并在必要时重建时间轴，确保最终对齐配音。
    # 若用户已在前端手动微调时间轴并希望“完全按传入 SRT 烧录”，则置为 True。
    strict_use_client_srt: bool = False
    bgm: Optional[BgmMixConfig] = None
    # 默认 True：按 clips 在整片上的时间窗从「原始素材视频」裁剪；False 时用预处理 clip 文件（更快、画质取决于切片参数）
    materialize_from_source: bool = True
    # TTS 成片：画面与配音时长对齐策略（默认 None 时保持旧行为：循环拼接素材组）
    tts_align: Optional[TtsVideoAlignConfig] = None


class ExportOriginalRequest(BaseModel):
    """
    原声导出：
    - 不使用 TTS（忽略 tts_filename）
    - 段落（segments 内每一段）的总时长 = 该段选中 clip 组的时长之和
    - 可选：按“句子/换行”切分文案，并在该段总时长内等分
    - 可选：对最终音频做归一化/限幅
    """

    segments: List[SubtitleSegmentInput]
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    also_export_jianying_draft: bool = Field(
        False,
        description="为 True 时在成片生成后额外导出剪映草稿 ZIP",
    )
    project_name: Optional[str] = "smartclip_original"
    include_subtitle: bool = True
    normalize_audio: bool = True
    export_backend: Optional[str] = None  # ffmpeg | moviepy（留空则使用 config.export_backend）
    bgm: Optional[BgmMixConfig] = None
    # 默认 True：从原始完整视频按时间窗裁剪拼接；False：仅用预处理 clip（旧行为）
    materialize_from_source: bool = True

