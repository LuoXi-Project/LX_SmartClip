"""subtitle.py — 字幕相关的数据模型（Pydantic schemas）。"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


from app.models.production import ProductionProfile


class SegmentVisualEffect(BaseModel):
    """混剪段落级视觉随机变换（成片 materialize 时应用）。"""

    zoom: Optional[float] = Field(None, description="放大倍率，如 1.15")
    mirror: bool = False
    rotation_deg: Optional[float] = Field(None, description="旋转角度（度）")
    color_intensity: Optional[float] = Field(
        None, description="调色强度 -0.15~0.15，影响饱和度/对比/色相"
    )


class TtsVideoAlignConfig(BaseModel):
    """成片段落：画面时长与系统 TTS 配音不一致时的对齐策略（主要针对「配音长于所选画面」）。"""

    policy: Literal[
        "freeze_last_frame",
        "preserve_video_duration",
        "loop_video_to_cover",
        "loop_playlist_to_cover",
        "stretch_audio",
        "stretch_video",
    ] = Field(
        "freeze_last_frame",
        description=(
            "freeze_last_frame=不加速画面，末尾定格直至配音结束；配音短于画面时裁切画面；"
            "preserve_video_duration=视频配音推荐：配音短于画面时保留完整画面并补静音，"
            "配音长于画面时末尾定格；"
            "loop_video_to_cover=仅重复本段所选素材直至盖住配音；"
            "loop_playlist_to_cover=按成片顺序轮播全部素材直至盖住配音（混剪推荐）；"
            "stretch_audio=变速压缩/拉伸配音以贴合画面时长；"
            "stretch_video=变速拉伸/压缩画面以贴合配音时长"
        ),
    )
    playlist_clip_ids: Optional[List[str]] = Field(
        None,
        description="loop_playlist_to_cover 时使用的素材顺序（成片 clip_id 列表）；为空则由烧录管线按 segments 顺序自动收集",
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
    split_narration_by_sentence: bool = Field(
        False,
        description=(
            "True=按逗号/顿号等拆成短条配音，并拆段匹配画面；"
            "False=仅按句号/换行分条，整段连贯配音（画面偏短时用上方对齐策略补偿）"
        ),
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
    # 混剪「仅 BGM / 素材全静音」：保留画面，音轨置零
    mute_audio: bool = False
    # 混剪视觉随机变换（段落级 materialize 滤镜）
    visual_effect: Optional[SegmentVisualEffect] = None
    # 进入本段的转场（与 Plan.transition 对齐；首段可为 fade_in）
    transition_in: Optional[
        Literal["hard_cut", "cross_dissolve", "fade_in", "fade_out"]
    ] = None


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
    motion_template: Literal["static", "fade", "pop", "slide_up"] = "static"
    motion_fade_ms: int = Field(150, ge=50, le=600)


class GenerateSRTRequest(BaseModel):
    segments: List[SubtitleSegmentInput]
    style: Optional[SubtitleStyle] = None
    use_tts_timing: bool = True
    split_narration_by_sentence: bool = Field(
        False,
        description="True=字幕按逗号/顿号等拆短条；False=仅按句号/换行分条（默认）",
    )


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


class JianYingDraftExportRequest(BaseModel):
    """仅导出剪映草稿 ZIP，不渲染成片 MP4。"""

    mode: Literal["tts", "original"]
    segments: List[SubtitleSegmentInput]
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    project_name: Optional[str] = "smartclip_jianying"
    # tts：与 burn 一致的字幕时间轴输入
    srt_content: str = ""
    strict_use_client_srt: bool = False
    # original：是否在草稿中生成字幕轨
    include_subtitle: bool = True
    # 与成片一致的 TTS 时长对齐覆盖（可选）
    tts_align: Optional[TtsVideoAlignConfig] = None


class JianYingDraftExportResponse(BaseModel):
    """剪映草稿导出：未配置本地父目录时为 ZIP 下载；配置后为直接写入目录。"""

    mode: Literal["zip", "direct"] = "zip"
    filename: str = ""
    url: str = ""
    local_path: str = ""


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
    export_backend: Optional[str] = None  # ffmpeg | moviepy（留空则使用 config.export_backend）
    # 默认：成片阶段会按 TTS 校验并在必要时重建时间轴，确保最终对齐配音。
    # 若用户已在前端手动微调时间轴并希望“完全按传入 SRT 烧录”，则置为 True。
    strict_use_client_srt: bool = False
    bgm: Optional[BgmMixConfig] = None
    # 默认 True：按 clips 在整片上的时间窗从「原始素材视频」裁剪；False 时用预处理 clip 文件（更快、画质取决于切片参数）
    materialize_from_source: bool = True
    # TTS 成片：画面与配音时长对齐策略（默认 None 时保持旧行为：循环拼接素材组）
    tts_align: Optional[TtsVideoAlignConfig] = None
    # 一键成片 / 口播 TTS 管线：有文案的段必须有可用 TTS 文件，禁止回退素材原声
    require_tts_audio: bool = False
    production_profile: Optional[ProductionProfile] = None


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
    project_name: Optional[str] = "smartclip_original"
    include_subtitle: bool = True
    normalize_audio: bool = True
    export_backend: Optional[str] = None  # ffmpeg | moviepy（留空则使用 config.export_backend）
    bgm: Optional[BgmMixConfig] = None
    # 默认 True：从原始完整视频按时间窗裁剪拼接；False：仅用预处理 clip（旧行为）
    materialize_from_source: bool = True
    production_profile: Optional[ProductionProfile] = None

