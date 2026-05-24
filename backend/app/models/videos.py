from typing import Literal, Optional

from pydantic import BaseModel, Field


class RenamePayload(BaseModel):
    name: str


class UpdateVideoPayload(BaseModel):
    name: Optional[str] = None
    status: Optional[Literal["pending", "processing", "done", "error"]] = None


class ImportVideoByUrlPayload(BaseModel):
    url: str = Field(..., min_length=5, description="视频链接（抖音分享链接或其它 yt-dlp 支持的站点）")
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


class ReencodeVideoPayload(BaseModel):
    vcodec: Literal["libx264", "libx265"] = Field("libx264", description="视频编码器")
    crf: int = Field(23, ge=18, le=35, description="恒定质量参数，越小越清晰")
    preset: Literal["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"] = Field(
        "medium",
        description="编码预设",
    )
    fps: Optional[int] = Field(None, ge=24, le=60, description="可选：输出 FPS")
    max_height: Optional[int] = Field(None, ge=360, le=2160, description="可选：输出最大高度")
    acodec: Literal["aac"] = Field("aac", description="音频编码器")
    audio_bitrate_k: int = Field(128, ge=64, le=320, description="音频码率（kbps）")

