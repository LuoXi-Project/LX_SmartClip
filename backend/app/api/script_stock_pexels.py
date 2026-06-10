"""Pexels 搜索、下载与本地缓存管理。"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, List

import aiosqlite
import httpx
from fastapi import HTTPException

from app.core.script_stock.stock_media import (
    ext_from_url,
    is_under_pexels_download_dir,
    media_type_from_path,
    stock_async_client,
)
from app.db.database import DB_PATH
from app.models.script_stock import (
    PexelsImageSummary,
    PexelsVideoFile,
    PexelsVideoSummary,
    ScriptStockPexelsCacheItem,
    ScriptStockPexelsCacheResponse,
    ScriptStockPexelsClearCacheResponse,
    ScriptStockPexelsDeleteRequest,
    ScriptStockPexelsDeleteResponse,
    ScriptStockPexelsDownloadRequest,
    ScriptStockPexelsDownloadResponse,
    ScriptStockPexelsSearchResponse,
)
from app.utils.paths import ensure_storage_subpath, resolve_stored_path, storage_public_url_for_file, to_stored_path

from app.api.script_stock_shared import cfg, router, stock_http_proxy

logger = logging.getLogger(__name__)

PEXELS_VIDEO_SEARCH_URL = "https://api.pexels.com/v1/videos/search"
PEXELS_PHOTO_SEARCH_URL = "https://api.pexels.com/v1/search"
_PEXELS_FN_ID = re.compile(r"^pexels_(?:img_)?(\d+)_", re.IGNORECASE)
_PEXELS_META_FILENAME = "pexels_cache_meta.json"


def _pexels_meta_path(root: str) -> str:
    return os.path.join(root, _PEXELS_META_FILENAME)


def read_pexels_meta(root: str) -> dict[str, Any]:
    mp = _pexels_meta_path(root)
    if not os.path.isfile(mp):
        return {}
    try:
        with open(mp, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def write_pexels_meta(root: str, data: dict[str, Any]) -> None:
    mp = _pexels_meta_path(root)
    tmp = mp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, mp)


def _map_pexels_video(v: dict) -> PexelsVideoSummary:
    files_raw = v.get("video_files") or []
    files: List[PexelsVideoFile] = []
    for f in files_raw:
        if not isinstance(f, dict):
            continue
        link = (f.get("link") or "").strip()
        if not link:
            continue
        files.append(
            PexelsVideoFile(
                quality=str(f.get("quality") or ""),
                width=int(f.get("width") or 0),
                height=int(f.get("height") or 0),
                link=link,
            )
        )
    user = v.get("user") if isinstance(v.get("user"), dict) else {}
    return PexelsVideoSummary(
        id=int(v.get("id") or 0),
        width=int(v.get("width") or 0),
        height=int(v.get("height") or 0),
        duration=int(v.get("duration") or 0),
        image=str(v.get("image") or ""),
        user_name=str((user or {}).get("name") or ""),
        video_files=files,
    )


def _map_pexels_image(p: dict) -> PexelsImageSummary:
    user = p.get("user") if isinstance(p.get("user"), dict) else {}
    src = p.get("src") if isinstance(p.get("src"), dict) else {}
    thumb = str(src.get("medium") or src.get("large") or src.get("large2x") or p.get("url") or "")
    return PexelsImageSummary(
        id=int(p.get("id") or 0),
        width=int(p.get("width") or 0),
        height=int(p.get("height") or 0),
        image=thumb,
        user_name=str((user or {}).get("name") or ""),
    )


def _pick_pexels_file(files: List[PexelsVideoFile], preferred: str) -> PexelsVideoFile | None:
    if not files:
        return None
    pref = (preferred or "hd").lower()
    for q in (pref, "hd", "medium", "sd"):
        for f in files:
            if f.quality.lower() == q and f.link.lower().endswith(".mp4"):
                return f
    for f in files:
        if f.link.lower().endswith(".mp4"):
            return f
    return files[0]


@router.get("/pexels/search", response_model=ScriptStockPexelsSearchResponse)
async def pexels_search(query: str, page: int = 1, per_page: int = 12) -> ScriptStockPexelsSearchResponse:
    q = (query or "").strip()
    if not q:
        raise HTTPException(400, "query 不能为空")
    per_page = max(1, min(24, int(per_page)))
    page = max(1, int(page))

    async with aiosqlite.connect(DB_PATH) as db:
        api_key = (await cfg(db, "pexels_api_key")).strip()
        http_proxy = await stock_http_proxy(db)
    if not api_key:
        raise HTTPException(
            400,
            "未配置 Pexels API Key，请在「设置 → 在线素材（文案成片）」中填写（详见 www.pexels.com/api）",
        )

    headers = {"Authorization": api_key}
    half = max(1, per_page // 2)
    vparams = {"query": q, "page": page, "per_page": half}
    iparams = {"query": q, "page": page, "per_page": per_page - half}
    try:
        async with stock_async_client(timeout=30.0, headers=headers, proxy=http_proxy) as client:
            vresp, iresp = await asyncio.gather(
                client.get(PEXELS_VIDEO_SEARCH_URL, headers=headers, params=vparams),
                client.get(PEXELS_PHOTO_SEARCH_URL, headers=headers, params=iparams),
            )
    except httpx.RequestError as e:
        raise HTTPException(502, detail=f"Pexels 请求失败: {e}")

    if vresp.status_code != 200:
        raise HTTPException(vresp.status_code, detail=vresp.text[:500])
    if iresp.status_code != 200:
        raise HTTPException(iresp.status_code, detail=iresp.text[:500])

    vdata = vresp.json()
    idata = iresp.json()
    videos = [_map_pexels_video(v) for v in (vdata.get("videos") or []) if isinstance(v, dict)]
    images = [_map_pexels_image(p) for p in (idata.get("photos") or []) if isinstance(p, dict)]
    total = int(vdata.get("total_results") or 0) + int(idata.get("total_results") or 0)
    return ScriptStockPexelsSearchResponse(
        page=page,
        per_page=per_page,
        total_results=total,
        videos=videos,
        images=images,
    )


@router.post("/pexels/download", response_model=ScriptStockPexelsDownloadResponse)
async def pexels_download(req: ScriptStockPexelsDownloadRequest) -> ScriptStockPexelsDownloadResponse:
    mid = int(req.pexels_media_id)
    if mid <= 0:
        raise HTTPException(400, "pexels_media_id 无效")
    media_type = (req.media_type or "video").lower()

    async with aiosqlite.connect(DB_PATH) as db:
        api_key = (await cfg(db, "pexels_api_key")).strip()
        http_proxy = await stock_http_proxy(db)
    if not api_key:
        raise HTTPException(400, "未配置 Pexels API Key")

    headers = {"Authorization": api_key}
    dest_dir = ensure_storage_subpath("stock_media", "pexels")
    preview = ""
    duration_sec = 0

    try:
        async with stock_async_client(
            timeout=600.0, follow_redirects=True, headers=headers, proxy=http_proxy
        ) as client:
            if media_type == "image":
                url = f"https://api.pexels.com/v1/photos/{mid}"
                resp = await client.get(url, headers=headers, timeout=45.0)
                if resp.status_code != 200:
                    raise HTTPException(resp.status_code, detail=resp.text[:500])
                raw = resp.json()
                data = raw if isinstance(raw, dict) else {}
                summary = _map_pexels_image(data)
                src = data.get("src") if isinstance(data.get("src"), dict) else {}
                dl = str(src.get("large2x") or src.get("large") or src.get("original") or "").strip()
                if not dl:
                    raise HTTPException(404, "未找到可下载的图片")
                preview = summary.image
                ext = ext_from_url(dl, ".jpg")
                fname = f"pexels_img_{mid}{ext}"
                dest_abs = os.path.join(dest_dir, fname)
                media = await client.get(dl)
                if media.status_code != 200:
                    raise HTTPException(502, detail="下载图片失败")
                with open(dest_abs, "wb") as f:
                    f.write(media.content)
            else:
                url = f"https://api.pexels.com/v1/videos/videos/{mid}"
                resp = await client.get(url, headers=headers, timeout=45.0)
                if resp.status_code != 200:
                    raise HTTPException(resp.status_code, detail=resp.text[:500])
                data = resp.json()
                summary = _map_pexels_video(data if isinstance(data, dict) else {})
                picked = _pick_pexels_file(summary.video_files, req.preferred_quality)
                if not picked:
                    raise HTTPException(404, "未找到可下载的视频文件")
                preview = summary.image
                duration_sec = int(summary.duration or 0)
                fname = f"pexels_{mid}_{picked.quality}_{picked.width}x{picked.height}.mp4"
                dest_abs = os.path.join(dest_dir, fname)
                media = await client.get(picked.link)
                if media.status_code != 200:
                    raise HTTPException(502, detail="下载视频失败")
                with open(dest_abs, "wb") as f:
                    f.write(media.content)
    except httpx.RequestError as e:
        raise HTTPException(502, detail=f"Pexels 请求失败: {e}") from e

    rel = to_stored_path(dest_abs)
    try:
        meta = read_pexels_meta(dest_dir)
        sq = (req.search_query or "").strip()[:500]
        meta[rel] = {
            "search_query": sq,
            "pexels_image": (preview or "").strip()[:2000],
            "duration_sec": duration_sec,
            "media_type": media_type,
        }
        write_pexels_meta(dest_dir, meta)
    except Exception as e:
        logger.warning("pexels meta write skipped: %s", e)

    return ScriptStockPexelsDownloadResponse(
        stored_rel_path=rel,
        public_url=storage_public_url_for_file(dest_abs),
        filename=os.path.basename(dest_abs),
    )


@router.get("/pexels/cache", response_model=ScriptStockPexelsCacheResponse)
async def pexels_cache_list() -> ScriptStockPexelsCacheResponse:
    root = ensure_storage_subpath("stock_media", "pexels")
    items: List[ScriptStockPexelsCacheItem] = []
    if not os.path.isdir(root):
        return ScriptStockPexelsCacheResponse(items=[])
    meta = read_pexels_meta(root)
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return ScriptStockPexelsCacheResponse(items=[])
    for name in names:
        if name == _PEXELS_META_FILENAME or name.endswith(".tmp"):
            continue
        low = name.lower()
        if not low.endswith(
            (".mp4", ".mov", ".webm", ".mkv", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
        ):
            continue
        full = os.path.join(root, name)
        if not os.path.isfile(full):
            continue
        try:
            st = os.stat(full)
            sz = int(st.st_size)
            mt = float(st.st_mtime)
        except OSError:
            sz, mt = 0, 0.0
        m = _PEXELS_FN_ID.match(name)
        vid = int(m.group(1)) if m else 0
        rel = to_stored_path(full)
        row = meta.get(rel) if isinstance(meta.get(rel), dict) else {}
        if not isinstance(row, dict):
            row = {}
        sq = str(row.get("search_query") or "")[:500]
        img = str(row.get("pexels_image") or "")[:2000]
        try:
            dsec = int(row.get("duration_sec") or row.get("duration") or 0)
        except (TypeError, ValueError):
            dsec = 0
        mt_row = str(row.get("media_type") or "").lower()
        if mt_row not in ("image", "video"):
            mt_row = media_type_from_path(full)
        items.append(
            ScriptStockPexelsCacheItem(
                pexels_video_id=vid,
                media_type=mt_row,  # type: ignore[arg-type]
                stored_rel_path=rel,
                filename=name,
                size_bytes=sz,
                mtime=mt,
                search_query=sq,
                pexels_image=img,
                duration_sec=dsec,
            )
        )
    items.sort(key=lambda x: -x.mtime)
    return ScriptStockPexelsCacheResponse(items=items)


@router.post("/pexels/delete-file", response_model=ScriptStockPexelsDeleteResponse)
async def pexels_delete_file(req: ScriptStockPexelsDeleteRequest) -> ScriptStockPexelsDeleteResponse:
    rel = (req.stored_rel_path or "").strip().replace("\\", "/")
    if not rel:
        raise HTTPException(400, "stored_rel_path 不能为空")
    abs_path = resolve_stored_path(rel)
    if not abs_path or not os.path.isfile(abs_path):
        raise HTTPException(404, "文件不存在或已删除")
    if not is_under_pexels_download_dir(abs_path):
        raise HTTPException(403, "非法路径：仅允许删除 stock_media/pexels 下的文件")
    try:
        os.unlink(abs_path)
    except OSError as e:
        logger.warning("pexels delete failed: %s", e)
        raise HTTPException(500, detail=str(e)) from e
    try:
        root = ensure_storage_subpath("stock_media", "pexels")
        meta = read_pexels_meta(root)
        if rel in meta:
            del meta[rel]
            write_pexels_meta(root, meta)
    except Exception as e:
        logger.warning("pexels meta delete skipped: %s", e)
    return ScriptStockPexelsDeleteResponse(ok=True)


@router.post("/pexels/clear-cache", response_model=ScriptStockPexelsClearCacheResponse)
async def pexels_clear_cache() -> ScriptStockPexelsClearCacheResponse:
    root = ensure_storage_subpath("stock_media", "pexels")
    deleted = 0
    if not os.path.isdir(root):
        return ScriptStockPexelsClearCacheResponse(ok=True, deleted_files=0)
    try:
        names = list(os.listdir(root))
    except OSError:
        return ScriptStockPexelsClearCacheResponse(ok=True, deleted_files=0)
    for name in names:
        if name == _PEXELS_META_FILENAME or name.endswith(".tmp"):
            continue
        low = name.lower()
        if not low.endswith(
            (".mp4", ".mov", ".webm", ".mkv", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
        ):
            continue
        full = os.path.join(root, name)
        if not os.path.isfile(full):
            continue
        if not is_under_pexels_download_dir(full):
            continue
        try:
            os.unlink(full)
            deleted += 1
        except OSError as e:
            logger.warning("pexels clear unlink %s: %s", full, e)
    mp = _pexels_meta_path(root)
    try:
        if os.path.isfile(mp):
            os.unlink(mp)
    except OSError as e:
        logger.warning("pexels clear meta: %s", e)
    return ScriptStockPexelsClearCacheResponse(ok=True, deleted_files=deleted)
