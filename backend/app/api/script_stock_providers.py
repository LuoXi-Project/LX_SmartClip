"""Pixabay / Unsplash 搜索、下载与缓存管理。"""
from __future__ import annotations

import logging
import os

import aiosqlite
import httpx
from fastapi import HTTPException

from app.core.script_stock import providers_pixabay as pixabay_prov
from app.core.script_stock import providers_unsplash as unsplash_prov
from app.core.script_stock.stock_media import is_under_stock_download_dir
from app.db.database import DB_PATH
from app.models.script_stock import (
    ScriptStockPixabayCacheResponse,
    ScriptStockPixabayClearCacheResponse,
    ScriptStockPixabayDeleteRequest,
    ScriptStockPixabayDeleteResponse,
    ScriptStockPixabayDownloadRequest,
    ScriptStockPixabayDownloadResponse,
    ScriptStockPixabaySearchResponse,
    ScriptStockUnsplashCacheResponse,
    ScriptStockUnsplashClearCacheResponse,
    ScriptStockUnsplashDeleteRequest,
    ScriptStockUnsplashDeleteResponse,
    ScriptStockUnsplashDownloadRequest,
    ScriptStockUnsplashDownloadResponse,
    ScriptStockUnsplashSearchResponse,
)
from app.utils.paths import resolve_stored_path

from app.api.script_stock_shared import cfg, router, stock_http_proxy

logger = logging.getLogger(__name__)


@router.get("/pixabay/search", response_model=ScriptStockPixabaySearchResponse)
async def pixabay_search(query: str, page: int = 1, per_page: int = 12) -> ScriptStockPixabaySearchResponse:
    q = (query or "").strip()
    if not q:
        raise HTTPException(400, "query 不能为空")
    per_page = max(3, min(24, int(per_page)))
    page = max(1, int(page))
    async with aiosqlite.connect(DB_PATH) as db:
        api_key = (await cfg(db, "pixabay_api_key")).strip()
        http_proxy = await stock_http_proxy(db)
    if not api_key:
        raise HTTPException(
            400,
            "未配置 Pixabay API Key，请在「设置 → 在线素材（文案成片）」中填写（详见 pixabay.com/api/docs/）",
        )
    try:
        return await pixabay_prov.search_pixabay(api_key, q, page, per_page, http_proxy=http_proxy)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, detail=e.response.text[:500]) from e
    except httpx.RequestError as e:
        raise HTTPException(502, detail=f"Pixabay 请求失败: {e}") from e


@router.post("/pixabay/download", response_model=ScriptStockPixabayDownloadResponse)
async def pixabay_download(req: ScriptStockPixabayDownloadRequest) -> ScriptStockPixabayDownloadResponse:
    async with aiosqlite.connect(DB_PATH) as db:
        api_key = (await cfg(db, "pixabay_api_key")).strip()
        http_proxy = await stock_http_proxy(db)
    if not api_key:
        raise HTTPException(400, "未配置 Pixabay API Key")
    try:
        return await pixabay_prov.download_pixabay(api_key, req, http_proxy=http_proxy)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, detail=e.response.text[:500]) from e
    except httpx.RequestError as e:
        raise HTTPException(502, detail=f"Pixabay 请求失败: {e}") from e
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e


@router.get("/pixabay/cache", response_model=ScriptStockPixabayCacheResponse)
async def pixabay_cache_list() -> ScriptStockPixabayCacheResponse:
    return pixabay_prov.list_pixabay_cache()


@router.post("/pixabay/delete-file", response_model=ScriptStockPixabayDeleteResponse)
async def pixabay_delete_file(req: ScriptStockPixabayDeleteRequest) -> ScriptStockPixabayDeleteResponse:
    rel = (req.stored_rel_path or "").strip().replace("\\", "/")
    if not rel:
        raise HTTPException(400, "stored_rel_path 不能为空")
    abs_path = resolve_stored_path(rel)
    if not abs_path or not os.path.isfile(abs_path):
        raise HTTPException(404, "文件不存在或已删除")
    if not is_under_stock_download_dir(abs_path, "pixabay"):
        raise HTTPException(403, "非法路径：仅允许删除 stock_media/pixabay 下的文件")
    try:
        os.unlink(abs_path)
    except OSError as e:
        raise HTTPException(500, detail=str(e)) from e
    try:
        pixabay_prov.delete_pixabay_meta_entry(rel)
    except Exception as e:
        logger.warning("pixabay meta delete skipped: %s", e)
    return ScriptStockPixabayDeleteResponse(ok=True)


