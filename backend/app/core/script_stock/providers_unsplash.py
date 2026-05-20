"""Unsplash 图片搜索与下载（仅存图片，成片时静帧）。"""
from __future__ import annotations

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
    ScriptStockUnsplashCacheItem,
    ScriptStockUnsplashCacheResponse,
    ScriptStockUnsplashClearCacheResponse,
    ScriptStockUnsplashDownloadRequest,
    ScriptStockUnsplashDownloadResponse,
    ScriptStockUnsplashSearchResponse,
    UnsplashPhotoSummary,
)
from app.utils.paths import storage_public_url_for_file, to_stored_path

logger = logging.getLogger(__name__)

UNSPLASH_API = "https://api.unsplash.com"
_PROVIDER = "unsplash"


def _headers(access_key: str) -> dict[str, str]:
    return {"Accept-Version": "v1", "Authorization": f"Client-ID {access_key}"}


def _map_photo(p: dict) -> UnsplashPhotoSummary:
    urls = p.get("urls") if isinstance(p.get("urls"), dict) else {}
    user = p.get("user") if isinstance(p.get("user"), dict) else {}
    desc = (p.get("description") or p.get("alt_description") or "").strip()
    thumb = str(urls.get("small") or urls.get("regular") or urls.get("thumb") or "")
    return UnsplashPhotoSummary(
        id=str(p.get("id") or ""),
        width=int(p.get("width") or 0),
        height=int(p.get("height") or 0),
        description=desc[:500],
        image=thumb,
        user_name=str(user.get("name") or user.get("username") or ""),
        color=str(p.get("color") or ""),
    )


async def search_unsplash(
    access_key: str,
    query: str,
    page: int,
    per_page: int,
    *,
    http_proxy: str | None = None,
) -> ScriptStockUnsplashSearchResponse:
    params = {"query": query, "page": page, "per_page": per_page}
    async with stock_async_client(timeout=30.0, headers=_headers(access_key), proxy=http_proxy) as client:
        resp = await client.get(f"{UNSPLASH_API}/search/photos", params=params)
    if resp.status_code != 200:
        raise httpx.HTTPStatusError("unsplash search failed", request=resp.request, response=resp)
    data = resp.json()
    photos = [_map_photo(p) for p in (data.get("results") or []) if isinstance(p, dict)]
    return ScriptStockUnsplashSearchResponse(
        page=page,
        per_page=per_page,
        total_results=int(data.get("total") or 0),
        photos=photos,
    )


async def download_unsplash(
    access_key: str,
    req: ScriptStockUnsplashDownloadRequest,
    *,
    http_proxy: str | None = None,
) -> ScriptStockUnsplashDownloadResponse:
    pid = (req.unsplash_photo_id or "").strip()
    if not pid:
        raise ValueError("unsplash_photo_id 无效")

    async with stock_async_client(timeout=45.0, headers=_headers(access_key), proxy=http_proxy) as client:
        photo_resp = await client.get(f"{UNSPLASH_API}/photos/{pid}")
        if photo_resp.status_code != 200:
            raise ValueError("未找到该 Unsplash 照片")
        photo_raw = photo_resp.json()
        photo = photo_raw if isinstance(photo_raw, dict) else {}
        summary = _map_photo(photo)

        dl_resp = await client.get(f"{UNSPLASH_API}/photos/{pid}/download")
        if dl_resp.status_code != 200:
            raise ValueError("Unsplash 下载追踪失败")
        dl_raw = dl_resp.json()
        dl_data = dl_raw if isinstance(dl_raw, dict) else {}
        img_url = (dl_data.get("url") or "").strip()
        if not img_url:
            urls = photo.get("urls") if isinstance(photo.get("urls"), dict) else {}
            img_url = str(urls.get("regular") or urls.get("full") or "").strip()
        if not img_url:
            raise ValueError("未获取到图片下载地址")

    dest_dir = stock_download_root(_PROVIDER)
    safe_id = "".join(c if c.isalnum() or c in "_-" else "_" for c in pid)[:64]
    ext = ext_from_url(img_url, ".jpg")
    fname = f"unsplash_{safe_id}{ext}"
    dest_abs = os.path.join(dest_dir, fname)

    async with stock_async_client(timeout=600.0, follow_redirects=True, proxy=http_proxy) as client:
        media = await client.get(img_url)
    if media.status_code != 200:
        raise ValueError("下载图片失败")
    with open(dest_abs, "wb") as f:
        f.write(media.content)

    rel = to_stored_path(dest_abs)
    try:
        meta = read_stock_meta(dest_dir)
        sq = (req.search_query or "").strip()[:500]
        meta[rel] = {
            "search_query": sq,
            "preview_image": (summary.image or "").strip()[:2000],
            "duration_sec": 0,
            "media_type": "image",
            "unsplash_photo_id": pid,
        }
        write_stock_meta(dest_dir, meta)
    except Exception as e:
        logger.warning("unsplash meta write skipped: %s", e)

    return ScriptStockUnsplashDownloadResponse(
        stored_rel_path=rel,
        public_url=storage_public_url_for_file(dest_abs),
        filename=os.path.basename(dest_abs),
    )


def list_unsplash_cache() -> ScriptStockUnsplashCacheResponse:
    root = stock_download_root(_PROVIDER)
    meta = read_stock_meta(root)
    items: List[ScriptStockUnsplashCacheItem] = []
    for rel, name, sz, mt in list_cached_media_files(_PROVIDER):
        mid = parse_media_id_from_filename(_PROVIDER, name)
        row = meta.get(rel) if isinstance(meta.get(rel), dict) else {}
        if not isinstance(row, dict):
            row = {}
        pid = str(row.get("unsplash_photo_id") or mid or "")[:80]
        items.append(
            ScriptStockUnsplashCacheItem(
                unsplash_photo_id=pid,
                media_type="image",
                stored_rel_path=rel,
                filename=name,
                size_bytes=sz,
                mtime=mt,
                search_query=str(row.get("search_query") or "")[:500],
                preview_image=str(row.get("preview_image") or "")[:2000],
                duration_sec=0,
            )
        )
    items.sort(key=lambda x: -x.mtime)
    return ScriptStockUnsplashCacheResponse(items=items)


def clear_unsplash_cache() -> ScriptStockUnsplashClearCacheResponse:
    from app.core.script_stock.stock_media import is_under_stock_download_dir

    root = stock_download_root(_PROVIDER)
    deleted = 0
    if not os.path.isdir(root):
        return ScriptStockUnsplashClearCacheResponse(ok=True, deleted_files=0)
    for _, name, _, _ in list_cached_media_files(_PROVIDER):
        full = os.path.join(root, name)
        if not is_under_stock_download_dir(full, _PROVIDER):
            continue
        try:
            os.unlink(full)
            deleted += 1
        except OSError as e:
            logger.warning("unsplash clear unlink %s: %s", full, e)
    mp = os.path.join(root, "stock_cache_meta.json")
    try:
        if os.path.isfile(mp):
            os.unlink(mp)
    except OSError as e:
        logger.warning("unsplash clear meta: %s", e)
    return ScriptStockUnsplashClearCacheResponse(ok=True, deleted_files=deleted)


def delete_unsplash_meta_entry(rel: str) -> None:
    root = stock_download_root(_PROVIDER)
    meta = read_stock_meta(root)
    if rel in meta:
        del meta[rel]
        write_stock_meta(root, meta)
