from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite

from app.db.database import DB_PATH
from app.models.agent import WorkspaceState

MAX_CHECKPOINTS = 20
MAX_SESSION_LIST = 80


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deep_merge_workspace(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, val in patch.items():
        if key == "jobs" and isinstance(val, dict) and isinstance(out.get("jobs"), dict):
            merged_jobs = dict(out["jobs"])
            for jk, jv in val.items():
                if jk == "process_task_ids" and isinstance(jv, list):
                    existing = list(merged_jobs.get("process_task_ids") or [])
                    for tid in jv:
                        if tid not in existing:
                            existing.append(tid)
                    merged_jobs["process_task_ids"] = existing
                else:
                    merged_jobs[jk] = jv
            out["jobs"] = merged_jobs
        elif key == "plans" and isinstance(val, list):
            out["plans"] = val
        elif key == "user_preferences" and isinstance(val, dict):
            nested = dict(out.get("user_preferences") or {})
            nested.update(val)
            out["user_preferences"] = nested
        elif key == "checkpoints" and isinstance(val, list):
            out["checkpoints"] = val
        elif key == "last_exports" and isinstance(val, list):
            out["last_exports"] = val
        elif isinstance(val, dict) and isinstance(out.get(key), dict):
            nested = dict(out[key])
            nested.update(val)
            out[key] = nested
        else:
            out[key] = val
    return out


async def create_session(
    *,
    title: str | None = None,
    video_ids: list[str] | None = None,
) -> WorkspaceState:
    session_id = str(uuid.uuid4())
    now = _utc_now()
    ws = WorkspaceState(
        session_id=session_id,
        title=(title or "").strip() or "未命名项目",
        selected_video_ids=list(video_ids or []),
    )
    payload = json.dumps(ws.model_dump(), ensure_ascii=False)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO agent_sessions (id, title, workspace_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, ws.title, payload, now, now),
        )
        await db.commit()
    return ws


async def list_sessions(*, limit: int = MAX_SESSION_LIST) -> list[dict[str, Any]]:
    limit = max(1, min(limit, MAX_SESSION_LIST))
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT s.id, s.title, s.workspace_json, s.created_at, s.updated_at,
                   (SELECT COUNT(*) FROM agent_messages m WHERE m.session_id = s.id) AS message_count,
                   (SELECT content_json FROM agent_messages m
                    WHERE m.session_id = s.id AND m.role = 'user'
                    ORDER BY m.created_at DESC LIMIT 1) AS last_user_json
            FROM agent_sessions s
            ORDER BY s.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        phase = "idle"
        try:
            ws = json.loads(row["workspace_json"])
            phase = ws.get("pipeline_phase") or "idle"
        except Exception:
            pass
        preview = ""
        if row["last_user_json"]:
            try:
                content = json.loads(row["last_user_json"])
                preview = str(content.get("text") or content.get("content") or "")[:80]
            except Exception:
                preview = ""
        out.append(
            {
                "session_id": row["id"],
                "title": row["title"] or "未命名项目",
                "pipeline_phase": phase,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "message_count": int(row["message_count"] or 0),
                "preview": preview,
            }
        )
    return out


async def delete_session(session_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM agent_messages WHERE session_id = ?", (session_id,))
        await db.execute("DELETE FROM agent_pending_confirms WHERE session_id = ?", (session_id,))
        cur2 = await db.execute("DELETE FROM agent_sessions WHERE id = ?", (session_id,))
        await db.commit()
        return cur2.rowcount > 0


async def get_session(session_id: str) -> WorkspaceState | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT workspace_json FROM agent_sessions WHERE id = ?",
            (session_id,),
        )
        row = await cur.fetchone()
    if not row:
        return None
    data = json.loads(row["workspace_json"])
    return WorkspaceState(**data)


