from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

PlatformName = Literal["douyin", "youtube"]


class ExternalSearchPreviewRequest(BaseModel):
    """搜索预览：只搜不下载，返回结果卡片供勾选。"""

    keywords: List[str] = Field(
        default_factory=list,
        description="搜索关键词列表（与 copy_text 二选一；每行一个）",
    )
    copy_text: str = Field(
        "",
        description="整段文案/标题：为空且 keywords 也为空时由 LLM 提取关键词",
    )
    platforms: List[PlatformName] = Field(
        default_factory=lambda: ["douyin"],
        description="搜索平台（douyin / youtube）",
    )
    limit_per_keyword: int = Field(
        5,
        ge=1,
        le=20,
        description="每个关键词每个平台返回的条数",
    )
    extract_keywords: bool = Field(
        True,
        description="copy_text 非空且 keywords 为空时是否用 LLM 提取关键词",
    )

    @field_validator("keywords")
    @classmethod
    def _clean_keywords(cls, v: List[str]) -> List[str]:
        cleaned = [k.strip() for k in v if k and k.strip()]
        if len(cleaned) > 20:
            raise ValueError("关键词最多 20 个")
        return cleaned


class ExternalSearchResultItem(BaseModel):
    platform: PlatformName
    video_id: str = ""
    title: str = ""
    author: str = ""
    duration_sec: Optional[float] = None
    url: str
    cover_url: str = ""
    view_count: Optional[int] = None
    keyword: str = ""
    stats_text: str = ""


class ExternalSearchExtraction(BaseModel):
    method: Literal["llm", "fallback"] = "llm"
    reason: str = ""


class ExternalSearchPreviewResponse(BaseModel):
    keywords: List[str]
    results: List[ExternalSearchResultItem]
    notes: List[str] = Field(default_factory=list, description="各平台搜索过程中的提示/跳过原因")
    extraction: Optional[ExternalSearchExtraction] = Field(
        None,
        description="关键词提取方式（copy_text 模式）：llm=AI 提取；fallback=降级文本切分（含原因）",
    )


class ExternalSearchIngestRequest(BaseModel):
    """自动采集任务：搜索 → 下载入库 → 自动进预处理队列。"""

    keywords: List[str] = Field(default_factory=list, description="显式关键词")
    copy_text: str = Field("", description="整段文案（由任务内 LLM 提取关键词）")
    platforms: List[PlatformName] = Field(
        default_factory=lambda: ["douyin"],
        description="搜索平台",
    )
    limit_per_keyword: Optional[int] = Field(
        None,
        ge=1,
        le=10,
        description="每个关键词下载条数（默认取 config external_search_limit_per_keyword=3）",
    )
    resolution: Optional[Literal["best", "1080p", "720p", "480p", "360p"]] = Field(
        None,
        description="下载分辨率上限（默认取 config external_search_resolution）",
    )
    auto_process: bool = Field(True, description="下载完成后自动进入预处理队列")
    selected_items: Optional[List[ExternalSearchResultItem]] = Field(
        None,
        description="预览勾选模式：直接下载这些目标（给出时忽略搜索参数）",
    )


class ExternalSearchIngestResponse(BaseModel):
    job_id: str
    status: str
    stream_url: str


class DouyinLoginStatusResponse(BaseModel):
    cookie_ready: bool
    message: str
    accounts: List[str] = Field(default_factory=list)
