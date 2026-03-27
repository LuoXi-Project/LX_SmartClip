import os
import uuid
import shutil
import subprocess
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

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
                timeout=30,
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
