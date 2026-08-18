"""外部平台（抖音 / YouTube）关键词搜索采集：共享数据结构与异常。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

PLATFORM_DOUYIN = "douyin"
PLATFORM_YOUTUBE = "youtube"

SUPPORTED_PLATFORMS = (PLATFORM_DOUYIN, PLATFORM_YOUTUBE)

PLATFORM_LABELS = {
    PLATFORM_DOUYIN: "抖音",
    PLATFORM_YOUTUBE: "YouTube",
}


class ExternalSearchError(Exception):
    """外部搜索通用异常。"""


class DouyinSearchError(ExternalSearchError):
    pass


class YoutubeSearchError(ExternalSearchError):
    pass


@dataclass
class ExternalSearchResult:
    """一条外部平台搜索结果（预览卡片 / 下载目标的最小单元）。"""

    platform: str                      # douyin | youtube
    video_id: str                      # 平台视频 ID（去重键）
    title: str = ""
    author: str = ""
    duration_sec: float | None = None  # 拿不到时为 None（不参与时长过滤）
    url: str = ""                      # 规范化 URL（下载入口 / 入库 source_url）
    cover_url: str = ""
    view_count: int | None = None
    keyword: str = ""                  # 命中的搜索词（预览分组 / 入库备注）
    stats_text: str = ""               # 前端展示用（点赞/播放等原始文案）

    def dedupe_key(self) -> tuple[str, str]:
        return (self.platform, self.video_id)

    def to_payload(self) -> dict:
        d = asdict(self)
        if d.get("duration_sec") is None:
            d["duration_sec"] = None
        return d


@dataclass
class IngestFailure:
    """单个目标下载/入库失败记录（不阻断整体任务）。"""

    title: str
    url: str
    platform: str = ""
    error: str = ""

    def to_payload(self) -> dict:
        return asdict(self)
