"""音乐源 Provider 统一接口。

从 LX_SmartMixroll 迁移而来，保持 SongMeta / DownloadResult / MusicProvider 契约不变，
仅调整 import 路径与注册表。各 provider 实现（netease/kuwo）见同目录。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


@dataclass
class SongMeta:
    """搜索/下载返回的歌曲元数据。"""
    source: str
    source_id: str
    title: str
    artist: Optional[str] = None
    album: Optional[str] = None
    duration: Optional[float] = None
    cover_url: Optional[str] = None
    heat: int = 0
    tags: list[str] = field(default_factory=list)


@dataclass
class DownloadResult:
    """下载一首歌的结果。"""
    meta: SongMeta
    audio_path: str                      # 下载到本地的音频路径
    lrc_path: Optional[str] = None       # 歌词文件（LRC/YRC）
    lrc_format: Optional[str] = None     # "lrc" / "yrc"
    success: bool = True
    error: Optional[str] = None


@runtime_checkable
class MusicProvider(Protocol):
    """音乐源统一接口。"""

    name: str

    async def search(self, keyword: str, limit: int = 20) -> list[SongMeta]:
        """搜索歌曲。"""
        ...

    async def download(self, meta: SongMeta, dest_dir: str) -> DownloadResult:
        """下载音频 + 歌词到本地。"""
        ...


# Provider 注册表
_REGISTRY: dict[str, MusicProvider] = {}


def register_provider(name: str, provider: MusicProvider) -> None:
    _REGISTRY[name] = provider


def get_provider(name: str) -> MusicProvider | None:
    return _REGISTRY.get(name)


def list_providers() -> list[str]:
    return list(_REGISTRY.keys())
