"""音频库模块的 pydantic 请求/响应 schema（仿 models/publish.py）。

API 层校验用；worker 子进程用 core/audio_library/types.py 的 dataclass。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AudioSourceName = Literal["netease", "kuwo"]


class LoginRequest(BaseModel):
    """触发扫码登录请求（仅 netease）。"""
    account: str = Field(default="main")


class CheckLoginRequest(BaseModel):
    account: str = Field(default="main")


class UpdateAccountRequest(BaseModel):
    """更新账号自定义显示名称。空串清除。"""
    display_name: str = Field(default="", max_length=40)


class SearchPreviewRequest(BaseModel):
    """搜索预览请求（不下载）。"""
    source: AudioSourceName
    keyword: str = Field(..., min_length=1, max_length=100)
    limit: int = Field(default=20, ge=1, le=50)
    account: str = Field(default="main")


class DownloadBatchRequest(BaseModel):
    """批量下载勾选歌曲到 BGM 库。"""
    source: AudioSourceName
    account: str = Field(default="main")
    songs: list[dict] = Field(..., min_length=1, description="勾选的歌曲 SongMeta 列表")


class AudioTaskResponse(BaseModel):
    id: str
    job_type: str
    source: str
    account: str | None = None
    status: str
    pid: int | None = None
    payload_json: str = "{}"
    progress_json: str | None = None
    result_json: str | None = None
    log: str = ""
    created_at: str
    updated_at: str


class AccountInfo(BaseModel):
    source: str
    account: str
    display_name: str | None = None
    login_status: str
    last_login_at: str | None = None
    last_used_at: str | None = None
    last_error: str | None = None


class AudioLibraryStatusResponse(BaseModel):
    ready: bool
    browser: dict[str, Any]
    sources: list[dict[str, Any]]
