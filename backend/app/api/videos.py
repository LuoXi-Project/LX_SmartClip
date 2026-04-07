import os
import uuid
import shutil
import subprocess
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from app.models.videos import RenamePayload

from app.db.database import get_db_conn

router = APIRouter(prefix="/api/videos", tags=["videos"])

STORAGE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "storage", "videos")
)
THUMBNAIL_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "storage", "thumbnails")
)
os.makedirs(STORAGE_DIR, exist_ok=True)
os.makedirs(THUMBNAIL_DIR, exist_ok=True)

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


def generate_thumbnail(video_path: str, video_id: str) -> str | None:
    """使用 ffmpeg 提取视频封面帧，返回封面图路径，失败返回 None。"""
    out_path = os.path.join(THUMBNAIL_DIR, f"{video_id}.jpg")
    for ss in ("00:00:01", "00:00:00"):
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", ss,
                    "-i", video_path,
                    "-frames:v", "1",
                    "-vf", "scale=320:-1",
                    "-q:v", "5",
                    out_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=300,
            )
            if result.returncode == 0 and os.path.exists(out_path):
                return out_path
        except Exception:
            pass
    return None


@router.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型：{file.content_type}",
        )

    video_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename or "")[1] or ".mp4"
    save_path = os.path.join(STORAGE_DIR, f"{video_id}{ext}")

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
            (video_id, file.filename, save_path, thumbnail_path, upload_at),
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
            raise HTTPException(status_code=404, detail="视频不存在")
        thumb_path = row["thumbnail_path"]
    finally:
        await db.close()

    if not thumb_path or not os.path.exists(thumb_path):
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
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")
        file_path = row["file_path"]
    finally:
        await db.close()

    if not file_path or not os.path.exists(file_path):
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
async def rename_video(video_id: str, payload: RenamePayload):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="名称不能为空")

    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT id FROM videos WHERE id = ?", (video_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")

        await db.execute(
            "UPDATE videos SET name = ? WHERE id = ?", (name, video_id)
        )
        await db.commit()
    finally:
        await db.close()

    return {"id": video_id, "name": name}


@router.delete("/{video_id}")
async def delete_video(video_id: str):
    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT id, file_path, thumbnail_path FROM videos WHERE id = ?", (video_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")

        file_path = row["file_path"]
        thumbnail_path = row["thumbnail_path"]

        await db.execute("DELETE FROM clips WHERE video_id = ?", (video_id,))
        await db.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        await db.commit()
    finally:
        await db.close()

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
