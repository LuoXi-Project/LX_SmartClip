import json
import logging
import uuid
from datetime import datetime, timezone
from fastapi import WebSocket
from app.db.database import get_db_conn
from app.utils.paths import resolve_stored_path, to_stored_path
from .process_shared import STEP_LABELS, now_iso, _task_subscribers
from app.utils.logging_utils import stage_log

logger = logging.getLogger(__name__)

STALE_RUNNING_TASK_SEC = 10 * 60


def _parse_iso_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        v = str(s).replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


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
        row = await cursor.fetchone()
        if not row:
            return row
        out = dict(row)
        if out.get("file_path"):
            try:
                out["file_path"] = resolve_stored_path(str(out["file_path"]))
            except Exception:
                pass
        return out
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
        rows = await cursor.fetchall()
        out = [dict(r) for r in rows]
        for r in out:
            if r.get("clip_path"):
                try:
                    r["clip_path"] = resolve_stored_path(str(r["clip_path"]))
                except Exception:
                    pass
        return out
    finally:
        await db.close()


async def get_clips_by_ids_for_video(video_id: str, clip_ids: list[str]):
    """按 id 列表返回属于该视频的切片行（顺序按 start_time），用于 clip_ids 归属校验。"""
    if not clip_ids:
        return []
    placeholders = ",".join("?" * len(clip_ids))
    db = await get_db_conn()
    try:
        cursor = await db.execute(
            f"SELECT id, clip_path, asr_text, vlm_description FROM clips "
            f"WHERE video_id = ? AND id IN ({placeholders}) ORDER BY start_time",
            (video_id, *clip_ids),
        )
        rows = await cursor.fetchall()
        out = [dict(r) for r in rows]
        for r in out:
            if r.get("clip_path"):
                try:
                    r["clip_path"] = resolve_stored_path(str(r["clip_path"]))
                except Exception:
                    pass
        return out
    finally:
        await db.close()


async def get_task(task_id: str):
    db = await get_db_conn()
    try:
        cursor = await db.execute("SELECT * FROM process_tasks WHERE id = ?", (task_id,))
        return await cursor.fetchone()
    finally:
        await db.close()


def _task_has_live_worker(task_id: str) -> bool:
    from .process_shared import _job_tasks

    t = _job_tasks.get(task_id)
    return t is not None and not t.done()


async def reconcile_orphan_task(row) -> dict:
    """进程内已无运行协程但库中仍为 running/pending 时，与视频状态对齐，避免前端永久「处理中」。"""
    if not row:
        return {}
    status = row["status"]
    if status not in ("running", "pending"):
        return row_to_task_payload(row)

    task_id = row["id"]
    if _task_has_live_worker(task_id):
        return row_to_task_payload(row)

    video = await get_video(row["video_id"])
    video_status = (video or {}).get("status") if video else None

    if video_status == "done":
        await update_task_status(task_id, "done")
        err = None
    elif video_status == "error":
        await update_task_status(task_id, "error", error_message="RECONCILED_FROM_VIDEO")
        err = "RECONCILED_FROM_VIDEO"
    else:
        await update_task_status(task_id, "cancelled", error_message="ORPHAN_TASK_NO_WORKER")
        err = "ORPHAN_TASK_NO_WORKER"
        if video_status == "processing":
            await set_video_status(row["video_id"], "pending")
    logger.warning(
        "已对齐孤儿任务: task_id=%s video_id=%s video_status=%s -> task reconciled (%s)",
        task_id,
        row["video_id"],
        video_status,
        err or "done",
    )
    refreshed = await get_task(task_id)
    return row_to_task_payload(refreshed)


