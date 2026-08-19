"""workflows / workflow_runs 表访问：定义 CRUD、运行记录、内置同步、启动对账。

DDL 由 init_db.py 导入执行（与 jobs.store 的 CREATE_ASYNC_JOBS 同一先例）。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from app.db.database import get_db_conn

from .schema import WorkflowDef

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.utcnow().isoformat()


CREATE_WORKFLOWS = """
CREATE TABLE IF NOT EXISTS workflows (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT DEFAULT '通用',
    definition_json TEXT NOT NULL,
    is_builtin INTEGER DEFAULT 0,
    version INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

CREATE_WORKFLOW_RUNS = """
CREATE TABLE IF NOT EXISTS workflow_runs (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    workflow_name TEXT,
    job_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    inputs_json TEXT,
    def_snapshot_json TEXT,
    context_json TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
"""


def _loads(s, default=None):
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:
        return default


# ── 定义（workflows 表）───────────────────────────────────────────────────

def _def_row_to_payload(row) -> dict:
    definition = _loads(row["definition_json"], {}) or {}
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"] or "",
        "category": row["category"] or "通用",
        "is_builtin": bool(row["is_builtin"]),
        "version": int(row["version"] or 1),
        "params": definition.get("params") or [],
        "steps": definition.get("steps") or [],
        "definition": definition,
        "updated_at": row["updated_at"],
        "created_at": row["created_at"],
    }


async def list_definitions() -> list[dict]:
    db = await get_db_conn()
    try:
        cur = await db.execute(
            "SELECT * FROM workflows ORDER BY is_builtin DESC, updated_at DESC"
        )
        rows = await cur.fetchall()
        return [_def_row_to_payload(r) for r in rows]
    finally:
        await db.close()


async def get_definition(workflow_id: str) -> dict | None:
    db = await get_db_conn()
    try:
        cur = await db.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,))
        row = await cur.fetchone()
        return _def_row_to_payload(row) if row else None
    finally:
        await db.close()


async def _definition_exists(db, workflow_id: str) -> bool:
    cur = await db.execute("SELECT 1 FROM workflows WHERE id = ?", (workflow_id,))
    return await cur.fetchone() is not None


async def save_definition(defn: WorkflowDef, *, is_builtin: bool = False) -> dict:
    """新增或更新定义（更新时 version+1）。内置定义仅由启动同步写入。"""
    now = _now()
    definition = defn.to_json()
    definition["is_builtin"] = is_builtin
    db = await get_db_conn()
    try:
        if await _definition_exists(db, defn.id):
            await db.execute(
                "UPDATE workflows SET name = ?, description = ?, category = ?, "
                "definition_json = ?, is_builtin = ?, version = version + 1, updated_at = ? "
                "WHERE id = ?",
                (
                    defn.name, defn.description, defn.category,
                    json.dumps(definition, ensure_ascii=False),
                    int(is_builtin), now, defn.id,
                ),
            )
        else:
            await db.execute(
                "INSERT INTO workflows (id, name, description, category, definition_json, "
                "is_builtin, version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    defn.id, defn.name, defn.description, defn.category,
                    json.dumps(definition, ensure_ascii=False),
                    int(is_builtin), now, now,
                ),
            )
        await db.commit()
    finally:
        await db.close()
    payload = await get_definition(defn.id)
    assert payload is not None
    return payload


async def delete_definition(workflow_id: str) -> bool:
    """删除自定义定义（内置定义不可删）。"""
    db = await get_db_conn()
    try:
        cur = await db.execute(
            "DELETE FROM workflows WHERE id = ? AND is_builtin = 0", (workflow_id,)
        )
        await db.commit()
        return cur.rowcount > 0
    finally:
        await db.close()


async def sync_builtin_workflows() -> int:
    """把 builtin.py 中的内置定义 upsert 进 DB（代码为唯一事实源，覆盖同名内置行）。"""
    from .builtin import BUILTIN_WORKFLOWS

    n = 0
    for defn in BUILTIN_WORKFLOWS:
        try:
            await _upsert_builtin(defn)
            n += 1
        except Exception:
            logger.exception("同步内置工作流失败 id=%s", defn.id)
    return n


async def _upsert_builtin(defn: WorkflowDef) -> None:
    now = _now()
    definition = defn.to_json()
    definition["is_builtin"] = True
    db = await get_db_conn()
    try:
        await db.execute(
            """
            INSERT INTO workflows (id, name, description, category, definition_json,
                                   is_builtin, version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                category = excluded.category,
                definition_json = excluded.definition_json,
                is_builtin = 1,
                updated_at = excluded.updated_at
            """,
            (
                defn.id, defn.name, defn.description, defn.category,
                json.dumps(definition, ensure_ascii=False), now, now,
            ),
        )
        await db.commit()
    finally:
        await db.close()


# ── 运行记录（workflow_runs 表）───────────────────────────────────────────

