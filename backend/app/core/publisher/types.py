"""发布模块的数据契约。

这里用 dataclass + dict 而非 pydantic，因为 worker 子进程会 import 本模块，
不应依赖 FastAPI/pydantic（保持子进程轻量、启动快）。
API 层（api/publish.py）会有对应的 pydantic schema 做请求校验。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal

# ── 平台枚举 ──────────────────────────────────────────────────────────────
# 阶段 1 仅实现 douyin；其余平台预留，前端可按 PLATFORMS 渲染但禁用未实现的。
Platform = Literal["douyin", "xhs", "wxchannels", "bilibili", "kuaishou", "tiktok", "youtube"]

# 平台元信息：label 中文名 + implemented 是否已内联实现
PLATFORM_META: dict[str, dict[str, Any]] = {
    "douyin": {"label": "抖音", "implemented": True, "risk": "normal"},
    "xhs": {"label": "小红书", "implemented": False, "risk": "strict"},  # 风控最严
    "wxchannels": {"label": "视频号", "implemented": False, "risk": "normal"},
    "bilibili": {"label": "哔哩哔哩", "implemented": False, "risk": "low"},
    "kuaishou": {"label": "快手", "implemented": False, "risk": "normal"},
    "tiktok": {"label": "TikTok", "implemented": False, "risk": "normal"},
    "youtube": {"label": "YouTube", "implemented": False, "risk": "low"},
}

PLATFORMS = list(PLATFORM_META.keys())
IMPLEMENTED_PLATFORMS = [k for k, v in PLATFORM_META.items() if v["implemented"]]


def is_supported_platform(p: str) -> bool:
    return p in PLATFORM_META


def is_implemented_platform(p: str) -> bool:
    return PLATFORM_META.get(p, {}).get("implemented", False)


# ── 发布请求项（单平台一条） ──────────────────────────────────────────────
@dataclass
class PublishItem:
    """单个平台的发布请求。"""
    platform: str
    account: str = "main"               # 账号标识，支持多账号矩阵
    title: str = ""                     # 视频标题
    description: str = ""               # 视频描述/正文
    tags: list[str] = field(default_factory=list)  # 话题标签
    cover_path: str | None = None       # 封面图（绝对路径），可选
    publish_strategy: str = "immediate"  # immediate | scheduled
    publish_date: str | None = None     # ISO 格式，仅 scheduled 生效
    extra: dict[str, Any] = field(default_factory=dict)  # 平台特有字段扩展位

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PublishItem":
        return cls(
            platform=d["platform"],
            account=d.get("account", "main"),
            title=d.get("title", ""),
            description=d.get("description", ""),
            tags=list(d.get("tags", []) or []),
            cover_path=d.get("cover_path"),
            publish_strategy=d.get("publish_strategy", "immediate"),
            publish_date=d.get("publish_date"),
            extra=dict(d.get("extra", {}) or {}),
        )


# ── 子进程任务载荷（task.json 的结构） ────────────────────────────────────
@dataclass
class PublishTaskPayload:
    """写入 task.json 的完整任务描述，由 worker 子进程读取。"""
    task_id: str
    video_path: str                     # 视频文件绝对路径
    items: list[PublishItem]            # 要发布的平台列表
    home_dir: str                       # LX_SMARTCLIP_HOME 绝对路径（子进程据此定位 cookie 目录）

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "video_path": self.video_path,
            "home_dir": self.home_dir,
            "items": [it.to_dict() for it in self.items],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PublishTaskPayload":
        return cls(
            task_id=d["task_id"],
            video_path=d["video_path"],
            home_dir=d["home_dir"],
            items=[PublishItem.from_dict(it) for it in d.get("items", [])],
        )


# ── 单平台执行结果 ────────────────────────────────────────────────────────
@dataclass
class TaskItemResult:
    """单个平台发布的结果。"""
    platform: str
    account: str = "main"
    status: str = "pending"             # success | failed | skipped
    message: str = ""                   # 人类可读的结果说明
    url: str | None = None              # 发布后的作品链接（若能拿到）
    screenshot_path: str | None = None  # 失败时的截图路径
    duration_sec: float = 0.0           # 该平台耗时

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── 整体任务结果（result.json 的结构） ────────────────────────────────────
@dataclass
class PublishResult:
    """整个发布任务的聚合结果，由 worker 写入 result.json。"""
    task_id: str
    status: str = "pending"             # succeeded | failed | partial | cancelled
    items: list[TaskItemResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "items": [it.to_dict() for it in self.items],
        }