async def reconcile_all_orphan_tasks_on_startup() -> int:
    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT * FROM process_tasks WHERE status IN ('running', 'pending')",
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()
    n = 0
    for row in rows:
        before = row["status"]
        payload = await reconcile_orphan_task(row)
        if payload.get("status") != before:
            n += 1
    if n:
        logger.warning("启动时已对齐 %d 个孤儿 process_tasks", n)
    return n


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
        reconciled = await reconcile_orphan_task(running)
        if reconciled.get("status") in ("running", "pending"):
            try:
                updated_raw = running["updated_at"]
            except Exception:
                updated_raw = None
            updated_dt = _parse_iso_dt(updated_raw)
            if updated_dt is not None:
                age_sec = (datetime.now(timezone.utc) - updated_dt).total_seconds()
                if age_sec > STALE_RUNNING_TASK_SEC:
                    now = now_iso()
                    db = await get_db_conn()
                    try:
                        await db.execute(
                            "UPDATE process_tasks SET status = 'error', error_message = ?, updated_at = ?, finished_at = COALESCE(?, finished_at) WHERE id = ?",
                            ("STALE_TASK_REPLACED", now, now, running["id"]),
                        )
                        await db.commit()
                    finally:
                        await db.close()
                    logger.warning(
                        "检测到僵尸任务并替换: video_id=%s old_task_id=%s age_sec=%.0f",
                        video_id,
                        running["id"],
                        age_sec,
                    )
                else:
                    return reconciled
            else:
                return reconciled
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
    """向 WebSocket 推送进度；无 WebSocket 时仅记录日志。

    当 job_id 不为空时，同步将进度写入 async_jobs 表，使 TaskHub 可实时显示。
    """

    def __init__(self, ws: WebSocket = None, task_id: str | None = None, job_id: str | None = None):
        self.ws = ws
        self.task_id = task_id
        self.job_id = job_id

    async def send(self, step: str, status: str, message: str, detail: dict = None):
        payload = {
            "step": step,
            "status": status,
            "message": message,
            "detail": detail or {},
        }
        step_label = STEP_LABELS.get(step, step)
        stage_log("预处理", f"{step_label} — {message}", status=status)
        logger.info("[%s] %s: %s", step, status, message)
        if self.task_id:
            try:
                await update_task_from_progress(
                    self.task_id,
                    step=step,
                    status=status,
                    message=message,
                    detail=payload["detail"],
                )
                await broadcast_task_message(self.task_id, payload)
            except Exception:
                logger.exception("ProgressReporter: 写库/广播进度失败，跳过以免影响流水线")
        if self.job_id:
            try:
                from app.jobs.store import update_job_progress as _async_update
                from app.jobs.runtime import broadcast as _job_broadcast
                await _async_update(self.job_id, step=step, status=status, message=message, detail=payload["detail"])
                await _job_broadcast(self.job_id, payload)
            except Exception:
                logger.exception("ProgressReporter: 同步 async_job 进度/广播失败，跳过")
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
        # 先取出待删 clip_id，用于稍后清理向量库（SQL 删除后就查不到了）
        rows = (
            await db.execute("SELECT id FROM clips WHERE video_id = ?", (video_id,))
        ).fetchall()
        clip_ids = [r["id"] for r in rows] if rows else []
        await db.execute("DELETE FROM clips WHERE video_id = ?", (video_id,))
        await db.execute("UPDATE videos SET total_clips = 0 WHERE id = ?", (video_id,))
        await db.commit()
    finally:
        await db.close()

    # 同步清理向量库，避免残留孤儿；放线程池避免阻塞事件循环；软失败不阻断主流程
    if clip_ids:
        try:
            from app.core.vector_db.cleanup import purge_clip_vectors
            from app.core.blocking_pool import run_heavy
            removed = await run_heavy(purge_clip_vectors, clip_ids)
            if removed:
                logger.info("清理 video=%s 的 %d 个 clip 向量，删除 %d 个", video_id, len(clip_ids), removed)
        except Exception as e:
            logger.warning("清理 video=%s 向量失败（已忽略）: %s", video_id, e)


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
                to_stored_path(clip.clip_path),
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
