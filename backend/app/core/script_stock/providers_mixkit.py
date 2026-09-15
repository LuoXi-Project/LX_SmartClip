"""Mixkit 视频搜索与下载（文案成片；仅视频）。

Mixkit（Envato 旗下）没有官方 API。其网页搜索由前端直连 Algolia 完成
（服务端渲染的 HTML 网格是固定的默认列表、不随 ?q= 变化），因此：

- 搜索：直接调用其公开的 Algolia 查询接口（App ID / 搜索 Key / 索引名
  均内嵌在页面 HTML 的 data-* 属性中，为前端公开密钥），按 query + type:video
  过滤，命中记录的 overviewData 自带缩略图、时长与 360/720/1080 分级 mp4 直链。
- 下载：按 itemId 反查 Algolia 取最高可用清晰度直链；Algolia 不可用时回退
  抓详情页 JSON-LD 的 contentUrl（需 detail_path）。
- mp4 走 assets.mixkit.co CDN，无需认证；页面请求需浏览器 UA。

algolianet/algolia 各主机在国内连通性不一，按列表轮询。
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, List
from urllib.parse import quote

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
    MixkitVideoSummary,
    ScriptStockMixkitCacheItem,
    ScriptStockMixkitCacheResponse,
    ScriptStockMixkitClearCacheResponse,
    ScriptStockMixkitDownloadRequest,
    ScriptStockMixkitDownloadResponse,
    ScriptStockMixkitSearchResponse,
)
from app.utils.paths import storage_public_url_for_file, to_stored_path

logger = logging.getLogger(__name__)

MIXKIT_SITE = "https://mixkit.co"
_PROVIDER = "mixkit"

# Algolia 配置（内嵌于 mixkit 页面的公开前端搜索密钥）
_ALGOLIA_APP_ID = "ZKRSER95J1"
_ALGOLIA_API_KEY = "9279146abe17592c4cc491f4124dc5ef"
_ALGOLIA_INDEX = "mixkit_prod_v4"
_ALGOLIA_HOSTS = (
    "https://zkrser95j1-dsn.algolia.net",
    "https://zkrser95j1.algolia.net",
    "https://zkrser95j1-1.algolianet.com",
    "https://zkrser95j1-2.algolianet.com",
    "https://zkrser95j1-3.algolianet.com",
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_ISO_DUR_RE = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$", re.IGNORECASE)


def _headers() -> dict[str, str]:
    return {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}


def _algolia_headers() -> dict[str, str]:
    return {
        "X-Algolia-Application-Id": _ALGOLIA_APP_ID,
        "X-Algolia-API-Key": _ALGOLIA_API_KEY,
        "Content-Type": "application/json",
    }


async def _algolia_query(
    params: str, *, http_proxy: str | None = None, timeout: float = 20.0
) -> dict[str, Any]:
    """POST /1/indexes/{index}/query；连接错误或 429/5xx 时轮询下一主机。"""
    body = json.dumps({"params": params})
    last: Exception | None = None
    async with stock_async_client(timeout=timeout, proxy=http_proxy) as client:
        for host in _ALGOLIA_HOSTS:
            try:
                resp = await client.post(
                    f"{host}/1/indexes/{_ALGOLIA_INDEX}/query",
                    content=body,
                    headers=_algolia_headers(),
                )
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                last = e
                continue
            if resp.status_code >= 500 or resp.status_code == 429:
                last = httpx.HTTPStatusError(
                    f"algolia host {host} -> {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
                continue
            if resp.status_code != 200:
                raise httpx.HTTPStatusError("algolia query failed", request=resp.request, response=resp)
            data = resp.json()
            return data if isinstance(data, dict) else {}
    assert last is not None
    raise last


def _map_hit(hit: dict) -> MixkitVideoSummary:
    ov = hit.get("overviewData") if isinstance(hit.get("overviewData"), dict) else {}
    item_id = str(hit.get("itemId") or "")
    slug = str(ov.get("urlSlug") or "")
    detail_path = f"/free-stock-video/{slug}-{item_id}/" if slug and item_id else ""
    try:
        duration = int(hit.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    return MixkitVideoSummary(
        id=item_id,
        title=str(hit.get("title") or "")[:300],
        image=str(ov.get("small_thumbnail_url") or ov.get("large_thumbnail_url") or "").strip(),
        detail_path=detail_path,
        duration=duration,
    )


def _pick_best_mp4(ov: dict) -> tuple[str, str]:
    """(url, 清晰度标签)；按 1080→720→360 取 overviewData 中第一个可用直链。"""
    for label, key in (("1080", "video_1080_url"), ("720", "video_720_url"), ("360", "video_360_url")):
        url = str(ov.get(key) or "").strip()
        if url:
            return url, label
    return "", ""


def _parse_iso_duration(raw: str) -> float:
    m = _ISO_DUR_RE.match((raw or "").strip())
    if not m:
        return 0.0
    h = float(m.group(1) or 0)
    mi = float(m.group(2) or 0)
    s = float(m.group(3) or 0)
    return h * 3600 + mi * 60 + s


def _video_object_from_ld_json(html: str) -> dict:
    """解析详情页 JSON-LD，返回第一个 VideoObject 节点（dict）；找不到返回 {}。"""
    for m in re.finditer(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S
    ):
        raw = m.group(1).strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        def _walk(node: object) -> dict:
            if isinstance(node, dict):
                if node.get("@type") == "VideoObject":
                    return node
                for v in node.values():
                    hit = _walk(v)
                    if hit:
                        return hit
            elif isinstance(node, list):
                for v in node:
                    hit = _walk(v)
                    if hit:
                        return hit
            return {}

        hit = _walk(data)
        if hit:
            return hit
    return {}


async def search_mixkit(
    query: str,
    page: int,
    per_page: int,
    *,
    http_proxy: str | None = None,
) -> ScriptStockMixkitSearchResponse:
    """页码 1 起始（内部转 Algolia 0 起始）。"""
    params = (
        f"query={quote(query)}"
        f"&hitsPerPage={max(1, min(24, int(per_page)))}"
        f"&page={max(0, int(page) - 1)}"
        "&filters=type:video"
    )
    data = await _algolia_query(params, http_proxy=http_proxy)
    hits = data.get("hits") or []
    videos = [_map_hit(h) for h in hits if isinstance(h, dict) and h.get("itemId")]
    return ScriptStockMixkitSearchResponse(
        page=page,
        per_page=int(per_page),
        total_results=int(data.get("nbHits") or 0),
        total_pages=int(data.get("nbPages") or 0),
        videos=videos,
    )


async def _fetch_detail_video(
    detail_path: str, *, http_proxy: str | None = None
) -> tuple[str, float, str, str]:
    """回退路径：抓详情页 JSON-LD，返回 (mp4 url, duration_sec, title, thumb)。"""
    async with stock_async_client(
        timeout=45.0, headers=_headers(), proxy=http_proxy, follow_redirects=True
    ) as client:
        resp = await client.get(f"{MIXKIT_SITE}{detail_path}")
        if resp.status_code != 200:
            raise httpx.HTTPStatusError("mixkit detail fetch failed", request=resp.request, response=resp)
        video = _video_object_from_ld_json(resp.text)
        url = str(video.get("contentUrl") or "").strip()
        if not url:
            raise ValueError("未从详情页解析到视频直链")
        return (
            url,
            _parse_iso_duration(str(video.get("duration") or "")),
            str(video.get("name") or "").strip(),
            str(video.get("thumbnailUrl") or "").strip(),
        )


async def download_mixkit(
    req: ScriptStockMixkitDownloadRequest,
    *,
    http_proxy: str | None = None,
) -> ScriptStockMixkitDownloadResponse:
    mid = (req.mixkit_media_id or "").strip()
    if not mid or not mid.isdigit():
        raise ValueError("mixkit_media_id 无效（应为数字 id）")

    url = ""
    res_label = "0"
    duration = 0.0
    title = ""
    thumb = ""

    # 首选：Algolia 按 itemId 反查（含各清晰度可用性）
    try:
        data = await _algolia_query(
            f"query=&hitsPerPage=1&filters=itemId={mid} AND type:video",
            http_proxy=http_proxy,
        )
        hits = data.get("hits") or []
        if hits and isinstance(hits[0], dict):
            hit = hits[0]
            ov = hit.get("overviewData") if isinstance(hit.get("overviewData"), dict) else {}
            url, res_label = _pick_best_mp4(ov)
            duration = float(hit.get("duration") or 0)
            title = str(hit.get("title") or "").strip()
            thumb = str(ov.get("small_thumbnail_url") or "").strip()
    except Exception as e:
        logger.warning("mixkit algolia lookup failed, fallback to detail page: %s", e)

    # 回退：详情页 JSON-LD
    if not url:
        detail_path = (req.detail_path or "").strip()
        if not detail_path.startswith("/") or ".." in detail_path:
            raise ValueError("Algolia 不可用且未提供有效的 detail_path，无法定位下载地址")
        url, duration, title, thumb = await _fetch_detail_video(detail_path, http_proxy=http_proxy)
        m = re.search(r"-(\d+)\.mp4$", url)
        res_label = m.group(1) if m else "0"

    dest_dir = stock_download_root(_PROVIDER)
    fname = f"mixkit_{mid}_{res_label}.mp4"
    dest_abs = os.path.join(dest_dir, fname)

    async with stock_async_client(timeout=600.0, follow_redirects=True, proxy=http_proxy) as client:
        media = await client.get(url, headers={"User-Agent": _UA, "Referer": f"{MIXKIT_SITE}/"})
    if media.status_code != 200:
        raise ValueError("下载视频失败")
    with open(dest_abs, "wb") as f:
        f.write(media.content)

    rel = to_stored_path(dest_abs)
    try:
        meta = read_stock_meta(dest_dir)
        sq = (req.search_query or "").strip()[:500]
        meta[rel] = {
            "search_query": sq,
            "preview_image": (thumb or "").strip()[:2000],
            "duration_sec": round(duration, 3),
            "media_type": "video",
            "mixkit_video_id": mid,
            "title": title[:300],
        }
        write_stock_meta(dest_dir, meta)
    except Exception as e:
        logger.warning("mixkit meta write skipped: %s", e)

    return ScriptStockMixkitDownloadResponse(
        stored_rel_path=rel,
        public_url=storage_public_url_for_file(dest_abs),
        filename=os.path.basename(dest_abs),
    )


def list_mixkit_cache() -> ScriptStockMixkitCacheResponse:
    root = stock_download_root(_PROVIDER)
    meta = read_stock_meta(root)
    items: List[ScriptStockMixkitCacheItem] = []
    for rel, name, sz, mt in list_cached_media_files(_PROVIDER):
        mid = parse_media_id_from_filename(_PROVIDER, name)
        row = meta.get(rel) if isinstance(meta.get(rel), dict) else {}
        if not isinstance(row, dict):
            row = {}
        try:
            dsec = float(row.get("duration_sec") or 0)
        except (TypeError, ValueError):
            dsec = 0.0
        items.append(
            ScriptStockMixkitCacheItem(
                mixkit_video_id=str(row.get("mixkit_video_id") or mid or "")[:32],
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
    return ScriptStockMixkitCacheResponse(items=items)


def clear_mixkit_cache() -> ScriptStockMixkitClearCacheResponse:
    from app.core.script_stock.stock_media import is_under_stock_download_dir

    root = stock_download_root(_PROVIDER)
    deleted = 0
    if not os.path.isdir(root):
        return ScriptStockMixkitClearCacheResponse(ok=True, deleted_files=0)
    for _, name, _, _ in list_cached_media_files(_PROVIDER):
        full = os.path.join(root, name)
        if not is_under_stock_download_dir(full, _PROVIDER):
            continue
        try:
            os.unlink(full)
            deleted += 1
        except OSError as e:
            logger.warning("mixkit clear unlink %s: %s", full, e)
    mp = os.path.join(root, "stock_cache_meta.json")
    try:
        if os.path.isfile(mp):
            os.unlink(mp)
    except OSError as e:
        logger.warning("mixkit clear meta: %s", e)
    return ScriptStockMixkitClearCacheResponse(ok=True, deleted_files=deleted)


def delete_mixkit_meta_entry(rel: str) -> None:
    root = stock_download_root(_PROVIDER)
    meta = read_stock_meta(root)
    if rel in meta:
        del meta[rel]
        write_stock_meta(root, meta)