@router.post("/pixabay/clear-cache", response_model=ScriptStockPixabayClearCacheResponse)
async def pixabay_clear_cache() -> ScriptStockPixabayClearCacheResponse:
    return pixabay_prov.clear_pixabay_cache()


@router.get("/unsplash/search", response_model=ScriptStockUnsplashSearchResponse)
async def unsplash_search(query: str, page: int = 1, per_page: int = 12) -> ScriptStockUnsplashSearchResponse:
    q = (query or "").strip()
    if not q:
        raise HTTPException(400, "query 不能为空")
    per_page = max(1, min(30, int(per_page)))
    page = max(1, int(page))
    async with aiosqlite.connect(DB_PATH) as db:
        access_key = (await cfg(db, "unsplash_access_key")).strip()
        http_proxy = await stock_http_proxy(db)
    if not access_key:
        raise HTTPException(
            400,
            "未配置 Unsplash Access Key，请在「设置 → 在线素材（文案成片）」中填写（详见 unsplash.com/developers）",
        )
    try:
        return await unsplash_prov.search_unsplash(access_key, q, page, per_page, http_proxy=http_proxy)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, detail=e.response.text[:500]) from e
    except httpx.RequestError as e:
        raise HTTPException(502, detail=f"Unsplash 请求失败: {e}") from e


@router.post("/unsplash/download", response_model=ScriptStockUnsplashDownloadResponse)
async def unsplash_download(req: ScriptStockUnsplashDownloadRequest) -> ScriptStockUnsplashDownloadResponse:
    async with aiosqlite.connect(DB_PATH) as db:
        access_key = (await cfg(db, "unsplash_access_key")).strip()
        http_proxy = await stock_http_proxy(db)
    if not access_key:
        raise HTTPException(400, "未配置 Unsplash Access Key")
    try:
        return await unsplash_prov.download_unsplash(access_key, req, http_proxy=http_proxy)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, detail=e.response.text[:500]) from e
    except httpx.RequestError as e:
        raise HTTPException(502, detail=f"Unsplash 请求失败: {e}") from e
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(500, detail=str(e)) from e


@router.get("/unsplash/cache", response_model=ScriptStockUnsplashCacheResponse)
async def unsplash_cache_list() -> ScriptStockUnsplashCacheResponse:
    return unsplash_prov.list_unsplash_cache()


@router.post("/unsplash/delete-file", response_model=ScriptStockUnsplashDeleteResponse)
async def unsplash_delete_file(req: ScriptStockUnsplashDeleteRequest) -> ScriptStockUnsplashDeleteResponse:
    rel = (req.stored_rel_path or "").strip().replace("\\", "/")
    if not rel:
        raise HTTPException(400, "stored_rel_path 不能为空")
    abs_path = resolve_stored_path(rel)
    if not abs_path or not os.path.isfile(abs_path):
        raise HTTPException(404, "文件不存在或已删除")
    if not is_under_stock_download_dir(abs_path, "unsplash"):
        raise HTTPException(403, "非法路径：仅允许删除 stock_media/unsplash 下的文件")
    try:
        os.unlink(abs_path)
    except OSError as e:
        raise HTTPException(500, detail=str(e)) from e
    try:
        unsplash_prov.delete_unsplash_meta_entry(rel)
    except Exception as e:
        logger.warning("unsplash meta delete skipped: %s", e)
    return ScriptStockUnsplashDeleteResponse(ok=True)


@router.post("/unsplash/clear-cache", response_model=ScriptStockUnsplashClearCacheResponse)
async def unsplash_clear_cache() -> ScriptStockUnsplashClearCacheResponse:
    return unsplash_prov.clear_unsplash_cache()