def _run_row_to_payload(row) -> dict:
    keys = row.keys()

    def col(name: str):
        return row[name] if name in keys else None

    return {
        "id": col("id"),
        "workflow_id": col("workflow_id"),
        "workflow_name": col("workflow_name") or "",
        "job_id": col("job_id"),
        "status": col("status"),
        "inputs": _loads(col("inputs_json"), {}),
        "def_snapshot": _loads(col("def_snapshot_json"), {}),
        "context": _loads(col("context_json"), {}),
        "error_message": col("error_message") or "",
        "created_at": col("created_at"),
        "updated_at": col("updated_at"),
        "finished_at": col("finished_at"),
    }


async def create_run(workflow_id: str, def_snapshot: dict, inputs: dict) -> dict:
    run_id = str(uuid.uuid4())
    now = _now()
    name = str(def_snapshot.get("name") or workflow_id)
    db = await get_db_conn()
    try:
        await db.execute(
            "INSERT INTO workflow_runs (id, workflow_id, workflow_name, status, inputs_json, "
            "def_snapshot_json, context_json, created_at, updated_at) "
            "VALUES (?, ?, ?, 'pending', ?, ?, '{}', ?, ?)",
            (
                run_id, workflow_id, name,
                json.dumps(inputs, ensure_ascii=False),
                json.dumps(def_snapshot, ensure_ascii=False),
                now, now,
            ),
        )
        await db.commit()
    finally:
        await db.close()
    run = await get_run(run_id)
    assert run is not None
    return run


async def get_run(run_id: str) -> dict | None:
    db = await get_db_conn()
    try:
        cur = await db.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,))
        row = await cur.fetchone()
        return _run_row_to_payload(row) if row else None
    finally:
        await db.close()


async def update_run(
    run_id: str,
    *,
    status: str | None = None,
    job_id: str | None = None,
    context: dict | None = None,
    error: str | None = None,
) -> None:
    sets: list[str] = []
    params: list = []
    if status is not None:
        sets.append("status = ?")
        params.append(status)
        if status in ("done", "error", "cancelled"):
            sets.append("finished_at = ?")
            params.append(_now())
    if job_id is not None:
        sets.append("job_id = ?")
        params.append(job_id)
    if context is not None:
        sets.append("context_json = ?")
        params.append(json.dumps(context, ensure_ascii=False))
    if error is not None:
        sets.append("error_message = ?")
        params.append(error[:2000])
    if not sets:
        return
    sets.append("updated_at = ?")
    params.append(_now())
    params.append(run_id)
    db = await get_db_conn()
    try:
        await db.execute(f"UPDATE workflow_runs SET {', '.join(sets)} WHERE id = ?", params)
        await db.commit()
    finally:
        await db.close()


async def list_runs(limit: int = 50, workflow_id: str | None = None) -> list[dict]:
    """运行历史（新→旧）。列表不带 context/def_snapshot 大字段，详情接口才带。"""
    sql = "SELECT id, workflow_id, workflow_name, job_id, status, inputs_json, error_message, " \
          "context_json, created_at, updated_at, finished_at FROM workflow_runs"
    params: list = []
    if workflow_id:
        sql += " WHERE workflow_id = ?"
        params.append(workflow_id)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit or 50), 200)))
    db = await get_db_conn()
    try:
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
        out = []
        for r in rows:
            payload = _run_row_to_payload(r)
            context = payload.pop("context") or {}
            # 列表级仅保留步骤状态摘要与成片地址
            payload["steps"] = {
                name: (info or {}).get("status")
                for name, info in (context.get("steps") or {}).items()
            }
            payload["render_url"] = _extract_render_url(context)
            payload.pop("def_snapshot")
            out.append(payload)
        return out
    finally:
        await db.close()


def _extract_render_url(context: dict) -> str:
    for info in (context.get("steps") or {}).values():
        output = (info or {}).get("output") or {}
        if isinstance(output, dict) and output.get("url"):
            return str(output["url"])
    return ""


# ── 启动对账 ──────────────────────────────────────────────────────────────

async def reconcile_workflow_runs_on_startup() -> int:
    """进程重启后引擎协程已死：把卡在 pending/running 的运行标记为中断。"""
    from app.jobs.store import list_jobs as list_async_jobs, update_job_status

    db = await get_db_conn()
    try:
        cur = await db.execute(
            "SELECT id, job_id FROM workflow_runs WHERE status IN ('pending', 'running')"
        )
        rows = await cur.fetchall()
    finally:
        await db.close()
    if not rows:
        return 0
    n = 0
    for row in rows:
        await update_run(
            row["id"], status="error", error="服务重启导致工作流中断，可点击重跑恢复"
        )
        job_id = row["job_id"]
        if job_id:
            try:
                jobs = await list_async_jobs(limit=500)
                if any(j["id"] == job_id and j["status"] in ("pending", "running") for j in jobs):
                    await update_job_status(job_id, "error", error_message="服务重启中断")
            except Exception:
                logger.exception("对账 workflow job 失败 job_id=%s", job_id)
        n += 1
    if n:
        logger.warning("启动时已标记 %d 个中断的工作流运行", n)
    return n
