import os
import uuid
import shutil
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, HTTPException

from app.db.database import get_db_conn

router = APIRouter(prefix="/api/videos", tags=["videos"])

STORAGE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "storage", "videos")
)
os.makedirs(STORAGE_DIR, exist_ok=True)

ALLOWED_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
    "video/webm",
    "video/mpeg",
}


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

    db = await get_db_conn()
    try:
        await db.execute(
            """
            INSERT INTO videos (id, name, file_path, duration, total_clips, split_mode, status, upload_at)
            VALUES (?, ?, ?, NULL, 0, 'scene', 'pending', ?)
            """,
            (video_id, file.filename, save_path, upload_at),
        )
        await db.commit()
    finally:
        await db.close()

    return {"id": video_id, "name": file.filename, "upload_at": upload_at}


@router.get("")
async def list_videos():
    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT id, name, file_path, duration, total_clips, split_mode, status, upload_at "
            "FROM videos ORDER BY upload_at DESC"
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "file_path": row["file_path"],
                "duration": row["duration"],
                "total_clips": row["total_clips"],
                "split_mode": row["split_mode"],
                "status": row["status"],
                "upload_at": row["upload_at"],
            }
            for row in rows
        ]
    finally:
        await db.close()


@router.delete("/{video_id}")
async def delete_video(video_id: str):
    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT id, file_path FROM videos WHERE id = ?", (video_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")

        file_path = row["file_path"]

        await db.execute("DELETE FROM clips WHERE video_id = ?", (video_id,))
        await db.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        await db.commit()
    finally:
        await db.close()

    if file_path and os.path.exists(file_path):
        os.remove(file_path)

    return {"id": video_id, "deleted": True}