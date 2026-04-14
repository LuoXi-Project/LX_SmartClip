import os
import uuid
import shutil
import logging
import subprocess
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from app.models.videos import ImportVideoByUrlPayload, ReencodeVideoPayload, UpdateVideoPayload

from app.db.database import get_db_conn
from app.utils.bin_paths import ffmpeg_bin
from app.utils.material_media_names import REENCODED_VIDEO_NAME, source_video_basename
from app.utils.paths import ensure_storage_subpath, resolve_stored_path, to_stored_path
from app.utils.video_thumbnail import generate_thumbnail
from app.utils.yt_dlp_downloader import YtDlpDownloadError, download_video_with_yt_dlp

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["videos"])

ALLOWED_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
    "video/webm",
    "video/mpeg",
}


def _infer_highlight_score(text: str | None) -> float:
    """
    从 clips.vlm_description 中粗略推断高光得分。

    说明：
        - 当前不增加数据库字段，仅在读取时做轻量解析。
        - 若后续增加结构化高光字段，可替换为直接读取字段。
    """
    if not text:
        return 0.0

    t = text.strip()
    if not t:
        return 0.0

    try:
        import re

        m = re.search(r"高光评级[:：]\s*(高光|一般|非高光)", t)
        if m:
            lvl = m.group(1)
            if "高光" == lvl:
                return 1.0
            if "一般" in lvl:
                return 0.6
            if "非高光" in lvl:
                return 0.2
    except Exception:
        pass

    keywords = ("高光", "精彩", "亮点", "高潮", "最有价值", "推荐保留")
    hit = sum(1 for k in keywords if k in t)
    if hit >= 2:
        return 0.8
    if hit == 1:
        return 0.6

    return 0.0


@router.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{file.content_type}",
        )

    video_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename or "")[1] or ".mp4"
    video_dir = ensure_storage_subpath(video_id, "videos")
    save_path = os.path.join(video_dir, source_video_basename(ext))

    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    upload_at = datetime.utcnow().isoformat()
    thumbnail_path = generate_thumbnail(save_path, video_id)

    db = await get_db_conn()
    try:
        await db.execute(
            """
            INSERT INTO videos (id, name, file_path, thumbnail_path, duration, total_clips, split_mode, status, upload_at)
            VALUES (?, ?, ?, ?, NULL, 0, 'scene', 'pending', ?)
            """,
            (video_id, file.filename, to_stored_path(save_path), to_stored_path(thumbnail_path), upload_at),
        )
        await db.commit()
    finally:
        await db.close()

    return {
        "id": video_id,
        "name": file.filename,
        "upload_at": upload_at,
        "thumbnail_path": thumbnail_path,
    }


@router.post("/import-url")
async def import_video_by_url(payload: ImportVideoByUrlPayload):
    video_id = str(uuid.uuid4())
    name = (payload.title or "").strip() or f"yt_import_{video_id[:8]}"
    try:
        save_path = download_video_with_yt_dlp(
            url=payload.url.strip(),
            output_dir=ensure_storage_subpath(video_id, "videos"),
            file_stem="source",
            resolution=payload.resolution,
            fps_limit=payload.fps_limit,
            prefer_mp4=payload.prefer_mp4,
        )
    except YtDlpDownloadError as exc:
        detail = str(exc)
        logger.error(f"下载视频失败: {detail}")
        status = 501 if "未检测到 yt-dlp" in detail else 502
        raise HTTPException(status_code=status, detail=detail) from exc

    upload_at = datetime.utcnow().isoformat()
    thumbnail_path = generate_thumbnail(save_path, video_id)

    db = await get_db_conn()
    try:
        await db.execute(
            """
            INSERT INTO videos (id, name, file_path, thumbnail_path, duration, total_clips, split_mode, status, upload_at)
            VALUES (?, ?, ?, ?, NULL, 0, 'scene', 'pending', ?)
            """,
            (video_id, name, to_stored_path(save_path), to_stored_path(thumbnail_path), upload_at),
        )
        await db.commit()
    finally:
        await db.close()

    return {
        "id": video_id,
        "name": name,
        "upload_at": upload_at,
        "thumbnail_path": thumbnail_path,
    }


