"""视频总结：持久化与行数据解析。"""

from __future__ import annotations

import json
import uuid
from typing import Any

import aiosqlite
from fastapi import HTTPException

from app.models.summary import SummaryGenerateRequest, VideoSummary

from .prompts import BUILTIN_TEMPLATE_ID, STAGE_A_SYSTEM, STAGE_B_SYSTEM
from .utils import fingerprint, now_iso


def parse_video_summary_row(d: dict[str, Any]) -> dict[str, Any]:
    if d.get("summary_json"):
        try:
            d["summary_json"] = json.loads(d["summary_json"])
        except Exception:
            d["summary_json"] = None
    if d.get("prompt_snapshot_json"):
        try:
            d["prompt_snapshot_json"] = json.loads(d["prompt_snapshot_json"])
        except Exception:
            d["prompt_snapshot_json"] = None
    return d


async def persist_generated_summary(
    db: aiosqlite.Connection,
    *,
    req: SummaryGenerateRequest,
    final_md: str,
    summary_json_obj: dict[str, Any],
    vars_: dict[str, Any],
    context: str,
    schema_hint: str,
) -> VideoSummary:
    """写入 video_summaries 与首条版本记录，返回解析后的 VideoSummary。"""
    now = now_iso()
    summary_id = f"sum_{uuid.uuid4().hex[:12]}"
    tid = BUILTIN_TEMPLATE_ID
    prompt_snapshot = {
        "prompt_kind": "builtin_note_v1",
        "template_id": tid,
        "stage_b_system": STAGE_B_SYSTEM,
        "stage_a_system": STAGE_A_SYSTEM,
        "system_prompt": STAGE_B_SYSTEM,
        "vars": vars_,
        "schema_hint": schema_hint,
        "mode": req.mode,
        "chunk_max_chars": req.chunk_max_chars,
        "chunk_overlap_chars": req.chunk_overlap_chars,
        "max_chunks": req.max_chunks,
    }
    fp = fingerprint(
        [
            req.video_id,
            req.mode,
            tid,
            json.dumps(vars_, ensure_ascii=False, sort_keys=True),
            context,
        ]
    )

    await db.execute(
        """
        INSERT INTO video_summaries
        (id, video_id, template_id, mode, status, input_fingerprint, summary_json, summary_markdown, prompt_snapshot_json, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            summary_id,
            req.video_id,
            tid,
            req.mode,
            "done",
            fp,
            json.dumps(summary_json_obj, ensure_ascii=False),
            final_md,
            json.dumps(prompt_snapshot, ensure_ascii=False),
            now,
            now,
        ),
    )
    await db.execute(
        """
        INSERT INTO video_summary_versions
        (id, summary_id, version, source, content_json, content_markdown, created_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            f"sumv_{uuid.uuid4().hex[:12]}",
            summary_id,
            1,
            "llm",
            json.dumps(summary_json_obj, ensure_ascii=False),
            final_md,
            now,
        ),
    )
    await db.commit()

    cur_out = await db.execute("SELECT * FROM video_summaries WHERE id = ?", (summary_id,))
    row_out = await cur_out.fetchone()
    if not row_out:
        raise HTTPException(status_code=500, detail="总结写入后读取失败")
    d = parse_video_summary_row(dict(row_out))
    return VideoSummary(**d)
