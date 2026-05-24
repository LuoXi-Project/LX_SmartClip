from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiosqlite

from app.db.database import DB_PATH, get_db_conn
from app.models.auto_edit import Plan
from app.models.film_commentary import (
    FilmAlignment,
    FilmCommentaryJob,
    FilmJobStatus,
    FilmMode,
    FilmSentence,
    FilmStyle,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _prompt_overrides_to_json(overrides: dict | None) -> str | None:
    if not overrides:
        return None
    cleaned = {k: v for k, v in overrides.items() if v and str(v).strip()}
    if not cleaned:
        return None
    return json.dumps(cleaned, ensure_ascii=False)


async def create_job(
    *,
    video_id: str,
    mode: FilmMode,
    style: FilmStyle,
    target_duration_sec: int,
    auto_render: bool,
    include_subtitle: bool,
    prompt_overrides: dict | None = None,
) -> str:
    job_id = str(uuid.uuid4())
    now = _now()
    db = await get_db_conn()
    try:
        await db.execute(
            """
            INSERT INTO film_commentary_jobs (
                id, video_id, status, current_step, mode, style,
                target_duration_sec, auto_render, include_subtitle,
                prompt_overrides_json, progress_json, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                job_id,
                video_id,
                "pending",
                None,
                mode,
                style,
                target_duration_sec,
                1 if auto_render else 0,
                1 if include_subtitle else 0,
                _prompt_overrides_to_json(prompt_overrides),
                "{}",
                now,
                now,
            ),
        )
        await db.commit()
    finally:
        await db.close()
    return job_id


async def update_job_fields(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    allowed = {
        "status",
        "current_step",
        "progress_json",
        "error_message",
        "clip_summaries_json",
        "storyline_json",
        "sentences_json",
        "alignments_json",
        "plan_json",
        "output_path",
        "output_url",
        "finished_at",
    }
    parts: List[str] = []
    vals: List[Any] = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        parts.append(f"{k} = ?")
        vals.append(v)
    parts.append("updated_at = ?")
    vals.append(_now())
    vals.append(job_id)
    db = await get_db_conn()
    try:
        await db.execute(
            f"UPDATE film_commentary_jobs SET {', '.join(parts)} WHERE id = ?",
            vals,
        )
        await db.commit()
    finally:
        await db.close()


async def update_job_progress(job_id: str, step: str, status: str, message: str, detail: dict | None = None) -> None:
    row = await get_job_row(job_id)
    if not row:
        return
    progress = _loads(row.get("progress_json"), {})
    progress[step] = {"status": status, "message": message, "detail": detail or {}}
    await update_job_fields(
        job_id,
        current_step=step,
        progress_json=json.dumps(progress, ensure_ascii=False),
    )


async def get_job_row(job_id: str) -> dict | None:
    db = await get_db_conn()
    try:
        cur = await db.execute(
            """
            SELECT j.*, v.name AS video_name
            FROM film_commentary_jobs j
            LEFT JOIN videos v ON v.id = j.video_id
            WHERE j.id = ?
            """,
            (job_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def list_jobs(limit: int = 50) -> List[dict]:
    db = await get_db_conn()
    try:
        cur = await db.execute(
            """
            SELECT j.*, v.name AS video_name
            FROM film_commentary_jobs j
            LEFT JOIN videos v ON v.id = j.video_id
            ORDER BY j.created_at DESC
            LIMIT ?
            """,
            (max(1, min(limit, 200)),),
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


def row_to_job(row: dict) -> FilmCommentaryJob:
    plan_raw = row.get("plan_json")
    plan_obj: Plan | None = None
    if plan_raw:
        try:
            plan_obj = Plan.model_validate_json(plan_raw)
        except Exception:
            plan_obj = None

    sentences_raw = _loads(row.get("sentences_json"), [])
    align_raw = _loads(row.get("alignments_json"), [])

    return FilmCommentaryJob(
        id=row["id"],
        video_id=row["video_id"],
        video_name=row.get("video_name"),
        status=row["status"],
        current_step=row.get("current_step"),
        mode=row["mode"],
        style=row["style"],
        target_duration_sec=int(row.get("target_duration_sec") or 300),
        auto_render=bool(row.get("auto_render")),
        include_subtitle=bool(row.get("include_subtitle")),
        progress=_loads(row.get("progress_json"), {}),
        error_message=row.get("error_message"),
        storyline=_loads(row.get("storyline_json"), None),
        sentences=[FilmSentence.model_validate(s) for s in sentences_raw if isinstance(s, dict)],
        alignments=[FilmAlignment.model_validate(a) for a in align_raw if isinstance(a, dict)],
        plan=plan_obj,
        output_url=row.get("output_url"),
        output_filename=row.get("output_path"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        finished_at=row.get("finished_at"),
    )


async def load_clips_for_video(video_id: str) -> List[dict]:
    db = await get_db_conn()
    try:
        cur = await db.execute(
            """
            SELECT id, video_id, clip_path, start_time, end_time, duration,
                   asr_text, vlm_description
            FROM clips WHERE video_id = ?
            ORDER BY start_time ASC
            """,
            (video_id,),
        )
        return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def read_config_map() -> Dict[str, str]:
    db = await get_db_conn()
    try:
        cur = await db.execute("SELECT key, value FROM config")
        rows = await cur.fetchall()
        return {str(r["key"]): str(r["value"] or "") for r in rows}
    finally:
        await db.close()
