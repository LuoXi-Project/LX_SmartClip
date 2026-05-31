from __future__ import annotations

from typing import Any

from app.agent.tool_registry import AgentContext, ToolSpec, register
from app.models.agent import ToolResult


async def _get_workspace_state(ctx: AgentContext, _args: dict[str, Any]) -> ToolResult:
    ws = ctx.workspace
    return ToolResult(
        ok=True,
        summary=(
            f"阶段={ws.pipeline_phase}, 选中视频={len(ws.selected_video_ids)}, "
            f"方案数={len(ws.plans)}, active_plan={ws.active_plan_id or '无'}"
        ),
        workspace_patch=None,
    )


async def _set_selected_videos(ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    ids = args.get("video_ids") or []
    if not isinstance(ids, list):
        return ToolResult(ok=False, summary="", error="video_ids 必须为数组")
    clean = [str(v).strip() for v in ids if str(v).strip()]
    return ToolResult(
        ok=True,
        summary=f"已选中 {len(clean)} 个视频",
        workspace_patch={"selected_video_ids": clean, "pipeline_phase": "ingest"},
    )


def register_workspace_tools() -> None:
    register(
        ToolSpec(
            name="get_workspace_state",
            description="获取当前智剪工作区的阶段、选中视频、方案等摘要",
            parameters={"type": "object", "properties": {}},
            risk="L0",
            handler=_get_workspace_state,
        )
    )
    register(
        ToolSpec(
            name="set_selected_videos",
            description="设置当前工作区要操作的素材视频 ID 列表",
            parameters={
                "type": "object",
                "properties": {
                    "video_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "视频 ID 列表",
                    }
                },
                "required": ["video_ids"],
            },
            risk="L1",
            handler=_set_selected_videos,
        )
    )
