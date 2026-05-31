from __future__ import annotations

import asyncio
from typing import Any

from app.agent.tool_registry import AgentContext, ToolSpec, register
from app.api.process import _run_task
from app.api.process_db import create_task, get_video
from app.api.process_shared import _job_tasks
from app.core.license import ensure_license_valid, is_license_enforced
from app.models.agent import ArtifactRef, ToolResult


async def _start_process_job(ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    video_id = (args.get("video_id") or "").strip()
    if not video_id:
        video_ids = ctx.workspace.selected_video_ids
        if len(video_ids) == 1:
            video_id = video_ids[0]
        else:
            return ToolResult(ok=False, summary="", error="请提供 video_id 或先在 workspace 选中单个视频")

    if is_license_enforced() and not await ensure_license_valid():
        return ToolResult(ok=False, summary="", error="需要有效卡密授权")

    video = await get_video(video_id)
    if not video:
        return ToolResult(ok=False, summary="", error=f"视频不存在: {video_id}")

    task_payload = await create_task(video_id)
    task_id = task_payload["id"]
    if task_id not in _job_tasks:
        _job_tasks[task_id] = asyncio.create_task(_run_task(task_id, video_id))

    return ToolResult(
        ok=True,
        summary=f"已开始处理视频 {video.get('name') or video_id}，任务 {task_id}",
        job_id=task_id,
        workspace_patch={
            "pipeline_phase": "process",
            "jobs": {"process_task_ids": [task_id]},
        },
        artifact=ArtifactRef(
            type="process_job",
            id=task_id,
            payload={"task_id": task_id, "video_id": video_id, "stream_url": f"/api/process-jobs/{task_id}/ws"},
        ),
        next_suggestions=["处理完成后可让我生成剪辑方案"],
    )


def register_process_tools() -> None:
    register(
        ToolSpec(
            name="start_process_job",
            description="对指定视频启动素材处理流水线（切分、ASR、VLM、向量化）",
            parameters={
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "视频 ID；可省略若 workspace 仅选中一个"},
                },
            },
            risk="L2",
            handler=_start_process_job,
        )
    )
