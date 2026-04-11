"""视频总结：从数据库加载模板、构建视频上下文与分段文本。"""

from __future__ import annotations

import json
from typing import Any

import aiosqlite
from fastapi import HTTPException

from app.models.summary import SummaryTemplate

from .utils import fmt_time


async def load_template(db: aiosqlite.Connection, template_id: str) -> SummaryTemplate:
    cur = await db.execute(
        """
        SELECT id, name, description, system_prompt, user_prompt_template, output_schema_hint, created_at, updated_at
        FROM summary_templates
        WHERE id = ?
        """,
        (template_id,),
    )
    row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"总结模板不存在: {template_id}")
    return SummaryTemplate(**dict(row))


async def build_video_context(db: aiosqlite.Connection, *, video_id: str, mode: str) -> str:
    cur = await db.execute(
        """
        SELECT c.id, c.start_time, c.end_time, c.asr_text, c.vlm_description
        FROM clips c
        WHERE c.video_id = ?
          AND (
            TRIM(COALESCE(c.asr_text, '')) <> ''
            OR TRIM(COALESCE(c.vlm_description, '')) <> ''
          )
        ORDER BY c.start_time
        """,
        (video_id,),
    )
    rows = await cur.fetchall()
    if not rows:
        return "（未找到有效的 ASR 或 VLM 识别内容）"

    lines: list[str] = [f"【video_id】{video_id}", "【内容片段】"]
    for r in rows:
        t0 = fmt_time(r["start_time"])
        t1 = fmt_time(r["end_time"])
        parts: list[str] = []
        if mode in ("asr", "asr_vlm"):
            asr = (r["asr_text"] or "").strip()
            if asr:
                parts.append(f"台词：{asr}")
        if mode in ("vlm", "asr_vlm"):
            vlm = (r["vlm_description"] or "").strip()
            if vlm:
                parts.append(f"画面：{vlm}")
        if not parts:
            continue
        lines.append(f"- [clip_id={r['id']}] [{t0}→{t1}] " + " | ".join(parts))
    return "\n".join(lines).strip()


async def build_segment_text(db: aiosqlite.Connection, *, video_id: str, mode: str) -> str:
    cur = await db.execute(
        """
        SELECT c.id, c.start_time, c.end_time, c.asr_text, c.vlm_description
        FROM clips c
        WHERE c.video_id = ?
          AND (
            TRIM(COALESCE(c.asr_text, '')) <> ''
            OR TRIM(COALESCE(c.vlm_description, '')) <> ''
          )
        ORDER BY c.start_time
        """,
        (video_id,),
    )
    rows = await cur.fetchall()
    if not rows:
        return "（未找到有效的 ASR 或 VLM 识别内容）"

    lines: list[str] = []
    for r in rows:
        t0 = fmt_time(r["start_time"])
        parts: list[str] = []
        if mode in ("asr", "asr_vlm"):
            asr = (r["asr_text"] or "").strip()
            if asr:
                parts.append(f"台词：{asr}")
        if mode in ("vlm", "asr_vlm"):
            vlm = (r["vlm_description"] or "").strip()
            if vlm:
                parts.append(f"画面：{vlm}")
        if not parts:
            continue
        lines.append(f"{t0} - " + " | ".join(parts))
    return "\n".join(lines).strip()


async def prompt_extra_vars(db: aiosqlite.Connection, *, video_id: str, mode: str) -> dict[str, Any]:
    cur = await db.execute("SELECT name FROM videos WHERE id = ?", (video_id,))
    row = await cur.fetchone()
    video_title = (str(row["name"]).strip() if row and row["name"] else "") or "(未命名)"

    cur2 = await db.execute("SELECT tags FROM clips WHERE video_id = ?", (video_id,))
    tag_set: set[str] = set()
    for r in await cur2.fetchall():
        raw = r["tags"]
        if not raw:
            continue
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                tag_set.update(str(x).strip() for x in arr if str(x).strip())
        except Exception:
            continue
    tags_str = "、".join(sorted(tag_set)) if tag_set else "(无)"

    segment_text = await build_segment_text(db, video_id=video_id, mode=mode)
    return {
        "video_title": video_title,
        "tags": tags_str,
        "segment_text": segment_text,
    }
