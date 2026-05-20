"""Pixabay 视频/图片搜索与下载（文案成片；图片仅存本地，成片时静帧）。"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import List

import httpx

from app.core.script_stock.stock_media import (
    ext_from_url,
    list_cached_media_files,
    media_type_from_path,
    parse_media_id_from_filename,
    read_stock_meta,
    stock_async_client,
    stock_download_root,
    write_stock_meta,
)
from app.models.script_stock import (
    PixabayImageSummary,
    PixabayVideoRendition,
    PixabayVideoSummary,
    ScriptStockPixabayCacheItem,
    ScriptStockPixabayCacheResponse,
    ScriptStockPixabayClearCacheResponse,
    ScriptStockPixabayDownloadRequest,
    ScriptStockPixabayDownloadResponse,
    ScriptStockPixabaySearchResponse,
)
from app.utils.paths import storage_public_url_for_file, to_stored_path

logger = logging.getLogger(__name__)

PIXABAY_VIDEO_URL = "https://pixabay.com/api/videos/"
PIXABAY_IMAGE_URL = "https://pixabay.com/api/"
_PROVIDER = "pixabay"

_IMAGE_SIZE_KEYS = ("largeImageURL", "fullHDURL", "webformatURL", "previewURL")


def _map_pixabay_video(v: dict) -> PixabayVideoSummary:
    videos_raw = v.get("videos") if isinstance(v.get("videos"), dict) else {}
    renditions: dict[str, PixabayVideoRendition] = {}
    w, h = 0, 0
    for key, val in videos_raw.items():
        if not isinstance(val, dict):
            continue
        url = (val.get("url") or "").strip()
        if not url:
            continue
        rw, rh = int(val.get("width") or 0), int(val.get("height") or 0)
        renditions[key] = PixabayVideoRendition(
            url=url,
            width=rw,
            height=rh,
            size=int(val.get("size") or 0),
            thumbnail=str(val.get("thumbnail") or ""),
        )
        if key in ("large", "medium") and rw and rh:
            w, h = rw, rh
    thumb = str(v.get("picture") or v.get("userImageURL") or "")
    if not thumb:
        med = renditions.get("medium") or renditions.get("large")
        if med:
            thumb = med.thumbnail or thumb
    return PixabayVideoSummary(
        id=int(v.get("id") or 0),
        width=w,
        height=h,
        duration=int(v.get("duration") or 0),
        image=thumb,
        user_name=str(v.get("user") or ""),
        tags=str(v.get("tags") or ""),
        videos=renditions,
    )


def _map_pixabay_image(v: dict) -> PixabayImageSummary:
    thumb = ""
    for k in _IMAGE_SIZE_KEYS:
        u = str(v.get(k) or "").strip()
        if u:
            thumb = u
            break
    return PixabayImageSummary(
        id=int(v.get("id") or 0),
        width=int(v.get("imageWidth") or 0),
        height=int(v.get("imageHeight") or 0),
        image=thumb,
        user_name=str(v.get("user") or ""),
        tags=str(v.get("tags") or ""),
    )


def _pick_pixabay_url(videos: dict[str, PixabayVideoRendition], preferred: str) -> PixabayVideoRendition | None:
    if not videos:
        return None
    pref = (preferred or "medium").lower()
    for q in (pref, "large", "medium", "small", "tiny"):
        r = videos.get(q)
        if r and r.url.lower().endswith((".mp4", ".mov", ".webm")):
            return r
    for r in videos.values():
        if r.url.lower().endswith((".mp4", ".mov", ".webm")):
            return r
    return next(iter(videos.values()), None)


def _pick_pixabay_image_url(hit: dict, preferred: str) -> str:
    pref = (preferred or "large").lower()
    if pref == "large":
        order = ("largeImageURL", "fullHDURL", "webformatURL", "previewURL")
    elif pref in ("medium", "small", "tiny"):
        order = ("webformatURL", "largeImageURL", "previewURL")
    else:
        order = _IMAGE_SIZE_KEYS
    for k in order:
        u = str(hit.get(k) or "").strip()
        if u:
            return u
    return ""


async def search_pixabay(
    api_key: str,
    query: str,
    page: int,
    per_page: int,
    *,
    http_proxy: str | None = None,
) -> ScriptStockPixabaySearchResponse:
    half = max(1, per_page // 2)
    vparams = {
        "key": api_key,
        "q": query,
        "page": page,
        "per_page": half,
        "safesearch": "true",
        "order": "popular",
    }
    iparams = {**vparams, "per_page": per_page - half}
    async with stock_async_client(timeout=30.0, proxy=http_proxy) as client:
        vresp, iresp = await asyncio.gather(
            client.get(PIXABAY_VIDEO_URL, params=vparams),
            client.get(PIXABAY_IMAGE_URL, params=iparams),
        )
    if vresp.status_code != 200:
        raise httpx.HTTPStatusError("pixabay video search failed", request=vresp.request, response=vresp)
    if iresp.status_code != 200:
        raise httpx.HTTPStatusError("pixabay image search failed", request=iresp.request, response=iresp)
    vdata = vresp.json()
    idata = iresp.json()
    videos = [_map_pixabay_video(v) for v in (vdata.get("hits") or []) if isinstance(v, dict)]
    images = [_map_pixabay_image(v) for v in (idata.get("hits") or []) if isinstance(v, dict)]
    total = int(vdata.get("totalHits") or 0) + int(idata.get("totalHits") or 0)
    return ScriptStockPixabaySearchResponse(
        page=int(vdata.get("page") or page),
        per_page=per_page,
        total_results=total,
        videos=videos,
        images=images,
    )


async def download_pixabay(
    api_key: str,
    req: ScriptStockPixabayDownloadRequest,
    *,
    http_proxy: str | None = None,
) -> ScriptStockPixabayDownloadResponse:
    mid = int(req.pixabay_media_id)
    if mid <= 0:
        raise ValueError("pixabay_media_id 无效")
    media_type = (req.media_type or "video").lower()

    params = {"key": api_key, "id": str(mid)}
    base_url = PIXABAY_IMAGE_URL if media_type == "image" else PIXABAY_VIDEO_URL
    async with stock_async_client(timeout=45.0, proxy=http_proxy) as client:
        resp = await client.get(base_url, params=params)
    if resp.status_code != 200:
        raise httpx.HTTPStatusError("pixabay fetch failed", request=resp.request, response=resp)
    data = resp.json()
    hits = data.get("hits") or []
    if not hits or not isinstance(hits[0], dict):
        raise ValueError("未找到该 Pixabay 素材")
    hit = hits[0]

    dest_dir = stock_download_root(_PROVIDER)
    preview = ""
    duration_sec = 0

    if media_type == "image":
        summary = _map_pixabay_image(hit)
        url = _pick_pixabay_image_url(hit, req.preferred_quality)
        if not url:
            raise ValueError("未找到可下载的图片")
        preview = summary.image
        ext = ext_from_url(url, ".jpg")
        fname = f"pixabay_img_{mid}{ext}"
    else:
        summary = _map_pixabay_video(hit)
        picked = _pick_pixabay_url(summary.videos, req.preferred_quality)
        if not picked:
            raise ValueError("未找到可下载的视频文件")
        preview = summary.image
        duration_sec = int(summary.duration or 0)
        url = picked.url
        fname = f"pixabay_{mid}_{req.preferred_quality}_{picked.width}x{picked.height}.mp4"

    dest_abs = os.path.join(dest_dir, fname)
    async with stock_async_client(timeout=600.0, follow_redirects=True, proxy=http_proxy) as client:
        media = await client.get(url)
    if media.status_code != 200:
        raise ValueError("下载失败")
    with open(dest_abs, "wb") as f:
        f.write(media.content)

    rel = to_stored_path(dest_abs)
    try:
        meta = read_stock_meta(dest_dir)
        sq = (req.search_query or "").strip()[:500]
        meta[rel] = {
            "search_query": sq,
            "preview_image": (preview or "").strip()[:2000],
            "duration_sec": duration_sec,
            "media_type": media_type,
        }
        write_stock_meta(dest_dir, meta)
    except Exception as e:
        logger.warning("pixabay meta write skipped: %s", e)

    return ScriptStockPixabayDownloadResponse(
        stored_rel_path=rel,
        public_url=storage_public_url_for_file(dest_abs),
        filename=os.path.basename(dest_abs),
    )


def list_pixabay_cache() -> ScriptStockPixabayCacheResponse:
    root = stock_download_root(_PROVIDER)
    meta = read_stock_meta(root)
    items: List[ScriptStockPixabayCacheItem] = []
    for rel, name, sz, mt in list_cached_media_files(_PROVIDER):
        mid = parse_media_id_from_filename(_PROVIDER, name)
        try:
            vid = int(mid) if mid else 0
        except ValueError:
            vid = 0
        row = meta.get(rel) if isinstance(meta.get(rel), dict) else {}
        if not isinstance(row, dict):
            row = {}
        mt_row = str(row.get("media_type") or "").lower()
        if mt_row not in ("image", "video"):
            mt_row = media_type_from_path(name)
        items.append(
            ScriptStockPixabayCacheItem(
                pixabay_video_id=vid,
                media_type=mt_row,  # type: ignore[arg-type]
                stored_rel_path=rel,
                filename=name,
                size_bytes=sz,
                mtime=mt,
                search_query=str(row.get("search_query") or "")[:500],
                preview_image=str(row.get("preview_image") or "")[:2000],
                duration_sec=int(row.get("duration_sec") or 0),
            )
        )
    items.sort(key=lambda x: -x.mtime)
    return ScriptStockPixabayCacheResponse(items=items)


def clear_pixabay_cache() -> ScriptStockPixabayClearCacheResponse:
    from app.core.script_stock.stock_media import is_under_stock_download_dir

    root = stock_download_root(_PROVIDER)
    deleted = 0
    if not os.path.isdir(root):
        return ScriptStockPixabayClearCacheResponse(ok=True, deleted_files=0)
    for _, name, _, _ in list_cached_media_files(_PROVIDER):
        full = os.path.join(root, name)
        if not is_under_stock_download_dir(full, _PROVIDER):
            continue
        try:
            os.unlink(full)
            deleted += 1
        except OSError as e:
            logger.warning("pixabay clear unlink %s: %s", full, e)
    mp = os.path.join(root, "stock_cache_meta.json")
    try:
        if os.path.isfile(mp):
            os.unlink(mp)
    except OSError as e:
        logger.warning("pixabay clear meta: %s", e)
    return ScriptStockPixabayClearCacheResponse(ok=True, deleted_files=deleted)


def delete_pixabay_meta_entry(rel: str) -> None:
    root = stock_download_root(_PROVIDER)
    meta = read_stock_meta(root)
    if rel in meta:
        del meta[rel]
        write_stock_meta(root, meta)
