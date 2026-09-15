"""Coverr 视频搜索与下载（文案成片；仅视频，无图片）。

API 文档：https://api.coverr.co/docs/videos/
认证：Authorization: Bearer {api_key}（或 api_key 查询参数）。
注意：/videos 的 page 从 0 开始，对外仍沿用项目内 1 起始页码，内部转换。
"""
from __future__ import annotations

import logging
import os
from typing import List

import httpx

from app.core.script_stock.stock_media import (
    list_cached_media_files,
    media_type_from_path,
    parse_media_id_from_filename,
    read_stock_meta,
    stock_async_client,
    stock_download_root,
    write_stock_meta,
)
from app.models.script_stock import (
    CoverrVideoSummary,
    ScriptStockCoverrCacheItem,
    ScriptStockCoverrCacheResponse,
    ScriptStockCoverrClearCacheResponse,
    ScriptStockCoverrDownloadRequest,
    ScriptStockCoverrDownloadResponse,
    ScriptStockCoverrSearchResponse,
)
from app.utils.paths import storage_public_url_for_file, to_stored_path

logger = logging.getLogger(__name__)

COVERR_API = "https://api.coverr.co"
_PROVIDER = "coverr"


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _to_float(v: object) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _map_video(v: dict) -> CoverrVideoSummary:
    tags = v.get("tags")
    if isinstance(tags, (list, tuple)):
        tag_str = ",".join(str(t) for t in tags if t)
    else:
        tag_str = str(tags or "")
    return CoverrVideoSummary(
        id=str(v.get("id") or v.get("video_id") or ""),
        title=str(v.get("title") or "")[:300],
        description=str(v.get("description") or "")[:1000],
        width=int(v.get("max_width") or 0),
        height=int(v.get("max_height") or 0),
        duration=_to_float(v.get("duration")),
        image=str(v.get("thumbnail") or v.get("poster") or ""),
        aspect_ratio=str(v.get("aspect_ratio") or ""),
        is_vertical=bool(v.get("is_vertical")),
        tags=tag_str[:500],
    )


async def search_coverr(
    api_key: str,
    query: str,
    page: int,
    per_page: int,
    *,
    http_proxy: str | None = None,
) -> ScriptStockCoverrSearchResponse:
    """page 为 1 起始（项目内约定），内部转换为 Coverr 的 0 起始页码。"""
    params = {
        "query": query,
        "page": max(0, int(page) - 1),
        "page_size": max(1, min(30, int(per_page))),
        "sort": "popular",
        "urls": "true",
    }
    async with stock_async_client(timeout=30.0, headers=_headers(api_key), proxy=http_proxy) as client:
        resp = await client.get(f"{COVERR_API}/videos", params=params)
    if resp.status_code != 200:
        raise httpx.HTTPStatusError("coverr search failed", request=resp.request, response=resp)
    data = resp.json()
    videos = [_map_video(v) for v in (data.get("hits") or []) if isinstance(v, dict)]
    return ScriptStockCoverrSearchResponse(
        page=page,
        per_page=int(params["page_size"]),
        total_results=int(data.get("total") or 0),
        total_pages=int(data.get("pages") or 0),
        videos=videos,
    )


async def _report_download(client: httpx.AsyncClient, media_id: str) -> None:
    """官方要求下载后上报统计；尽力而为，失败仅记日志。"""
    try:
        await client.patch(f"{COVERR_API}/videos/{media_id}/stats/downloads")
    except Exception as e:
        logger.debug("coverr download stats report skipped: %s", e)


