"""音频库模块的数据契约（仿 publisher/types.py，用 dataclass 不依赖 pydantic）。

被 worker 子进程 import，故保持轻量。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal

# 支持的音乐源
AudioSource = Literal["netease", "kuwo"]

# 音乐源元信息：label 中文名 + needs_login 是否需要登录
SOURCE_META: dict[str, dict[str, Any]] = {
    "netease": {"label": "网易云音乐", "needs_login": True},
    "kuwo": {"label": "酷我音乐", "needs_login": False},
}

SOURCES = list(SOURCE_META.keys())


def needs_login(source: str) -> bool:
    return SOURCE_META.get(source, {}).get("needs_login", False)


def source_label(source: str) -> str:
    return SOURCE_META.get(source, {}).get("label", source)


# ── 子进程任务载荷（task.json 的结构） ────────────────────────────────────
@dataclass
class AudioTaskPayload:
    """写入 task.json 的完整任务描述，由 worker 子进程读取。

    job_type:
      - "search"：搜索歌曲（不下载），结果写 result.json
      - "download"：批量下载勾选歌曲到 BGM 库
    """
    task_id: str
    job_type: str                        # "search" | "download"
    source: str                          # "netease" | "kuwo"
    account: str = "main"
    keyword: str = ""                    # search 用
    limit: int = 20                      # search 用
    songs: list[dict] = field(default_factory=list)  # download 用：SongMeta 序列化列表
    home_dir: str = ""                   # LX_SMARTCLIP_HOME 绝对路径

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "job_type": self.job_type,
            "source": self.source,
            "account": self.account,
            "keyword": self.keyword,
            "limit": self.limit,
            "songs": list(self.songs),
            "home_dir": self.home_dir,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AudioTaskPayload":
        return cls(
            task_id=d["task_id"],
            job_type=d["job_type"],
            source=d["source"],
            account=d.get("account", "main"),
            keyword=d.get("keyword", ""),
            limit=int(d.get("limit", 20)),
            songs=list(d.get("songs", []) or []),
            home_dir=d.get("home_dir", ""),
        )


# ── 整体任务结果（result.json 的结构） ────────────────────────────────────
@dataclass
class AudioTaskResult:
    """整个音频任务的聚合结果，由 worker 写入 result.json。"""
    task_id: str
    status: str = "pending"              # succeeded | failed | partial | cancelled
    # search 结果（job_type=search 时）
    songs: list[dict] = field(default_factory=list)
    # download 汇总（job_type=download 时）
    downloaded: int = 0
    failed: int = 0
    skipped: int = 0
    detail: list[dict] = field(default_factory=list)  # 每首歌结果

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
