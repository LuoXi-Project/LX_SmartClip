"""script-stock 路由与共用辅助函数。"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, List, Tuple

import aiosqlite
from fastapi import APIRouter, HTTPException

from app.core.script_stock.stock_media import default_image_hold_sec, is_stock_image_path, is_under_stock_download_dir, normalize_stock_http_proxy
from app.models.script_stock import ScriptStockComposeRequest, ScriptStockComposeSegment
from app.utils.ffprobe_utils import probe_duration
from app.utils.paths import resolve_stored_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/script-stock", tags=["script-stock"])


async def cfg(db: aiosqlite.Connection, key: str, default: str = "") -> str:
    async with db.execute("SELECT value FROM config WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
    if row and row[0] is not None:
        return str(row[0])
    return default


async def stock_http_proxy(db: aiosqlite.Connection) -> str | None:
    return normalize_stock_http_proxy(await cfg(db, "stock_media_http_proxy"))


async def load_export_render_opts(db: aiosqlite.Connection) -> dict:
    keys = [
        "export_vcodec",
        "export_acodec",
        "export_preset",
        "export_crf",
        "export_video_bitrate_kbps",
        "export_audio_bitrate_kbps",
        "export_g",
        "export_keyint_min",
        "export_sc_threshold",
        "export_fps",
        "export_scale_width",
        "export_scale_height",
        "export_pix_fmt",
        "export_container",
        "export_gpu",
    ]
    opts: dict[str, str] = {}
    for key in keys:
        opts[key] = await cfg(db, key, "")
    return opts


def split_script_text(script: str, mode: str) -> List[str]:
    raw = (script or "").strip()
    if not raw:
        return []
    if mode == "line":
        parts = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    else:
        parts = [p.strip() for p in re.split(r"\n\s*\n+", raw) if p.strip()]
    return parts[:40]


def parse_json_array(text: str) -> Any:
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start = t.find("[")
        end = t.rfind("]")
        if start >= 0 and end > start:
            return json.loads(t[start : end + 1])
        raise


def online_rels_from_segment(seg: ScriptStockComposeSegment, provider: str) -> List[str]:
    if provider == "pexels":
        raw = seg.pexels_stored_rel_paths
        one = seg.stored_rel_path
    elif provider == "pixabay":
        raw = seg.pixabay_stored_rel_paths
        one = None
    elif provider == "unsplash":
        raw = seg.unsplash_stored_rel_paths
        one = None
    else:
        return []
    rels: List[str] = []
    if raw:
        rels = [str(x).strip().replace("\\", "/") for x in raw if str(x).strip()]
    if not rels and one:
        o = str(one).strip().replace("\\", "/")
        if o:
            rels = [o]
    return rels


def default_pair_for_path(abs_path: str) -> Tuple[float, float]:
    if is_stock_image_path(abs_path):
        return (0.0, default_image_hold_sec())
    d = float(probe_duration(abs_path) or 0.0)
    if d <= 0.02:
        d = 60.0
    return (0.0, d)


async def resolve_compose_rows(
    db: aiosqlite.Connection, req: ScriptStockComposeRequest
) -> List[Tuple[List[str], str, List[Tuple[float, float]]]]:
    out: List[Tuple[List[str], str, List[Tuple[float, float]]]] = []
    for seg in req.segments:
        if seg.kind == "library":
            raw_ids: List[str] = []
            if seg.library_video_ids:
                raw_ids = [str(x).strip() for x in seg.library_video_ids if str(x).strip()]
            if not raw_ids:
                vid = (seg.video_id or "").strip()
                if vid:
                    raw_ids = [vid]
            if not raw_ids:
                raise HTTPException(400, "library 分段缺少 video_id 或 library_video_ids")
            if len(raw_ids) > 12:
                raise HTTPException(400, "单段最多拼接 12 条本地素材")
            paths: List[str] = []
            for vid in raw_ids:
                async with db.execute(
                    "SELECT file_path FROM videos WHERE id = ?",
                    (vid,),
                ) as cur:
                    row = await cur.fetchone()
                if not row or not row[0]:
                    raise HTTPException(400, f"素材库视频不存在: {vid}")
                abs_path = resolve_stored_path(str(row[0]))
                if not abs_path or not os.path.isfile(abs_path):
                    raise HTTPException(400, f"视频文件缺失: {vid}")
                paths.append(abs_path)
            lt = seg.library_trims
            if lt is not None and len(lt) != len(paths):
                raise HTTPException(400, "library_trims 与 library_video_ids 数量须一致")
            trim_pairs: List[Tuple[float, float]] = []
            for j, p in enumerate(paths):
                if lt and j < len(lt):
                    a, b = float(lt[j].in_sec), float(lt[j].out_sec)
                    if b <= a + 0.02:
                        raise HTTPException(400, f"选用区间无效：out_sec 须大于 in_sec（第 {j + 1} 条）")
                    trim_pairs.append((a, b))
                else:
                    trim_pairs.append(default_pair_for_path(p))
            out.append((paths, "library", trim_pairs))
        elif seg.kind in ("pexels", "pixabay", "unsplash"):
            provider = seg.kind
            rels = online_rels_from_segment(seg, provider)
            if not rels:
                raise HTTPException(400, f"{provider} 分段缺少已下载文件路径")
            if len(rels) > 12:
                raise HTTPException(400, f"单段最多拼接 12 条 {provider} 文件")
            paths = []
            for rel in rels:
                abs_path = resolve_stored_path(rel)
                if not abs_path or not os.path.isfile(abs_path):
                    raise HTTPException(400, f"{provider} 本地文件不存在: {rel}")
                if not is_under_stock_download_dir(abs_path, provider):
                    raise HTTPException(
                        403,
                        f"非法素材路径：仅允许使用 stock_media/{provider} 下的下载文件",
                    )
                paths.append(abs_path)
            trim_pairs_px: List[Tuple[float, float]] = [default_pair_for_path(p) for p in paths]
            out.append((paths, provider, trim_pairs_px))
        else:
            raise HTTPException(400, "未知分段类型")
    return out