async def replace_workspace(session_id: str, workspace: WorkspaceState) -> WorkspaceState:
    now = _utc_now()
    workspace.session_id = session_id
    payload = json.dumps(workspace.model_dump(), ensure_ascii=False)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE agent_sessions
            SET workspace_json = ?, title = ?, updated_at = ?
            WHERE id = ?
            """,
            (payload, workspace.title, now, session_id),
        )
        await db.commit()
    return workspace


async def patch_workspace(session_id: str, patch: dict[str, Any]) -> WorkspaceState:
    ws = await get_session(session_id)
    if not ws:
        raise ValueError(f"session not found: {session_id}")
    merged = _deep_merge_workspace(ws.model_dump(), patch)
    merged["session_id"] = session_id
    updated = WorkspaceState(**merged)
    return await replace_workspace(session_id, updated)


async def update_session_title(session_id: str, title: str) -> None:
    title = (title or "").strip()[:80] or "未命名项目"
    now = _utc_now()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE agent_sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, now, session_id),
        )
        await db.commit()
    ws = await get_session(session_id)
    if ws:
        ws.title = title
        await replace_workspace(session_id, ws)


async def append_message(session_id: str, role: str, content: dict[str, Any]) -> str:
    msg_id = str(uuid.uuid4())
    now = _utc_now()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO agent_messages (id, session_id, role, content_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (msg_id, session_id, role, json.dumps(content, ensure_ascii=False), now),
        )
        await db.execute(
            "UPDATE agent_sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        await db.commit()
    return msg_id


async def persist_studio_message(session_id: str, content: dict[str, Any]) -> str:
    """持久化前端可还原的结构化消息。"""
    studio_type = content.get("studio_type") or "assistant"
    role = "user" if studio_type == "user" else "assistant"
    if studio_type in ("tool", "artifact", "system"):
        role = "assistant"
    return await append_message(session_id, role, content)


async def list_messages(session_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, role, content_json, created_at
            FROM agent_messages
            WHERE session_id = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (session_id, limit),
        )
        rows = await cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": row["id"],
                "role": row["role"],
                "content": json.loads(row["content_json"]),
                "created_at": row["created_at"],
            }
        )
    return out


async def clear_messages(session_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM agent_messages WHERE session_id = ?",
            (session_id,),
        )
        row = await cur.fetchone()
        count = int(row[0]) if row else 0
        await db.execute("DELETE FROM agent_messages WHERE session_id = ?", (session_id,))
        await db.execute(
            "UPDATE agent_sessions SET updated_at = ? WHERE id = ?",
            (_utc_now(), session_id),
        )
        await db.commit()
    return count


async def delete_messages_after(session_id: str, created_at: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            DELETE FROM agent_messages
            WHERE session_id = ? AND created_at > ?
            """,
            (session_id, created_at),
        )
        await db.commit()
        return cur.rowcount or 0


async def delete_messages_from(session_id: str, created_at: str) -> int:
    """删除 created_at 及之后的消息（含该条）。"""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            DELETE FROM agent_messages
            WHERE session_id = ? AND created_at >= ?
            """,
            (session_id, created_at),
        )
        await db.execute(
            "UPDATE agent_sessions SET updated_at = ? WHERE id = ?",
            (_utc_now(), session_id),
        )
        await db.commit()
        return cur.rowcount or 0


async def get_message(session_id: str, message_id: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, role, content_json, created_at
            FROM agent_messages
            WHERE session_id = ? AND id = ?
            """,
            (session_id, message_id),
        )
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "role": row["role"],
        "content": json.loads(row["content_json"]),
        "created_at": row["created_at"],
    }


async def get_last_user_message(session_id: str) -> dict[str, Any] | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, role, content_json, created_at
            FROM agent_messages
            WHERE session_id = ?
              AND (role = 'user' OR json_extract(content_json, '$.studio_type') = 'user')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (session_id,),
        )
        row = await cur.fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "role": row["role"],
        "content": json.loads(row["content_json"]),
        "created_at": row["created_at"],
    }


async def push_checkpoint(session_id: str, label: str) -> Optional[dict[str, Any]]:
    ws = await get_session(session_id)
    if not ws:
        return None
    cp = {
        "id": str(uuid.uuid4()),
        "label": label,
        "created_at": _utc_now(),
        "workspace": ws.model_dump(),
    }
    checkpoints = list(ws.checkpoints or [])
    checkpoints.append(cp)
    if len(checkpoints) > MAX_CHECKPOINTS:
        checkpoints = checkpoints[-MAX_CHECKPOINTS:]
    await patch_workspace(session_id, {"checkpoints": checkpoints})
    return cp


