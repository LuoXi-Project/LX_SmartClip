"""文案驱动的 Pexels / 本地素材成片 API 模型"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.subtitle import BgmMixConfig, SubtitleStyle


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
    num_paragraphs: int = Field(5, ge=1, le=1000, description="期望段落数")


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


class PexelsImageSummary(BaseModel):
    id: int
    width: int = 0
    height: int = 0
    image: str = Field("", description="预览图 URL")
    user_name: str = ""


class ScriptStockPexelsSearchResponse(BaseModel):
    page: int
    per_page: int
    total_results: int
    videos: List[PexelsVideoSummary] = Field(default_factory=list)
    images: List[PexelsImageSummary] = Field(default_factory=list)


class ScriptStockPexelsDownloadRequest(BaseModel):
    pexels_media_id: int = Field(..., description="Pexels 视频或图片 id")
    media_type: Literal["video", "image"] = Field("video", description="下载视频或静态图片（图片在成片时做静帧）")
    preferred_quality: Literal["medium", "hd", "sd", "hls"] = Field(
        "hd",
        description="video 时优先选取的 video_files.quality",
    )
    search_query: str = Field(
        "",
        description="下载时使用的搜索关键词，写入缓存元数据便于列表识别",
    )


class ScriptStockPexelsDownloadResponse(BaseModel):
    stored_rel_path: str
    public_url: str
    filename: str


StockTimelineMode = Literal["follow_narration", "follow_material"]
StockVideoExtendPolicy = Literal["loop_video_to_cover", "freeze_last_frame"]
StockMaterialTtsFill = Literal["pad_silence", "loop_audio"]
StockTtsLongerThanMaterial = Literal["trim_tts", "stretch_audio"]


class ScriptStockLibraryTrimPart(BaseModel):
    """与 library_video_ids 同序；对该条素材在源文件时间轴上的选用区间（秒）。"""

    in_sec: float = Field(0.0, ge=0, description="入点（秒）")
    out_sec: float = Field(..., gt=0, description="出点（秒），须大于入点")


class ScriptStockComposeSegment(BaseModel):
    kind: Literal["library", "pexels", "pixabay", "unsplash"] = Field(
        ...,
        description="library=素材库；pexels/pixabay/unsplash=已下载到 stock_media 对应子目录的文件",
    )
    video_id: Optional[str] = Field(None, description="kind=library 时与 library_video_ids 二选一（单段）")
    library_video_ids: Optional[List[str]] = Field(
        None,
        description="kind=library 时可选：按顺序多段拼接（仅允许与「仅 TTS」同时使用）；非空时优先于 video_id",
    )
    library_trims: Optional[List[ScriptStockLibraryTrimPart]] = Field(
        None,
        description="与 library_video_ids 等长时可省略（服务端按整段探测）；指定时每槽选用区间（秒）",
    )
    stored_rel_path: Optional[str] = Field(
        None,
        description="kind=pexels 时单文件路径；与 pexels_stored_rel_paths 二选一",
    )
    pexels_stored_rel_paths: Optional[List[str]] = Field(
        None,
        description="kind=pexels 时可选：多文件按顺序拼接（仅「仅 TTS」）；非空时优先于 stored_rel_path",
    )
    pixabay_stored_rel_paths: Optional[List[str]] = Field(
        None,
        description="kind=pixabay 时多文件路径；规则同 pexels_stored_rel_paths",
    )
    unsplash_stored_rel_paths: Optional[List[str]] = Field(
        None,
        description="kind=unsplash 时多文件路径（静态图，成片时静帧）；规则同 pexels",
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
    bgm: Optional[BgmMixConfig] = Field(
        None,
        description="成片导出后叠加背景音乐（FFmpeg 混音）；与手动匹配/字幕导出一致",
    )


class ScriptStockComposeResponse(BaseModel):
    filename: str
    public_url: str
    stored_rel_path: str


class ScriptStockPexelsCacheItem(BaseModel):
    pexels_video_id: int = Field(0, description="从文件名解析；无法解析时为 0")
    media_type: Literal["image", "video"] = Field("video", description="缓存文件类型")
    stored_rel_path: str
    filename: str
    size_bytes: int = 0
    mtime: float = Field(0, description="修改时间 Unix 秒，用于同 id 多文件时选最新")
    search_query: str = Field("", description="下载时记录的搜索词（来自 pexels/download）")
    pexels_image: str = Field("", description="Pexels 缩略图 URL，下载时写入")
    duration_sec: int = Field(0, description="视频标注时长（秒）；图片为 0")


class ScriptStockPexelsCacheResponse(BaseModel):
    items: List[ScriptStockPexelsCacheItem]


class ScriptStockPexelsDeleteRequest(BaseModel):
    stored_rel_path: str = Field(..., description="须为 stock_media/pexels 下的相对存储路径")


class ScriptStockPexelsDeleteResponse(BaseModel):
    ok: bool = True


class ScriptStockPexelsClearCacheResponse(BaseModel):
    ok: bool = True
    deleted_files: int = Field(0, description="已删除的视频文件数")


# --- Pixabay ---


class PixabayVideoRendition(BaseModel):
    url: str
    width: int = 0
    height: int = 0
    size: int = 0
    thumbnail: str = ""


class PixabayVideoSummary(BaseModel):
    id: int
    width: int = 0
    height: int = 0
    duration: int = 0
    image: str = Field("", description="预览图 URL")
    user_name: str = ""
    tags: str = ""
    videos: dict[str, PixabayVideoRendition] = Field(default_factory=dict)


class PixabayImageSummary(BaseModel):
    id: int
    width: int = 0
    height: int = 0
    image: str = ""
    user_name: str = ""
    tags: str = ""


class ScriptStockPixabaySearchResponse(BaseModel):
    page: int
    per_page: int
    total_results: int
    videos: List[PixabayVideoSummary] = Field(default_factory=list)
    images: List[PixabayImageSummary] = Field(default_factory=list)


class ScriptStockPixabayDownloadRequest(BaseModel):
    pixabay_media_id: int = Field(..., description="Pixabay 视频或图片 id")
    media_type: Literal["video", "image"] = Field("video", description="下载视频或静态图片")
    preferred_quality: Literal["large", "medium", "small", "tiny"] = Field(
        "medium",
        description="video 时 videos 清晰度键；image 时为 largeImageURL 等等级",
    )
    search_query: str = Field("", description="下载时搜索关键词，写入缓存元数据")


class ScriptStockPixabayDownloadResponse(BaseModel):
    stored_rel_path: str
    public_url: str
    filename: str


class ScriptStockPixabayCacheItem(BaseModel):
    pixabay_video_id: int = 0
    media_type: Literal["image", "video"] = "video"
    stored_rel_path: str
    filename: str
    size_bytes: int = 0
    mtime: float = 0
    search_query: str = ""
    preview_image: str = ""
    duration_sec: int = 0


class ScriptStockPixabayCacheResponse(BaseModel):
    items: List[ScriptStockPixabayCacheItem]


class ScriptStockPixabayDeleteRequest(BaseModel):
    stored_rel_path: str


class ScriptStockPixabayDeleteResponse(BaseModel):
    ok: bool = True


class ScriptStockPixabayClearCacheResponse(BaseModel):
    ok: bool = True
    deleted_files: int = 0


# --- Unsplash（下载时转为静音短视频） ---


class UnsplashPhotoSummary(BaseModel):
    id: str
    width: int = 0
    height: int = 0
    description: str = ""
    image: str = Field("", description="缩略图 URLs.small 或 regular")
    user_name: str = ""
    color: str = ""


class ScriptStockUnsplashSearchResponse(BaseModel):
    page: int
    per_page: int
    total_results: int
    photos: List[UnsplashPhotoSummary]


class ScriptStockUnsplashDownloadRequest(BaseModel):
    unsplash_photo_id: str = Field(..., description="Unsplash photo id")
    search_query: str = Field("", description="下载时搜索关键词")


class ScriptStockUnsplashDownloadResponse(BaseModel):
    stored_rel_path: str
    public_url: str
    filename: str


class ScriptStockUnsplashCacheItem(BaseModel):
    unsplash_photo_id: str = ""
    media_type: Literal["image", "video"] = "image"
    stored_rel_path: str
    filename: str
    size_bytes: int = 0
    mtime: float = 0
    search_query: str = ""
    preview_image: str = ""
    duration_sec: int = 0


class ScriptStockUnsplashCacheResponse(BaseModel):
    items: List[ScriptStockUnsplashCacheItem]


class ScriptStockUnsplashDeleteRequest(BaseModel):
    stored_rel_path: str


class ScriptStockUnsplashDeleteResponse(BaseModel):
    ok: bool = True


class ScriptStockUnsplashClearCacheResponse(BaseModel):
    ok: bool = True
    deleted_files: int = 0
