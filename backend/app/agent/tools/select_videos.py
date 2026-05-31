from __future__ import annotations

from typing import Any

from app.agent.intent_preflight import search_videos_by_name
from app.agent.tool_registry import AgentContext, ToolSpec, register
from app.models.agent import ArtifactRef, ToolResult


async def _select_videos_by_keyword(ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    keyword = (args.get("keyword") or "").strip()
    if not keyword:
        return ToolResult(ok=False, summary="", error="缺少 keyword")
    limit = max(1, min(int(args.get("limit") or 3), 10))
    rows = await search_videos_by_name(keyword, limit=limit)
    if not rows:
        return ToolResult(
            ok=False,
            summary="",
            error=f"素材库中未找到名称包含「{keyword}」的视频，请换关键词或 list_videos",
        )
    ids = [str(r["id"]) for r in rows]
    names = "\n".join(f"- {r['name']} ({r['id']})" for r in rows)
    return ToolResult(
        ok=True,
        summary=f"已选中 {len(ids)} 个视频：\n{names}",
        workspace_patch={"selected_video_ids": ids, "pipeline_phase": "ingest"},
        artifact=ArtifactRef(type="video", id="selection", payload={"video_ids": ids, "videos": rows}),
    )


def register_select_video_tools() -> None:
    register(
        ToolSpec(
            name="select_videos_by_keyword",
            description="按名称关键词搜索素材库并选中视频（如「洁柔」选中所有名称含洁柔的视频，配合 limit）",
            parameters={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "视频名称关键词，如 洁柔、后室"},
                    "limit": {"type": "integer", "description": "最多选中几个，默认3"},
                },
                "required": ["keyword"],
            },
            risk="L1",
            handler=_select_videos_by_keyword,
        )
    )
