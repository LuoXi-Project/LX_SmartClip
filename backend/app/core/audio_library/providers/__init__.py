"""音频库音乐源 provider 包。

provider 不在 import 时自动注册单例（区别于 SmartMixroll），
而是由 worker 按账号实例化，因为网易云 cookie 随账号变化。

对外提供工厂函数 get_provider_instance(source, account)。
"""
from __future__ import annotations

from typing import Optional

from app.core.audio_library.providers.base import (
    DownloadResult,
    MusicProvider,
    SongMeta,
)


def get_provider_instance(source: str, account: str = "main") -> Optional[MusicProvider]:
    """按 source + account 实例化 provider。延迟 import 避免循环依赖。"""
    if source == "netease":
        from app.core.audio_library.providers.netease import NeteaseProvider
        return NeteaseProvider(account=account)
    if source == "kuwo":
        from app.core.audio_library.providers.kuwo import KuwoProvider
        return KuwoProvider(account=account)
    return None


__all__ = [
    "DownloadResult",
    "MusicProvider",
    "SongMeta",
    "get_provider_instance",
]
