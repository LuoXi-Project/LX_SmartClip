"""发布模块的 pydantic 请求/响应 schema（仿 models/replica.py 范式）。

这些是 API 层校验用；worker 子进程用的是 publisher/types.py 的 dataclass（不依赖 pydantic）。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PlatformName = Literal["douyin", "xhs", "wxchannels", "bilibili", "kuaishou", "tiktok", "youtube"]


class PublishItemRequest(BaseModel):
    """单平台发布请求项。"""
    platform: PlatformName
    account: str = Field(default="main", description="账号标识，支持多账号")
    title: str = Field(default="", max_length=200, description="视频标题")
    description: str = Field(default="", description="视频描述/正文")
    tags: list[str] = Field(default_factory=list, description="话题标签")
    cover_path: str | None = Field(default=None, description="封面图绝对路径")
    publish_strategy: Literal["immediate", "scheduled"] = Field(default="immediate")
    publish_date: str | None = Field(default=None, description="ISO 时间，仅 scheduled 生效")


class CreatePublishTaskRequest(BaseModel):
    """创建发布任务请求。"""
    video_path: str = Field(..., description="视频文件绝对路径（须为 storage 内文件）")
    items: list[PublishItemRequest] = Field(..., min_length=1, description="目标平台列表")
    # 是否无头模式（true=后台无界面；false=显示浏览器窗口，便于排查/手动兜底）
    headless: bool = Field(default=True, description="无头模式开关")


class LoginRequest(BaseModel):
    """触发扫码登录请求。"""
    account: str = Field(default="main")


class CheckLoginRequest(BaseModel):
    """校验登录态请求。"""
    account: str = Field(default="main")


class UpdateAccountRequest(BaseModel):
    """更新账号信息（用户编辑）。

    display_name：账号的自定义显示名称（备注/别名），便于多账号区分。
    传空串 → 清除自定义名，回退到自动命名。
    """
    display_name: str = Field(default="", max_length=40, description="自定义显示名称，空串清除")


class PublishTaskResponse(BaseModel):
    """任务详情响应。"""
    id: str
    video_path: str
    video_name: str | None = None
    status: str
    pid: int | None = None
    items_json: str = "[]"
    progress_json: str | None = None
    result_json: str | None = None
    log: str = ""
    created_at: str
    updated_at: str


class PublishStatusResponse(BaseModel):
    """功能就绪状态响应。"""
    ready: bool
    browser: dict[str, Any]
    platforms: list[dict[str, Any]]


class AccountInfo(BaseModel):
    """账号信息。"""
    platform: str
    account: str
    display_name: str | None = None
    login_status: str
    last_login_at: str | None = None
    last_used_at: str | None = None
    last_error: str | None = None
