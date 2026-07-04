"""成片管理 API 路由。

供前端「成片中心」使用：列表（搜索/筛选/分页）、详情、缩略图（懒生成）、删除、手动扫描。
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.utils.paths import resolve_stored_path, storage_public_url_for_file

from . import renders_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/renders", tags=["renders"])

# 来源中文标签（前端展示用）
SOURCE_LABELS = {
    "burn": "一键成片",
    "export_original": "原声成片",
    "realize": "智剪/模板",
    "film_commentary": "影视解说",
    "script_stock_compose": "文案素材",
}


def _decorate(rec: dict) -> dict:
    """给单条 render 记录补充前端需要的派生字段。"""
    # 缩略图 URL：若有 thumbnail_path 返回 /storage/...，否则用懒生成端点
    if rec.get("thumbnail_path"):
        try:
            thumb_abs = resolve_stored_path(rec["thumbnail_path"])
            rec["thumbnail_url"] = storage_public_url_for_file(thumb_abs)
        except Exception:
            rec["thumbnail_url"] = None
    else:
        # 前端可用此 URL 触发懒生成（首次访问时生成）
        rec["thumbnail_url"] = None
    rec["thumbnail_api_url"] = f"/api/renders/{rec['id']}/thumbnail"
    rec["source_label"] = SOURCE_LABELS.get(rec.get("source", ""), rec.get("source", ""))
    # 视频预览 URL（直接走 /storage 静态）
    rec["video_url"] = rec.get("public_url")
    return rec


@router.get("")
@router.get("/")
async def list_renders(
    search: str | None = Query(None, description="搜索 filename/title"),
    source: str | None = Query(None, description="按来源过滤"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """成片列表（分页 + 搜索 + 来源过滤），按创建时间倒序。"""
    items = await renders_db.list_renders(search=search, source=source, limit=limit, offset=offset)
    total = await renders_db.count_renders(search=search, source=source)
    return {
        "items": [_decorate(it) for it in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/sources")
async def list_sources():
    """列出所有来源类型（前端筛选 tab 用）。"""
    return {
        "sources": [
            {"value": k, "label": v}
            for k, v in SOURCE_LABELS.items()
        ]
    }


@router.get("/{render_id}")
async def get_render(render_id: str):
    """成片详情。"""
    rec = await renders_db.get_render(render_id)
    if not rec:
        raise HTTPException(status_code=404, detail="成片不存在")
    return _decorate(rec)


@router.get("/{render_id}/thumbnail")
async def get_thumbnail(render_id: str):
    """成片缩略图（懒生成：首次访问时生成并缓存）。"""
    rec = await renders_db.get_render(render_id)
    if not rec:
        raise HTTPException(status_code=404, detail="成片不存在")

    # 1. 若已生成，直接返回
    if rec.get("thumbnail_path"):
        try:
            thumb_abs = resolve_stored_path(rec["thumbnail_path"])
            if os.path.isfile(thumb_abs):
                return FileResponse(thumb_abs, media_type="image/jpeg")
        except Exception:
            pass

    # 2. 懒生成
    from app.utils.render_thumbnail import generate_render_thumbnail
    try:
        video_abs = resolve_stored_path(rec["file_path"])
    except Exception:
        raise HTTPException(status_code=404, detail="成片文件路径无法解析")

    if not os.path.isfile(video_abs):
        raise HTTPException(status_code=404, detail="成片文件不存在（可能已被外部删除）")

    thumb_abs = generate_render_thumbnail(video_abs)
    if not thumb_abs:
        raise HTTPException(status_code=500, detail="缩略图生成失败")

    # 记录到 DB（相对路径）
    thumb_rel = "storage/" + os.path.relpath(thumb_abs, os.path.dirname(os.path.dirname(video_abs))).replace("\\", "/")
    # 更稳妥：用 storage_public_url_for_file 的逆逻辑存相对路径
    from app.utils.paths import get_storage_root
    try:
        root = os.path.normpath(str(get_storage_root().resolve()))
        thumb_rel = "storage/" + os.path.relpath(thumb_abs, root).replace("\\", "/")
    except Exception:
        thumb_rel = thumb_abs.replace("\\", "/")
    await renders_db.mark_thumbnail(render_id, thumb_rel)

    return FileResponse(thumb_abs, media_type="image/jpeg")


@router.delete("/{render_id}")
async def delete_render(render_id: str):
    """删除成片（DB 记录 + 物理文件 + 缩略图）。"""
    rec = await renders_db.delete_render(render_id)
    if not rec:
        raise HTTPException(status_code=404, detail="成片不存在")
    return {"deleted": True, "filename": rec.get("filename")}


@router.post("/scan")
async def scan_renders():
    """手动触发成片扫描（补录历史/新发现的成片）。"""
    from app.utils.render_scanner import scan_and_record
    stats = await scan_and_record()
    return {"stats": stats}