async def rollback_checkpoint(session_id: str) -> tuple[WorkspaceState, str]:
    ws = await get_session(session_id)
    if not ws:
        raise ValueError("session not found")
    checkpoints = list(ws.checkpoints or [])
    if not checkpoints:
        raise ValueError("没有可回退的检查点")
    cp = checkpoints.pop()
    snap = cp.get("workspace") or {}
    snap["session_id"] = session_id
    snap["checkpoints"] = checkpoints
    restored = WorkspaceState(**snap)
    await replace_workspace(session_id, restored)
    cp_time = str(cp.get("created_at") or "")
    if cp_time:
        await delete_messages_after(session_id, cp_time)
    label = str(cp.get("label") or "检查点")
    return restored, label


async def rollback_to_message(session_id: str, message_id: str) -> tuple[WorkspaceState, str]:
    """回退到指定用户消息：恢复该消息前的检查点，并删除该消息及之后的内容。"""
    msg = await get_message(session_id, message_id)
    if not msg:
        raise ValueError("消息不存在")
    content = msg.get("content") or {}
    if content.get("studio_type") != "user" and msg.get("role") != "user":
        raise ValueError("只能回退到用户消息")

    msg_time = str(msg["created_at"])
    ws = await get_session(session_id)
    if not ws:
        raise ValueError("session not found")

    checkpoints = list(ws.checkpoints or [])
    best_idx = -1
    for i, cp in enumerate(checkpoints):
        cp_time = str(cp.get("created_at") or "")
        if cp_time and cp_time < msg_time:
            best_idx = i

    if best_idx >= 0:
        cp = checkpoints[best_idx]
        kept = checkpoints[:best_idx]
        snap = dict(cp.get("workspace") or {})
        snap["session_id"] = session_id
        snap["checkpoints"] = kept
        restored = WorkspaceState(**snap)
        await replace_workspace(session_id, restored)
        label = str(cp.get("label") or "检查点")
    else:
        restored = ws
        label = "对话起点"

    deleted = await delete_messages_from(session_id, msg_time)
    if deleted <= 0:
        raise ValueError("没有可删除的消息")
    return restored, label


async def rollback_one_step(session_id: str) -> tuple[WorkspaceState, str]:
    """回退一步：优先弹出最近检查点，否则回退最后一轮用户对话。"""
    ws = await get_session(session_id)
    if not ws:
        raise ValueError("session not found")
    if ws.checkpoints:
        return await rollback_checkpoint(session_id)
    last_user = await get_last_user_message(session_id)
    if last_user:
        return await rollback_to_message(session_id, last_user["id"])
    raise ValueError("没有可回退的内容")


async def reset_workspace(session_id: str, *, keep_title: bool = True) -> WorkspaceState:
    ws = await get_session(session_id)
    if not ws:
        raise ValueError("session not found")
    title = ws.title if keep_title else "未命名项目"
    fresh = WorkspaceState(session_id=session_id, title=title)
    await replace_workspace(session_id, fresh)
    await clear_messages(session_id)
    return fresh


async def save_pending_confirm(
    *,
    call_id: str,
    session_id: str,
    tool_name: str,
    input_json: dict[str, Any],
    risk: str,
) -> None:
    now = _utc_now()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO agent_pending_confirms
            (call_id, session_id, tool_name, input_json, risk, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                call_id,
                session_id,
                tool_name,
                json.dumps(input_json, ensure_ascii=False),
                risk,
                now,
            ),
        )
        await db.commit()


async def pop_pending_confirm(call_id: str) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM agent_pending_confirms WHERE call_id = ?",
            (call_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        await db.execute(
            "DELETE FROM agent_pending_confirms WHERE call_id = ?",
            (call_id,),
        )
        await db.commit()
    return {
        "call_id": row["call_id"],
        "session_id": row["session_id"],
        "tool_name": row["tool_name"],
        "input_json": json.loads(row["input_json"]),
        "risk": row["risk"],
    }
