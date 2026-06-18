"""通用异步任务的持久化层（async_jobs 表 + CRUD）。

镜像 app/api/process_db.py 中 process_tasks 的设计，但 kind/ref 泛化以承载
reencode / burn / export_original / realize / jianying / transcribe / slice 等
任意后台任务。独立成表，不影响正在运行的视频处理管线。
"""

import json
import logging
import uuid
from datetime import datetime

from app.db.database import get_db_conn

logger = logging.getLogger(__name__)

CREATE_ASYNC_JOBS = """
CREATE TABLE IF NOT EXISTS async_jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    ref_type TEXT,
    ref_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    current_step TEXT,
    progress_json TEXT,
    metrics_json TEXT,
    result_json TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
"""


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def _load_json(s):
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


async def get_job(job_id: str):
    db = await get_db_conn()
    try:
        cursor = await db.execute("SELECT * FROM async_jobs WHERE id = ?", (job_id,))
        return await cursor.fetchone()
    finally:
        await db.close()


def row_to_payload(row) -> dict:
    if not row:
        return {}
    return {
        "id": row["id"],
        "kind": row["kind"],
        "ref_type": row["ref_type"],
        "ref_id": row["ref_id"],
        "status": row["status"],
        "current_step": row["current_step"],
        "steps": _load_json(row["progress_json"]) or {},
        "metrics": _load_json(row["metrics_json"]),
        "result": _load_json(row["result_json"]),
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "finished_at": row["finished_at"],
    }


async def create_job(
    kind: str,
    ref_type: str | None = None,
    ref_id: str | None = None,
    initial_step: str | None = None,
) -> dict:
    job_id = str(uuid.uuid4())
    now = now_iso()
    db = await get_db_conn()
    try:
        await db.execute(
            "INSERT INTO async_jobs (id, kind, ref_type, ref_id, status, current_step, progress_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, 'running', ?, '{}', ?, ?)",
            (job_id, kind, ref_type, ref_id, initial_step, now, now),
        )
        await db.commit()
    finally:
        await db.close()
    return row_to_payload(await get_job(job_id))


async def update_job_progress(job_id: str, step: str, status: str, message: str, detail: dict | None):
    row = await get_job(job_id)
    if not row:
        return
    try:
        progress = json.loads(row["progress_json"]) if row["progress_json"] else {}
    except Exception:
        progress = {}
    progress[step] = {"status": status, "message": message, "detail": detail or {}}
    metrics = None
    if isinstance(detail, dict) and isinstance(detail.get("metrics"), dict):
        metrics = detail["metrics"]
    now = now_iso()
    db = await get_db_conn()
    try:
        await db.execute(
            "UPDATE async_jobs SET current_step = ?, progress_json = ?, "
            "metrics_json = COALESCE(?, metrics_json), updated_at = ? WHERE id = ?",
            (
                step,
                json.dumps(progress, ensure_ascii=False),
                json.dumps(metrics, ensure_ascii=False) if metrics else None,
                now,
                job_id,
            ),
        )
        await db.commit()
    finally:
        await db.close()


async def update_job_status(
    job_id: str,
    status: str,
    error_message: str | None = None,
    result=None,
):
    now = now_iso()
    finished = now if status in ("done", "error", "cancelled") else None
    db = await get_db_conn()
    try:
        await db.execute(
            "UPDATE async_jobs SET status = ?, error_message = ?, "
            "result_json = COALESCE(?, result_json), updated_at = ?, "
            "finished_at = COALESCE(?, finished_at) WHERE id = ?",
            (
                status,
                error_message,
                json.dumps(result, ensure_ascii=False) if result is not None else None,
                now,
                finished,
                job_id,
            ),
        )
        await db.commit()
    finally:
        await db.close()
