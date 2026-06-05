from __future__ import annotations

import asyncio
from typing import Any

from app.agent.tool_registry import AgentContext, ToolSpec, register
from app.api.process import _run_task
from app.api.process_db import create_task, get_task, get_video, reconcile_orphan_task
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


async def _get_process_job_status(_ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    task_id = (args.get("task_id") or "").strip()
    if not task_id:
        jobs = (_ctx.workspace.jobs or {}).get("process_task_ids") or []
        if jobs:
            task_id = str(jobs[-1])
    if not task_id:
        return ToolResult(ok=False, summary="", error="缺少 task_id，且 workspace 无处理任务")

    row = await get_task(task_id)
    if not row:
        return ToolResult(ok=False, summary="", error=f"任务不存在: {task_id}")

    payload = await reconcile_orphan_task(row)
    status = str(payload.get("status") or "")
    step = str(payload.get("current_step") or "")
    steps = payload.get("steps") or {}
    running = [k for k, v in steps.items() if isinstance(v, dict) and v.get("status") == "running"]
    summary = f"任务 {task_id}：{status}"
    if step:
        summary += f"，当前步骤 {step}"
    if running:
        summary += f"，进行中: {', '.join(running[:3])}"

    suggestions: list[str] = []
    if status == "done":
        suggestions.append("处理已完成，可让我生成剪辑方案")
    elif status in ("running", "pending"):
        suggestions.append("稍后再查询进度，或等待处理完成")

    return ToolResult(
        ok=status != "error",
        summary=summary,
        job_id=task_id,
        artifact=ArtifactRef(
            type="process_job",
            id=task_id,
            payload={**payload, "stream_url": f"/api/process-jobs/{task_id}/ws"},
        ),
        next_suggestions=suggestions,
    )


def register_process_tools() -> None:
    register(
        ToolSpec(
            name="get_process_job_status",
            description="查询素材处理任务进度（切分/ASR/VLM/向量）；处理中可轮询此工具",
            parameters={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "处理任务 ID；可省略则用 workspace 最近任务"},
                },
            },
            risk="L0",
            handler=_get_process_job_status,
        )
    )
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