async def download_coverr(
    api_key: str,
    req: ScriptStockCoverrDownloadRequest,
    *,
    http_proxy: str | None = None,
) -> ScriptStockCoverrDownloadResponse:
    mid = (req.coverr_media_id or "").strip()
    if not mid:
        raise ValueError("coverr_media_id 无效")

    async with stock_async_client(timeout=45.0, headers=_headers(api_key), proxy=http_proxy) as client:
        resp = await client.get(f"{COVERR_API}/videos/{mid}")
        if resp.status_code != 200:
            raise httpx.HTTPStatusError("coverr fetch failed", request=resp.request, response=resp)
        raw = resp.json()
        data = raw if isinstance(raw, dict) else {}
        summary = _map_video(data)
        if not summary.id:
            summary.id = mid
        urls = data.get("urls") if isinstance(data.get("urls"), dict) else {}
        url = str(urls.get("mp4_download") or urls.get("mp4") or "").strip()
        if not url:
            raise ValueError("未找到可下载的视频文件")

    dest_dir = stock_download_root(_PROVIDER)
    safe_id = "".join(c if c.isalnum() or c in "_-" else "_" for c in mid)[:64]
    fname = f"coverr_{safe_id}_{summary.width}x{summary.height}.mp4"
    dest_abs = os.path.join(dest_dir, fname)

    async with stock_async_client(timeout=600.0, follow_redirects=True, proxy=http_proxy) as client:
        media = await client.get(url)
        if media.status_code != 200:
            raise ValueError("下载视频失败")
        with open(dest_abs, "wb") as f:
            f.write(media.content)
        await _report_download(client, mid)

    rel = to_stored_path(dest_abs)
    try:
        meta = read_stock_meta(dest_dir)
        sq = (req.search_query or "").strip()[:500]
        meta[rel] = {
            "search_query": sq,
            "preview_image": (summary.image or "").strip()[:2000],
            "duration_sec": round(summary.duration or 0.0, 3),
            "media_type": "video",
            "coverr_video_id": mid,
        }
        write_stock_meta(dest_dir, meta)
    except Exception as e:
        logger.warning("coverr meta write skipped: %s", e)

    return ScriptStockCoverrDownloadResponse(
        stored_rel_path=rel,
        public_url=storage_public_url_for_file(dest_abs),
        filename=os.path.basename(dest_abs),
    )


def list_coverr_cache() -> ScriptStockCoverrCacheResponse:
    root = stock_download_root(_PROVIDER)
    meta = read_stock_meta(root)
    items: List[ScriptStockCoverrCacheItem] = []
    for rel, name, sz, mt in list_cached_media_files(_PROVIDER):
        mid = parse_media_id_from_filename(_PROVIDER, name)
        row = meta.get(rel) if isinstance(meta.get(rel), dict) else {}
        if not isinstance(row, dict):
            row = {}
        vid = str(row.get("coverr_video_id") or mid or "")[:64]
        try:
            dsec = float(row.get("duration_sec") or 0)
        except (TypeError, ValueError):
            dsec = 0.0
        items.append(
            ScriptStockCoverrCacheItem(
                coverr_video_id=vid,
                media_type="video" if media_type_from_path(name) == "video" else "image",
                stored_rel_path=rel,
                filename=name,
                size_bytes=sz,
                mtime=mt,
                search_query=str(row.get("search_query") or "")[:500],
                preview_image=str(row.get("preview_image") or "")[:2000],
                duration_sec=dsec,
            )
        )
    items.sort(key=lambda x: -x.mtime)
    return ScriptStockCoverrCacheResponse(items=items)


def clear_coverr_cache() -> ScriptStockCoverrClearCacheResponse:
    from app.core.script_stock.stock_media import is_under_stock_download_dir

    root = stock_download_root(_PROVIDER)
    deleted = 0
    if not os.path.isdir(root):
        return ScriptStockCoverrClearCacheResponse(ok=True, deleted_files=0)
    for _, name, _, _ in list_cached_media_files(_PROVIDER):
        full = os.path.join(root, name)
        if not is_under_stock_download_dir(full, _PROVIDER):
            continue
        try:
            os.unlink(full)
            deleted += 1
        except OSError as e:
            logger.warning("coverr clear unlink %s: %s", full, e)
    mp = os.path.join(root, "stock_cache_meta.json")
    try:
        if os.path.isfile(mp):
            os.unlink(mp)
    except OSError as e:
        logger.warning("coverr clear meta: %s", e)
    return ScriptStockCoverrClearCacheResponse(ok=True, deleted_files=deleted)


def delete_coverr_meta_entry(rel: str) -> None:
    root = stock_download_root(_PROVIDER)
    meta = read_stock_meta(root)
    if rel in meta:
        del meta[rel]
        write_stock_meta(root, meta)
