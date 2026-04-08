import json
import logging
import uuid
from fastapi import WebSocket
from app.db.database import get_db_conn
from .process_shared import now_iso, _task_subscribers

logger = logging.getLogger(__name__)


async def read_config(db, key: str, default: str = "") -> str:
    cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row["value"] if row else default


async def set_video_status(video_id: str, status: str):
    db = await get_db_conn()
    try:
        await db.execute("UPDATE videos SET status = ? WHERE id = ?", (status, video_id))
        await db.commit()
    finally:
        await db.close()


async def get_video(video_id: str):
    db = await get_db_conn()
    try:
        cursor = await db.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
        return await cursor.fetchone()
    finally:
        await db.close()


async def get_clips(video_id: str):
    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT id, clip_path, asr_text, vlm_description FROM clips "
            "WHERE video_id = ? ORDER BY start_time",
            (video_id,),
        )
        return await cursor.fetchall()
    finally:
        await db.close()


async def get_task(task_id: str):
    db = await get_db_conn()
    try:
        cursor = await db.execute("SELECT * FROM process_tasks WHERE id = ?", (task_id,))
        return await cursor.fetchone()
    finally:
        await db.close()


async def get_running_task_for_video(video_id: str):
    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT * FROM process_tasks WHERE video_id = ? AND status = 'running' ORDER BY created_at DESC LIMIT 1",
            (video_id,),
        )
        return await cursor.fetchone()
    finally:
        await db.close()


def row_to_task_payload(row) -> dict:
    if not row:
        return {}
    try:
        steps = json.loads(row["progress_json"]) if row["progress_json"] else {}
    except Exception:
        steps = {}
    try:
        metrics = json.loads(row["metrics_json"]) if row["metrics_json"] else None
    except Exception:
        metrics = None
    return {
        "id": row["id"],
        "video_id": row["video_id"],
        "status": row["status"],
        "current_step": row["current_step"],
        "steps": steps,
        "metrics": metrics,
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "finished_at": row["finished_at"],
    }


async def create_task(video_id: str) -> dict:
    running = await get_running_task_for_video(video_id)
    if running:
        return row_to_task_payload(running)
    task_id = str(uuid.uuid4())
    now = now_iso()
    db = await get_db_conn()
    try:
        await db.execute(
            "INSERT INTO process_tasks (id, video_id, status, progress_json, created_at, updated_at) VALUES (?, ?, 'running', ?, ?, ?)",
            (task_id, video_id, "{}", now, now),
        )
        await db.commit()
    finally:
        await db.close()
    created = await get_task(task_id)
    return row_to_task_payload(created)


async def update_task_status(task_id: str, status: str, error_message: str | None = None):
    now = now_iso()
    finished_at = now if status in ("done", "error", "cancelled") else None
    db = await get_db_conn()
    try:
        await db.execute(
            "UPDATE process_tasks SET status = ?, error_message = ?, updated_at = ?, finished_at = COALESCE(?, finished_at) WHERE id = ?",
            (status, error_message, now, finished_at, task_id),
        )
        await db.commit()
    finally:
        await db.close()


async def update_task_from_progress(task_id: str, step: str, status: str, message: str, detail: dict):
    row = await get_task(task_id)
    if not row:
        return
    try:
        progress = json.loads(row["progress_json"]) if row["progress_json"] else {}
    except Exception:
        progress = {}
    progress[step] = {
        "status": status,
        "message": message,
        "detail": detail or {},
    }
    metrics = None
    if isinstance(detail, dict):
        m = detail.get("metrics")
        if isinstance(m, dict):
            metrics = m
    now = now_iso()
    db = await get_db_conn()
    try:
        await db.execute(
            "UPDATE process_tasks SET current_step = ?, progress_json = ?, metrics_json = COALESCE(?, metrics_json), updated_at = ? WHERE id = ?",
            (step, json.dumps(progress, ensure_ascii=False), json.dumps(metrics, ensure_ascii=False) if metrics else None, now, task_id),
        )
        await db.commit()
    finally:
        await db.close()


async def broadcast_task_message(task_id: str, payload: dict):
    subscribers = _task_subscribers.get(task_id)
    if not subscribers:
        return
    stale: list[WebSocket] = []
    for ws in subscribers:
        try:
            await ws.send_json(payload)
        except Exception:
            stale.append(ws)
    for ws in stale:
        subscribers.discard(ws)
    if not subscribers:
        _task_subscribers.pop(task_id, None)


class ProgressReporter:
    """向 WebSocket 推送进度；无 WebSocket 时仅记录日志"""

    def __init__(self, ws: WebSocket = None, task_id: str | None = None):
        self.ws = ws
        self.task_id = task_id

    async def send(self, step: str, status: str, message: str, detail: dict = None):
        payload = {
            "step": step,
            "status": status,
            "message": message,
            "detail": detail or {},
        }
        logger.info("[%s] %s: %s", step, status, message)
        if self.task_id:
            await update_task_from_progress(
                self.task_id,
                step=step,
                status=status,
                message=message,
                detail=payload["detail"],
            )
            await broadcast_task_message(self.task_id, payload)
        if self.ws:
            try:
                await self.ws.send_json(payload)
            except Exception:
                pass


async def update_clip_field(clip_id: str, field: str, value: str):
    db = await get_db_conn()
    try:
        await db.execute(f"UPDATE clips SET {field} = ? WHERE id = ?", (value, clip_id))
        await db.commit()
    finally:
        await db.close()


async def update_clip_asr(clip_id: str, asr_text: str, asr_segments_json: str | None):
    db = await get_db_conn()
    try:
        await db.execute(
            "UPDATE clips SET asr_text = ?, asr_segments = ? WHERE id = ?",
            (asr_text, asr_segments_json, clip_id),
        )
        await db.commit()
    finally:
        await db.close()


async def clear_clips_for_video(video_id: str):
    db = await get_db_conn()
    try:
        await db.execute("DELETE FROM clips WHERE video_id = ?", (video_id,))
        await db.execute("UPDATE videos SET total_clips = 0 WHERE id = ?", (video_id,))
        await db.commit()
    finally:
        await db.close()


async def insert_clip_to_db(video_id: str, clip) -> str:
    clip_id = str(uuid.uuid4())
    db = await get_db_conn()
    try:
        await db.execute(
            "INSERT INTO clips (id, video_id, clip_path, start_time, end_time, duration) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                clip_id,
                video_id,
                clip.clip_path,
                float(clip.start_time),
                float(clip.end_time),
                float(clip.duration),
            ),
        )
        await db.execute(
            "UPDATE videos SET total_clips = (SELECT COUNT(*) FROM clips WHERE video_id = ?) WHERE id = ?",
            (video_id, video_id),
        )
        await db.commit()
        return clip_id
    finally:
        await db.close()
