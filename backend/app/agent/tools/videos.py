from __future__ import annotations

from typing import Any

import aiosqlite

from app.agent.tool_registry import AgentContext, ToolSpec, register
from app.db.database import DB_PATH
from app.models.agent import ArtifactRef, ToolResult


async def _list_videos(_ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    limit = min(int(args.get("limit") or 20), 50)
    q = (args.get("q") or "").strip().lower()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if q:
            cur = await db.execute(
                """
                SELECT id, name, status, duration, total_clips, upload_at
                FROM videos
                WHERE LOWER(name) LIKE ?
                ORDER BY upload_at DESC
                LIMIT ?
                """,
                (f"%{q}%", limit),
            )
        else:
            cur = await db.execute(
                """
                SELECT id, name, status, duration, total_clips, upload_at
                FROM videos
                ORDER BY upload_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        rows = await cur.fetchall()
    items = [dict(r) for r in rows]
    lines = [
        f"- {r['id']}: {r['name']} [{r['status']}] clips={r['total_clips'] or 0}"
        for r in items
    ]
    return ToolResult(
        ok=True,
        summary=f"共 {len(items)} 个视频。\n" + ("\n".join(lines) if lines else "（空）"),
        artifact=ArtifactRef(type="video", id="list", payload={"videos": items})
        if items
        else None,
    )


async def _get_video_status(_ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    video_id = (args.get("video_id") or "").strip()
    if not video_id:
        return ToolResult(ok=False, summary="", error="缺少 video_id")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT id, name, status, duration, total_clips FROM videos WHERE id = ?",
            (video_id,),
        )
        row = await cur.fetchone()
        if not row:
            return ToolResult(ok=False, summary="", error=f"视频不存在: {video_id}")
        cur2 = await db.execute(
            "SELECT COUNT(*) AS c FROM clips WHERE video_id = ?",
            (video_id,),
        )
        clip_row = await cur2.fetchone()
    clip_count = int(clip_row["c"]) if clip_row else 0
    info = dict(row)
    info["clip_count"] = clip_count
    return ToolResult(
        ok=True,
        summary=(
            f"{info['name']} ({video_id}): status={info['status']}, "
            f"clips={clip_count}, duration={info.get('duration') or '?'}"
        ),
        artifact=ArtifactRef(type="video", id=video_id, payload=info),
    )


def register_video_tools() -> None:
    register(
        ToolSpec(
            name="list_videos",
            description="列出素材库中的视频，可按名称关键词筛选",
            parameters={
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "名称关键词，可选"},
                    "limit": {"type": "integer", "description": "最多返回条数，默认20"},
                },
            },
            risk="L0",
            handler=_list_videos,
        )
    )
    register(
        ToolSpec(
            name="get_video_status",
            description="查询单个视频的 processing 状态与片段数量",
            parameters={
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "视频 ID"},
                },
                "required": ["video_id"],
            },
            risk="L0",
            handler=_get_video_status,
        )
    )
