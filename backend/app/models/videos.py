from typing import Optional

from pydantic import BaseModel, Field


class RenamePayload(BaseModel):
    name: str


class ImportVideoByUrlPayload(BaseModel):
    url: str = Field(..., min_length=5, description="要下载的视频链接（由 yt-dlp 处理）")
    title: Optional[str] = Field(None, description="可选：导入后素材名称")

