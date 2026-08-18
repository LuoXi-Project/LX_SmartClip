"""YouTube 关键词搜索：yt-dlp 原生 ytsearch（extract_flat，不逐条抓详情页）。

搜索与下载都走 yt-dlp Python API；国内访问需要代理时由 config 的
external_search_proxy 提供（传给 yt-dlp 的 proxy 选项）。
"""
from __future__ import annotations

import asyncio
import logging
import os

from app.core.blocking_pool import run_in_blocking_executor

from .types import PLATFORM_YOUTUBE, ExternalSearchResult, YoutubeSearchError

logger = logging.getLogger(__name__)

# 单次搜索的硬上限，防止误传超大 limit
_MAX_LIMIT = 30


def _build_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _search_youtube_sync(
    query: str,
    limit: int = 10,
    proxy: str | None = None,
    cookiefile: str | None = None,
) -> list[ExternalSearchResult]:
    query = (query or "").strip()
    if not query:
        raise YoutubeSearchError("搜索关键词为空")
    limit = max(1, min(int(limit or 10), _MAX_LIMIT))

    try:
        import yt_dlp
    except Exception as exc:
        raise YoutubeSearchError("未安装 yt-dlp，无法搜索 YouTube") from exc

    ydl_opts: dict = {
        # 完全扁平模式：只取搜索列表页内联字段（id/title/duration/view_count），
        # 不逐条访问视频页 —— 既快，又能绕开被标记 IP 的「Sign in to confirm」验证
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "socket_timeout": 30,
    }
    if proxy:
        ydl_opts["proxy"] = proxy
    if cookiefile and os.path.isfile(cookiefile):
        ydl_opts["cookiefile"] = cookiefile

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    except Exception as exc:
        raise YoutubeSearchError(f"YouTube 搜索失败：{str(exc).strip()[-500:]}") from exc

    entries = (info or {}).get("entries") or []
    results: list[ExternalSearchResult] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        video_id = str(e.get("id") or "").strip()
        if not video_id:
            continue
        duration = e.get("duration")
        try:
            duration_sec = float(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration_sec = None
        try:
            view_count = int(e.get("view_count") or 0) or None
        except (TypeError, ValueError):
            view_count = None
        results.append(
            ExternalSearchResult(
                platform=PLATFORM_YOUTUBE,
                video_id=video_id,
                title=str(e.get("title") or "")[:200],
                author=str(e.get("uploader") or e.get("channel") or "")[:120],
                duration_sec=duration_sec,
                url=_build_watch_url(video_id),
                view_count=view_count,
                keyword=query,
            )
        )
    return results


async def search_youtube(
    query: str,
    limit: int = 10,
    proxy: str | None = None,
    cookiefile: str | None = None,
) -> list[ExternalSearchResult]:
    """异步包装：yt-dlp 为阻塞调用，放 IO 线程池执行。"""
    try:
        return await asyncio.wait_for(
            run_in_blocking_executor(_search_youtube_sync, query, limit, proxy, cookiefile),
            timeout=120,
        )
    except asyncio.TimeoutError as exc:
        raise YoutubeSearchError("YouTube 搜索超时（120s），请检查网络或代理配置") from exc
