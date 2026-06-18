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
    ref_name TEXT,
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
        "video_name": row["ref_name"] if "ref_name" in row.keys() else None,
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
    ref_name: str | None = None,
    initial_status: str = "running",
) -> dict:
    job_id = str(uuid.uuid4())
    now = now_iso()
    db = await get_db_conn()
    try:
        await db.execute(
            "INSERT INTO async_jobs (id, kind, ref_type, ref_id, ref_name, status, current_step, progress_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)",
            (job_id, kind, ref_type, ref_id, ref_name, initial_status, initial_step, now, now),
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


async def delete_job(job_id: str) -> bool:
    """删除 async_jobs 行（用于「删除任务」）。返回是否删除了一行。"""
    db = await get_db_conn()
    try:
        cur = await db.execute("DELETE FROM async_jobs WHERE id = ?", (job_id,))
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def list_jobs(
    kind: str | None = None,
    active_only: bool = False,
    ref_id: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """按 created_at 升序列出 job（FIFO=排队顺序）。active_only 只返回 pending/running。"""
    clauses: list[str] = []
    params: list = []
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if active_only:
        clauses.append("status IN ('pending', 'running')")
    if ref_id:
        clauses.append("ref_id = ?")
        params.append(ref_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(int(limit))
    db = await get_db_conn()
    try:
        cur = await db.execute(
            f"SELECT * FROM async_jobs{where} ORDER BY created_at ASC LIMIT ?",
            params,
        )
        rows = await cur.fetchall()
        return [row_to_payload(r) for r in rows]
    finally:
        await db.close()


async def reconcile_process_jobs_on_startup() -> int:
    """进程重启后，队列 worker 已死：把卡在 pending/running 的 process job 按视频状态对齐。

    镜像 process_db.reconcile_all_orphan_tasks_on_startup 的语义，但作用于 async_jobs，
    避免前端 TaskHub/ProcessPage 永远显示「处理中」。
    """
    rows = await list_jobs(kind="process", active_only=True)
    if not rows:
        return 0
    # 延迟导入避免循环依赖
    from app.api.process_db import get_video, set_video_status

    n = 0
    for job in rows:
        job_id = job["id"]
        video_id = job.get("ref_id") or ""
        video = await get_video(video_id) if video_id else None
        video_status = (video or {}).get("status") if video else None
        if video_status == "done":
            await update_job_status(job_id, "done", result={"video_id": video_id})
        elif video_status == "error":
            await update_job_status(job_id, "error", error_message="RECONCILED_FROM_VIDEO")
        else:
            await update_job_status(job_id, "cancelled", error_message="ORPHAN_JOB_NO_WORKER")
            if video_status == "processing":
                await set_video_status(video_id, "pending")
        n += 1
    if n:
        logger.warning("启动时已对齐 %d 个孤儿 process async_jobs", n)
    return n
