"""文案成片：Pexels / Pixabay / Unsplash 本地下载目录与元数据。"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Literal, Mapping

import httpx

from app.utils.paths import ensure_storage_subpath, to_stored_path

STOCK_PROVIDERS = ("pexels", "pixabay", "unsplash")
_META_FILENAME = "stock_cache_meta.json"

StockMediaType = Literal["image", "video"]

_FN_PATTERNS = {
    "pexels": re.compile(r"^pexels_(?:img_)?(\d+)_", re.IGNORECASE),
    "pixabay": re.compile(r"^pixabay_(?:img_)?(\d+)_", re.IGNORECASE),
    "unsplash": re.compile(r"^unsplash_([A-Za-z0-9_-]+)_", re.IGNORECASE),
}

_VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv")
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
_MEDIA_EXTS = _VIDEO_EXTS + _IMAGE_EXTS


def stock_download_root(provider: str) -> str:
    if provider not in STOCK_PROVIDERS:
        raise ValueError(f"unknown stock provider: {provider}")
    return ensure_storage_subpath("stock_media", provider)


def is_under_stock_download_dir(abs_path: str, provider: str) -> bool:
    root = os.path.normpath(stock_download_root(provider))
    ap = os.path.normpath(os.path.abspath(abs_path))
    return ap.startswith(root + os.sep) or ap == root


def is_under_pexels_download_dir(abs_path: str) -> bool:
    return is_under_stock_download_dir(abs_path, "pexels")


def is_stock_image_path(path: str) -> bool:
    return (path or "").lower().endswith(_IMAGE_EXTS)


def is_stock_video_path(path: str) -> bool:
    return (path or "").lower().endswith(_VIDEO_EXTS)


def media_type_from_path(path: str) -> StockMediaType:
    if is_stock_image_path(path):
        return "image"
    return "video"


def default_image_hold_sec() -> float:
    raw = (os.environ.get("SMARTCLIP_STOCK_IMAGE_HOLD_SEC", "3") or "").strip()
    try:
        v = float(raw)
        return max(0.5, min(30.0, v))
    except ValueError:
        return 3.0


def _meta_path(root: str) -> str:
    return os.path.join(root, _META_FILENAME)


def read_stock_meta(root: str) -> dict[str, Any]:
    mp = _meta_path(root)
    if not os.path.isfile(mp):
        return {}
    try:
        with open(mp, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def write_stock_meta(root: str, data: dict[str, Any]) -> None:
    mp = _meta_path(root)
    tmp = mp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, mp)


def parse_media_id_from_filename(provider: str, name: str) -> str:
    pat = _FN_PATTERNS.get(provider)
    if not pat:
        return ""
    m = pat.match(name)
    return m.group(1) if m else ""


def list_cached_media_files(provider: str) -> list[tuple[str, str, int, float]]:
    """返回 [(rel_path, filename, size_bytes, mtime), ...]（含图片与视频）。"""
    root = stock_download_root(provider)
    out: list[tuple[str, str, int, float]] = []
    if not os.path.isdir(root):
        return out
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for name in names:
        if name == _META_FILENAME or name.endswith(".tmp"):
            continue
        if not name.lower().endswith(_MEDIA_EXTS):
            continue
        full = os.path.join(root, name)
        if not os.path.isfile(full):
            continue
        try:
            st = os.stat(full)
            sz, mt = int(st.st_size), float(st.st_mtime)
        except OSError:
            sz, mt = 0, 0.0
        out.append((to_stored_path(full), name, sz, mt))
    return out


# 兼容旧引用
list_cached_video_files = list_cached_media_files


def ext_from_url(url: str, default: str = ".jpg") -> str:
    path = (url or "").split("?")[0]
    suffix = os.path.splitext(path)[1].lower()
    if suffix in _MEDIA_EXTS:
        return suffix
    return default


def normalize_stock_http_proxy(proxy: str | None) -> str | None:
    """设置中的代理 URL；空则直连（不读系统 HTTP_PROXY）。"""
    p = (proxy or "").strip()
    return p or None


def stock_async_client(
    *,
    timeout: float | httpx.Timeout = 30.0,
    headers: Mapping[str, str] | None = None,
    follow_redirects: bool = False,
    proxy: str | None = None,
) -> httpx.AsyncClient:
    """外网素材 API 客户端：默认忽略系统代理，仅当 proxy 非空时走指定代理。"""
    kwargs: dict[str, Any] = {
        "timeout": timeout,
        "trust_env": False,
        "follow_redirects": follow_redirects,
    }
    if headers:
        kwargs["headers"] = dict(headers)
    px = normalize_stock_http_proxy(proxy)
    if px:
        kwargs["proxy"] = px
    return httpx.AsyncClient(**kwargs)
