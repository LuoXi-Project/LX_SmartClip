"""文案驱动的 Pexels / 本地素材成片 API 模型"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.subtitle import SubtitleStyle


class ScriptStockSplitRequest(BaseModel):
    script: str = Field(..., description="完整文案")
    mode: Literal["paragraph", "line"] = Field(
        "paragraph",
        description="paragraph=按空行分段；line=按单行分段",
    )


class ScriptStockSplitResponse(BaseModel):
    segments: List[str]


class ScriptStockGenerateScriptRequest(BaseModel):
    topic: str = Field(..., description="主题或关键词")
    style_hint: str = Field("", description="风格补充")
    num_paragraphs: int = Field(5, ge=1, le=20, description="期望段落数")


class ScriptStockGenerateScriptResponse(BaseModel):
    script: str


class ScriptStockSuggestQueriesRequest(BaseModel):
    segments: List[str] = Field(..., description="分段文案，与顺序一致")


class ScriptStockSuggestQueriesResponse(BaseModel):
    queries: List[str] = Field(..., description="每段对应英文搜索词（与 segments 等长）")


class PexelsVideoFile(BaseModel):
    quality: str
    width: int
    height: int
    link: str


class PexelsVideoSummary(BaseModel):
    id: int
    width: int
    height: int
    duration: int
    image: str
    user_name: str = ""
    video_files: List[PexelsVideoFile] = Field(default_factory=list)


class ScriptStockPexelsSearchResponse(BaseModel):
    page: int
    per_page: int
    total_results: int
    videos: List[PexelsVideoSummary]


class ScriptStockPexelsDownloadRequest(BaseModel):
    pexels_video_id: int = Field(..., description="Pexels 视频 id")
    preferred_quality: Literal["medium", "hd", "sd", "hls"] = Field(
        "hd",
        description="优先选取的 video_files.quality",
    )


class ScriptStockPexelsDownloadResponse(BaseModel):
    stored_rel_path: str
    public_url: str
    filename: str


StockTimelineMode = Literal["follow_narration", "follow_material"]
StockVideoExtendPolicy = Literal["loop_video_to_cover", "freeze_last_frame"]
StockMaterialTtsFill = Literal["pad_silence", "loop_audio"]
StockTtsLongerThanMaterial = Literal["trim_tts", "stretch_audio"]


class ScriptStockComposeSegment(BaseModel):
    kind: Literal["library", "pexels"] = Field(..., description="library=素材库整段视频；pexels=已下载到隔离目录的文件")
    video_id: Optional[str] = Field(None, description="kind=library 时与 library_video_ids 二选一（单段）")
    library_video_ids: Optional[List[str]] = Field(
        None,
        description="kind=library 时可选：按顺序多段拼接（仅允许与「仅 TTS」同时使用）；非空时优先于 video_id",
    )
    stored_rel_path: Optional[str] = Field(None, description="kind=pexels 时必填，须为 storage/stock_media/pexels/ 下路径")
    trim_sec: float = Field(
        0,
        ge=0,
        le=600,
        description="截取前若干秒；0 表示使用整段素材时长",
    )
    text: Optional[str] = Field(
        None,
        description="该段配音文案（tts_only/mix 时使用；空则该段为静音配音）",
    )


class ScriptStockComposeRequest(BaseModel):
    segments: List[ScriptStockComposeSegment] = Field(..., description="按成片顺序")
    project_name: str = Field("stock_clip", description="输出文件名前缀")
    audio_mode: Literal["tts_only", "original_only", "mix"] = Field(
        "tts_only",
        description="tts_only=仅 TTS 配音（画面素材静音）；original_only=保留素材原声；mix=TTS 与原声混合（可调音量）",
    )
    tts_volume_db: float = Field(0.0, ge=-60.0, le=12.0, description="TTS 轨音量（dB）")
    original_volume_db: float = Field(
        -6.0,
        ge=-60.0,
        le=12.0,
        description="素材原声音量（dB），仅 original_only / mix 生效",
    )
    tts_voice: Optional[str] = Field(None, description="覆盖默认 TTS 音色（可选）")
    tts_rate: Optional[str] = Field(None, description="语速，如 +0%（可选）")
    tts_volume: Optional[str] = Field(None, description="TTS 引擎音量百分比（可选，与成片 dB 无关）")
    timeline_mode: StockTimelineMode = Field(
        "follow_narration",
        description="follow_narration=与手动匹配一致：以配音时长为准（TTS 短则裁画面，长则循环/定格画面）；follow_material=以素材成片时长为准（TTS 短则补静音或循环配音，长则裁切或变速压缩配音）",
    )
    video_extend_policy: StockVideoExtendPolicy = Field(
        "loop_video_to_cover",
        description="配音长于画面时：循环拼接画面或尾帧定格直至盖住配音",
    )
    material_tts_fill: StockMaterialTtsFill = Field(
        "pad_silence",
        description="follow_material 且 TTS 短于画面：尾段补静音或循环播放该段 TTS",
    )
    material_tts_longer: StockTtsLongerThanMaterial = Field(
        "stretch_audio",
        description="follow_material 且 TTS 长于画面：裁掉多余配音或变速压缩配音以贴合画面（受 stretch 上下限约束）",
    )
    include_subtitle: bool = Field(
        False,
        description="为 True 时按各段成片时长与文案硬烧字幕（与手动匹配成片逻辑一致，样式见 subtitle_style）",
    )
    subtitle_style: Optional[SubtitleStyle] = Field(
        None,
        description="字幕样式；为空则使用默认 SubtitleStyle",
    )


class ScriptStockComposeResponse(BaseModel):
    filename: str
    public_url: str
    stored_rel_path: str