@router.post("/{video_id}/reencode")
async def reencode_video(video_id: str, payload: ReencodeVideoPayload):
    db = await get_db_conn()
    old_path = ""
    old_thumb = None
    old_name = ""
    try:
        cursor = await db.execute(
            "SELECT id, name, file_path, thumbnail_path FROM videos WHERE id = ?", (video_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")
        old_path = resolve_stored_path(row["file_path"])
        old_thumb = resolve_stored_path(row["thumbnail_path"]) if row["thumbnail_path"] else None
        old_name = row["name"]
    finally:
        await db.close()

    if not old_path or not os.path.exists(old_path):
        raise HTTPException(status_code=404, detail="源视频文件不存在")

    output_path = os.path.join(ensure_storage_subpath(video_id, "videos"), REENCODED_VIDEO_NAME)
    vf_parts = []
    if payload.max_height:
        # 用 force_original_aspect_ratio=decrease 避免 min(...) 里的逗号被当作滤镜分隔符
        # force_divisible_by=2: 保证输出宽高为偶数，兼容 libx264 编码约束
        vf_parts.append(
            f"scale=-2:{payload.max_height}:force_original_aspect_ratio=decrease:force_divisible_by=2"
        )
    if payload.fps:
        vf_parts.append(f"fps={payload.fps}")
    vf_parts.append("format=yuv420p")
    vf_expr = ",".join(vf_parts)

    cmd = [
        ffmpeg_bin(),
        "-y",
        "-i",
        old_path,
        "-vf",
        vf_expr,
        "-c:v",
        payload.vcodec,
        "-preset",
        payload.preset,
        "-crf",
        str(payload.crf),
        "-c:a",
        payload.acodec,
        "-b:a",
        f"{payload.audio_bitrate_k}k",
        "-movflags",
        "+faststart",
        output_path,
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60 * 30,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=501, detail="未检测到 ffmpeg，请先安装 ffmpeg") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="重编码超时，请尝试更快预设或更低分辨率") from exc

    if result.returncode != 0 or not os.path.exists(output_path):
        stderr_text = (result.stderr or "").strip()
        detail = stderr_text[-4000:] if stderr_text else "ffmpeg 重编码失败"
        logger.error(
            "视频重编码失败: video_id=%s returncode=%s cmd=%s stderr_tail=%s",
            video_id,
            result.returncode,
            " ".join(cmd),
            detail,
        )
        raise HTTPException(status_code=502, detail=detail)

    thumbnail_path = generate_thumbnail(output_path, video_id)

    db = await get_db_conn()
    try:
        await db.execute(
            "UPDATE videos SET file_path = ?, thumbnail_path = ? WHERE id = ?",
            (to_stored_path(output_path), to_stored_path(thumbnail_path), video_id),
        )
        await db.commit()
    finally:
        await db.close()

    if old_path != output_path and os.path.exists(old_path):
        try:
            os.remove(old_path)
        except Exception:
            pass
    if old_thumb and thumbnail_path and old_thumb != thumbnail_path and os.path.exists(old_thumb):
        try:
            os.remove(old_thumb)
        except Exception:
            pass

    return {
        "id": video_id,
        "name": old_name,
        "file_path": output_path,
        "thumbnail_path": thumbnail_path,
    }


@router.get("")
async def list_videos(
    q: str = "",
    status: str = "",
    sort: str = "upload_at_desc",
    page: int = 1,
    page_size: int = 12,
):
    """List videos with search, status filter, sort and pagination.

    Params:
    - q: name substring search (case-insensitive)
    - status: pending | processing | done | error | "" (all)
    - sort: upload_at_desc | upload_at_asc | name_asc | name_desc
    - page: 1-based
    - page_size: 1-100
    """
    page = max(1, page)
    page_size = max(1, min(100, page_size))

    conditions = []
    params: list = []

    if q.strip():
        conditions.append("LOWER(name) LIKE ?")
        params.append(f"%{q.strip().lower()}%")

    if status.strip() in ("pending", "processing", "done", "error"):
        conditions.append("status = ?")
        params.append(status.strip())

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sort_map = {
        "upload_at_desc": "upload_at DESC",
        "upload_at_asc": "upload_at ASC",
        "name_asc": "name ASC",
        "name_desc": "name DESC",
    }
    order_clause = sort_map.get(sort, "upload_at DESC")

    db = await get_db_conn()
    try:
        # Total matching count
        count_cursor = await db.execute(
            f"SELECT COUNT(*) FROM videos {where_clause}", params
        )
        total = (await count_cursor.fetchone())[0]

        # Paginated rows
        offset = (page - 1) * page_size
        cursor = await db.execute(
            f"SELECT id, name, file_path, thumbnail_path, duration, total_clips, split_mode, status, upload_at "
            f"FROM videos {where_clause} ORDER BY {order_clause} LIMIT ? OFFSET ?",
            params + [page_size, offset],
        )
        rows = await cursor.fetchall()
        items = [
            {
                "id": row["id"],
                "name": row["name"],
                "file_path": row["file_path"],
                "thumbnail_path": row["thumbnail_path"],
                "duration": row["duration"],
                "total_clips": row["total_clips"],
                "split_mode": row["split_mode"],
                "status": row["status"],
                "upload_at": row["upload_at"],
            }
            for row in rows
        ]
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, -(-total // page_size)),
        }
    finally:
        await db.close()


@router.get("/{video_id}/thumbnail")
async def get_thumbnail(video_id: str):
    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT thumbnail_path FROM videos WHERE id = ?", (video_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            logger.error(f"视频封面图不存在: {video_id}")
            raise HTTPException(status_code=404, detail="视频不存在")
        thumb_path = resolve_stored_path(row["thumbnail_path"]) if row["thumbnail_path"] else ""
    finally:
        await db.close()

    if not thumb_path or not os.path.exists(thumb_path):
        logger.error(f"视频封面图不存在: {video_id}")
        raise HTTPException(status_code=404, detail="封面图不存在")

    return FileResponse(thumb_path, media_type="image/jpeg")


@router.get("/{video_id}/stream")
async def stream_video(video_id: str):
    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT file_path FROM videos WHERE id = ?", (video_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            logger.error(f"视频文件不存在: {video_id}")
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")
        file_path = resolve_stored_path(row["file_path"])
    finally:
        await db.close()

    if not file_path or not os.path.exists(file_path):
        logger.error(f"视频文件不存在: {video_id}")
        raise HTTPException(status_code=404, detail="视频文件不存在")

    ext = os.path.splitext(file_path)[1].lower()
    _mime_map = {
        ".mp4": "video/mp4",
        ".m4v": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
        ".mpeg": "video/mpeg",
        ".mpg": "video/mpeg",
    }
    media_type = _mime_map.get(ext, "video/mp4")
    return FileResponse(file_path, media_type=media_type, filename=os.path.basename(file_path))


@router.patch("/{video_id}")
async def update_video(video_id: str, payload: UpdateVideoPayload):
    name = payload.name.strip() if isinstance(payload.name, str) else None
    status = payload.status
    if not name and not status:
        raise HTTPException(status_code=400, detail="至少提供一个可更新字段（name/status）")
    if payload.name is not None and not name:
        logger.error(f"视频名称不能为空: {video_id}")
        raise HTTPException(status_code=400, detail="名称不能为空")

    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT id FROM videos WHERE id = ?", (video_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            logger.error(f"视频不存在: {video_id}")
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")
        updates = []
        params = []
        if name:
            updates.append("name = ?")
            params.append(name)
        if status:
            updates.append("status = ?")
            params.append(status)
        params.append(video_id)
        await db.execute(f"UPDATE videos SET {', '.join(updates)} WHERE id = ?", params)
        await db.commit()
    finally:
        await db.close()

    return {"id": video_id, "name": name, "status": status}


@router.delete("/{video_id}")
async def delete_video(video_id: str):
    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT id, file_path, thumbnail_path FROM videos WHERE id = ?", (video_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            logger.error(f"视频不存在: {video_id}")
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")

        file_path = resolve_stored_path(row["file_path"])
        thumbnail_path = resolve_stored_path(row["thumbnail_path"]) if row["thumbnail_path"] else ""

        await db.execute("DELETE FROM clips WHERE video_id = ?", (video_id,))
        await db.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        await db.commit()
    finally:
        await db.close()

    material_root = ensure_storage_subpath(video_id)
    if os.path.isdir(material_root):
        try:
            shutil.rmtree(material_root)
        except Exception:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass
            if thumbnail_path and os.path.exists(thumbnail_path):
                try:
                    os.remove(thumbnail_path)
                except Exception:
                    pass
    else:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        if thumbnail_path and os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)

    return {"id": video_id, "deleted": True}


@router.get("/{video_id}/highlights")
async def list_video_highlights(
    video_id: str,
    limit: int = 10,
    min_score: float = 0.3,
):
    """
    返回指定素材内的高光片段列表（按推测的高光得分排序）。

    说明：
        - 目前通过解析 clips.vlm_description 中的“高光评级”或关键词粗略推断 highlight_score。
        - 后续如有结构化高光字段，可直接改为从表字段读取。
    """
    limit = max(1, min(100, int(limit)))
    try:
        min_score = float(min_score)
    except Exception:
        min_score = 0.3

    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT id, start_time, end_time, duration, vlm_description "
            "FROM clips WHERE video_id = ? ORDER BY start_time",
            (video_id,),
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    segments = []
    for row in rows:
        score = _infer_highlight_score(row["vlm_description"])
        if score < min_score:
            continue
        segments.append(
            {
                "clip_id": row["id"],
                "start_time": row["start_time"],
                "end_time": row["end_time"],
                "duration": row["duration"],
                "highlight_score": score,
                "summary_text": row["vlm_description"],
            }
        )

    segments.sort(key=lambda s: s["highlight_score"], reverse=True)
    return {
        "video_id": video_id,
        "total": len(segments),
        "segments": segments[:limit],
    }
