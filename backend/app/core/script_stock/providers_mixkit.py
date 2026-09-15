"""Mixkit 视频搜索与下载（文案成片；仅视频）。

Mixkit（Envato 旗下）没有官方 API，走页面抓取：
- 搜索页 https://mixkit.co/free-stock-video/search/?q={query}&page={n} 为服务端渲染，
  卡片含 item id、缩略图、详情页链接（每页 24 条，页码 1 起始）。
- 详情页 JSON-LD 的 VideoObject 提供 contentUrl（最高画质 mp4 直链，CDN 无需认证）、
  duration（ISO8601）、name、thumbnailUrl。
仅需浏览器 UA（站方对无 UA 请求可能拒绝）；HTTP 代理沿用 stock_media_http_proxy。
"""
from __future__ import annotations

import json
import logging
import os
import re
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

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

_CARD_ID_RE = re.compile(r'data-item-grid--video-player-item-id-value="(\d+)"')
_CARD_THUMB_RE = re.compile(r'<img src="(https://assets\.mixkit\.co/videos/[^"]+)"[^>]*>')
_CARD_TITLE_RE = re.compile(r'overlay-video-title">\s*([^<]+?)\s*<', re.S)
_CARD_LINK_RE = re.compile(r'<a href="(/free-stock-video/[^"]+)"[^>]*class="item-grid-video-player__overlay-link"')
_CARD_LINK_RE2 = re.compile(r'class="item-grid-video-player__overlay-link"[^>]* href="(/free-stock-video/[^"]+)"')

_ISO_DUR_RE = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$", re.IGNORECASE)


def _headers() -> dict[str, str]:
    return {"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"}


async def _get_with_retry(
    client: httpx.AsyncClient, url: str, *, retries: int = 1, **kwargs
) -> httpx.Response:
    """mixkit.co 直连偶发超时，连接类错误重试一次。"""
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            return await client.get(url, **kwargs)
        except httpx.ConnectError as e:
            last = e
        except httpx.ConnectTimeout as e:
            last = e
    assert last is not None
    raise last


def _parse_iso_duration(raw: str) -> float:
    m = _ISO_DUR_RE.match((raw or "").strip())
    if not m:
        return 0.0
    h = float(m.group(1) or 0)
    mi = float(m.group(2) or 0)
    s = float(m.group(3) or 0)
    return h * 3600 + mi * 60 + s


def _parse_search_html(html: str) -> List[MixkitVideoSummary]:
    """按卡片起始锚点切块后逐块提取，避免跨卡片串数据。"""
    anchors = list(_CARD_ID_RE.finditer(html))
    out: List[MixkitVideoSummary] = []
    seen: set[str] = set()
    for i, m in enumerate(anchors):
        vid = m.group(1)
        if vid in seen:
            continue
        end = anchors[i + 1].start() if i + 1 < len(anchors) else min(len(html), m.end() + 6000)
        block = html[m.end() : end]
        thumb_m = _CARD_THUMB_RE.search(block)
        title_m = _CARD_TITLE_RE.search(block)
        link_m = _CARD_LINK_RE.search(block) or _CARD_LINK_RE2.search(block)
        title = (title_m.group(1) if title_m else "").strip()
        if not title and thumb_m:
            # alt="Title." 与 src 同在 img 标签内
            alt_m = re.search(r'alt="([^"]*)"', block[thumb_m.start() : thumb_m.end()])
            if alt_m:
                title = alt_m.group(1).rstrip(".").strip()
        out.append(
            MixkitVideoSummary(
                id=vid,
                title=title[:300],
                image=(thumb_m.group(1) if thumb_m else "").strip(),
                detail_path=(link_m.group(1) if link_m else "").strip(),
            )
        )
        seen.add(vid)
    return out


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
    """页码 1 起始；Mixkit 每页固定 24 条，per_page 只做截断。

    page=1 时必须省略 page 参数（显式 page=1 会被 301 规范化）；
    超出最大页时站点 301 回第 1 页，此处不跟随重定向、按空结果处理。
    """
    params: dict[str, str | int] = {"q": query}
    if int(page) > 1:
        params["page"] = int(page)
    async with stock_async_client(timeout=30.0, headers=_headers(), proxy=http_proxy, follow_redirects=False) as client:
        resp = await _get_with_retry(client, f"{MIXKIT_SITE}/free-stock-video/search/", params=params)
    if resp.status_code != 200:
        # 超出最大页时站点返回 301；当作空结果
        if resp.status_code in (301, 302, 303, 307, 308):
            return ScriptStockMixkitSearchResponse(page=page, per_page=per_page, total_results=0, videos=[])
        raise httpx.HTTPStatusError("mixkit search failed", request=resp.request, response=resp)
    videos = _parse_search_html(resp.text)
    if per_page and per_page > 0:
        videos = videos[:per_page]
    return ScriptStockMixkitSearchResponse(page=page, per_page=per_page, total_results=0, videos=videos)


async def download_mixkit(
    req: ScriptStockMixkitDownloadRequest,
    *,
    http_proxy: str | None = None,
) -> ScriptStockMixkitDownloadResponse:
    mid = (req.mixkit_media_id or "").strip()
    detail_path = (req.detail_path or "").strip()
    if not mid or not detail_path:
        raise ValueError("mixkit_media_id 与 detail_path 均不能为空")
    if not detail_path.startswith("/") or ".." in detail_path:
        raise ValueError("detail_path 非法")

    async with stock_async_client(timeout=45.0, headers=_headers(), proxy=http_proxy, follow_redirects=True) as client:
        resp = await _get_with_retry(client, f"{MIXKIT_SITE}{detail_path}")
        if resp.status_code != 200:
            raise httpx.HTTPStatusError("mixkit detail fetch failed", request=resp.request, response=resp)
        video = _video_object_from_ld_json(resp.text)
        url = str(video.get("contentUrl") or "").strip()
        if not url:
            raise ValueError("未从详情页解析到视频直链")
        title = str(video.get("name") or "").strip()
        thumb = str(video.get("thumbnailUrl") or "").strip()
        duration = _parse_iso_duration(str(video.get("duration") or ""))

        res_m = re.search(r"-(\d+)\.mp4$", url)
        res_label = res_m.group(1) if res_m else "0"

        dest_dir = stock_download_root(_PROVIDER)
        safe_id = "".join(c if c.isalnum() else "_" for c in mid)[:32]
        fname = f"mixkit_{safe_id}_{res_label}.mp4"
        dest_abs = os.path.join(dest_dir, fname)

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
