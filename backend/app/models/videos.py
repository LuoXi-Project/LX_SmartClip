from typing import Literal, Optional

from pydantic import BaseModel, Field


class RenamePayload(BaseModel):
    name: str


class ImportVideoByUrlPayload(BaseModel):
    url: str = Field(..., min_length=5, description="要下载的视频链接（由 yt-dlp 处理）")
    title: Optional[str] = Field(None, description="可选：导入后素材名称")
    resolution: Literal["best", "1080p", "720p", "480p", "360p"] = Field(
        "best",
        description="下载分辨率上限",
    )
    fps_limit: Optional[int] = Field(
        None,
        ge=24,
        le=60,
        description="可选：帧率上限（24-60）",
    )
    prefer_mp4: bool = Field(
        True,
        description="优先选择 mp4/m4a 组合并合并输出 mp4",
    )

