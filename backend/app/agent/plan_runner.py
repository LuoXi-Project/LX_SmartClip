from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from app.agent import session_store
from app.agent.intent_preflight import _extract_search_terms
from app.agent.tool_registry import AgentContext, REGISTRY, invoke, needs_confirm
from app.api.process_db import get_task, reconcile_orphan_task, row_to_task_payload
from app.models.agent import PlannerOutput, PlannerStep, ToolResult

logger = logging.getLogger(__name__)

# 仅用于 start_process_job 之后的素材处理轮询（切分/ASR/VLM/向量）。
# 不包含 realize_plan / export_jianying_draft 成片渲染——成片是同步 invoke，无此超时。
PROCESS_JOB_POLL_INTERVAL_SEC = 2.0
PROCESS_JOB_POLL_TIMEOUT_SEC = 3600.0  # 长素材处理可超 10 分钟，与 auto_edit realize 上限对齐

# 规划步骤中可自动推断参数的工具
_AUTO_ARG_TOOLS = frozenset({
    "list_videos",
    "get_workspace_state",
    "get_video_status",
    "set_selected_videos",
    "select_videos_by_keyword",
    "start_process_job",
    "get_process_job_status",
    "generate_auto_edit_plan",
    "realize_plan",
    "export_jianying_draft",
})


def _sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def _topo_sort(steps: list[PlannerStep]) -> list[PlannerStep]:
    by_id = {s.id: s for s in steps}
    done: set[str] = set()
    out: list[PlannerStep] = []
    remaining = list(steps)
    guard = 0
    while remaining and guard < len(steps) * 3:
        guard += 1
        progressed = False
        next_remaining: list[PlannerStep] = []
        for step in remaining:
            deps = set(step.depends_on or [])
            if deps <= done:
                out.append(step)
                done.add(step.id)
                progressed = True
            else:
                next_remaining.append(step)
        if not progressed:
            out.extend(next_remaining)
            break
        remaining = next_remaining
    return out


def build_step_args(tool: str, ctx: AgentContext, user_message: str) -> dict[str, Any] | None:
    ws = ctx.workspace
    if tool in ("list_videos", "get_workspace_state"):
        return {}
    if tool == "get_video_status":
        if not ws.selected_video_ids:
            return None
        return {"video_id": ws.selected_video_ids[0]}
    if tool == "set_selected_videos":
        if not ws.selected_video_ids:
            return None
        return {"video_ids": list(ws.selected_video_ids)}
    if tool == "select_videos_by_keyword":
        terms = _extract_search_terms(user_message)
        if not terms:
            return None
        return {"keyword": terms[0], "limit": 5}
    if tool == "start_process_job":
        if len(ws.selected_video_ids) == 1:
            return {"video_id": ws.selected_video_ids[0]}
        return None
    if tool == "get_process_job_status":
        jobs = (ws.jobs or {}).get("process_task_ids") or []
        if not jobs:
            return None
        return {"task_id": str(jobs[-1])}
    if tool == "generate_auto_edit_plan":
        if not ws.selected_video_ids:
            return None
        prefs = ws.user_preferences or {}
        return {
            "video_ids": list(ws.selected_video_ids),
            "user_prompt": user_message.strip() or str(prefs.get("last_user_prompt") or ""),
            "target_duration_sec": prefs.get("target_duration_sec"),
        }
    if tool in ("realize_plan", "export_jianying_draft"):
        if not ws.plans:
            return None
        plan_id = str(ws.active_plan_id or ws.plans[0].get("plan_id") or "")
        raw = next((p for p in ws.plans if str(p.get("plan_id")) == plan_id), ws.plans[0])
        mode = str(raw.get("mode") or "auto")
        force_tts = mode in ("voiceover", "auto")
        return {"plan_id": plan_id, "force_tts_pipeline": force_tts}
    return None


def _progress_message(payload: dict[str, Any]) -> str:
    status = str(payload.get("status") or "")
    step = str(payload.get("current_step") or "")
    steps = payload.get("steps") or {}
    if isinstance(steps, dict) and steps:
        parts: list[str] = []
        for name, info in steps.items():
            if not isinstance(info, dict):
                continue
            st = str(info.get("status") or "")
            msg = str(info.get("message") or "")[:60]
            if st == "running":
                parts.append(f"{name}: {msg or '进行中'}")
            elif st == "done":
                parts.append(f"{name}✓")
        if parts:
            return f"处理中 ({status}) — " + " · ".join(parts[:4])
    return f"素材处理 {status}" + (f" · 当前 {step}" if step else "")


def _progress_percent(payload: dict[str, Any]) -> int | None:
    steps = payload.get("steps")
    if not isinstance(steps, dict) or not steps:
        return None
    total = len(steps)
    done = sum(1 for v in steps.values() if isinstance(v, dict) and v.get("status") == "done")
    if total:
        return min(99, int(done / total * 100))
    return None


async def _apply_tool_result(session_id: str, result: ToolResult, ctx: AgentContext) -> None:
    if result.workspace_patch:
        ctx.workspace = await session_store.patch_workspace(session_id, result.workspace_patch)


async def _persist_plan_trace(
    session_id: str,
    *,
    route: str,
    route_reason: str,
    step_states: list[dict[str, Any]],
) -> None:
    if not route and not step_states:
        return
    await session_store.persist_studio_message(
        session_id,
        {
            "studio_type": "execution_trace",
            "route": route,
            "route_reason": route_reason,
            "steps": step_states,
        },
    )


async def _poll_process_job(
    session_id: str,
    task_id: str,
) -> AsyncIterator[bytes]:
    start = time.monotonic()
    last_msg = ""
    while time.monotonic() - start < PROCESS_JOB_POLL_TIMEOUT_SEC:
        row = await get_task(task_id)
        if not row:
            yield _sse("progress", {
                "job_id": task_id,
                "message": "任务不存在或已清理",
                "status": "error",
            })
            return
        payload = await reconcile_orphan_task(row)
        status = str(payload.get("status") or "")
        msg = _progress_message(payload)
        pct = _progress_percent(payload)
        if msg != last_msg or status in ("done", "error", "cancelled"):
            yield _sse("progress", {
                "job_id": task_id,
                "step": payload.get("current_step"),
                "message": msg,
                "status": status,
                "percent": pct,
            })
            last_msg = msg
        if status == "done":
            return
        if status in ("error", "cancelled"):
            return
        await asyncio.sleep(PROCESS_JOB_POLL_INTERVAL_SEC)
    yield _sse("progress", {
        "job_id": task_id,
        "message": "素材处理等待超时（1 小时），可稍后让我查询进度或继续",
        "status": "timeout",
    })


async def _videos_need_process(ctx: AgentContext) -> bool:
    from app.agent.tools.videos import _get_video_status

    for vid in ctx.workspace.selected_video_ids[:5]:
        res = await _get_video_status(ctx, {"video_id": vid})
        if not res.ok:
            continue
        payload = (res.artifact.payload if res.artifact else {}) or {}
        st = str(payload.get("status") or "")
        clips = int(payload.get("clip_count") or payload.get("total_clips") or 0)
        if st != "done" or clips == 0:
            return True
    return False


async def run_plan_steps(
    session_id: str,
    plan: PlannerOutput,
    ctx: AgentContext,
    user_message: str,
    *,
    route: str = "",
    route_reason: str = "",
    confirm_preview_fn,
    finish_tool_result_fn,
    maybe_checkpoint_fn,
) -> AsyncIterator[bytes]:
    """
    按 Planner 步骤顺序执行；start_process_job 后自动轮询进度。
    遇 L2 确认或无法推断参数时提前结束，由 Executor 接手。
    """
    steps = _topo_sort(plan.steps)
    if not steps:
        yield _sse("plan_done", {"completed": False, "reason": "empty_plan"})
        return

    step_states: dict[str, dict[str, Any]] = {
        s.id: {"id": s.id, "title": s.title, "tool": s.tool, "status": "pending"}
        for s in steps
    }

    def _patch_step(step_id: str, **fields: Any) -> None:
        if step_id in step_states:
            step_states[step_id].update(fields)

    async def _finish_plan(payload: dict[str, Any]) -> bytes:
        await _persist_plan_trace(
            session_id,
            route=route,
            route_reason=route_reason,
            step_states=list(step_states.values()),
        )
        return _sse("plan_done", payload)

    yield _sse("message_delta", {"content": f"已规划 {len(steps)} 步，开始按序执行…\n"})

    for step in steps:
        spec = REGISTRY.get(step.tool)
        if not spec:
            _patch_step(
                step.id,
                status="skipped",
                title=step.title,
                tool=step.tool,
                message=f"未知工具 {step.tool}",
            )
            yield _sse("plan_step_update", {
                "step_id": step.id,
                "status": "skipped",
                "title": step.title,
                "tool": step.tool,
                "message": f"未知工具 {step.tool}",
            })
            continue

        if step.tool not in _AUTO_ARG_TOOLS:
            _patch_step(
                step.id,
                status="skipped",
                title=step.title,
                tool=step.tool,
                message="需 Agent 补充参数，转交对话执行",
            )
            yield _sse("plan_step_update", {
                "step_id": step.id,
                "status": "skipped",
                "title": step.title,
                "tool": step.tool,
                "message": "需 Agent 补充参数，转交对话执行",
            })
            yield await _finish_plan({"completed": False, "reason": "needs_executor", "at_step": step.id})
            return

        args = build_step_args(step.tool, ctx, user_message)
        if args is None:
            _patch_step(
                step.id,
                status="skipped",
                title=step.title,
                tool=step.tool,
                message="缺少前置条件，转交对话执行",
            )
            yield _sse("plan_step_update", {
                "step_id": step.id,
                "status": "skipped",
                "title": step.title,
                "tool": step.tool,
                "message": "缺少前置条件，转交对话执行",
            })
            yield await _finish_plan({"completed": False, "reason": "missing_args", "at_step": step.id})
            return

        # 生成方案前确保素材已处理
        if step.tool == "generate_auto_edit_plan" and await _videos_need_process(ctx):
            _patch_step(
                step.id,
                status="skipped",
                title=step.title,
                tool=step.tool,
                message="素材尚未处理完成，转交对话执行",
            )
            yield _sse("plan_step_update", {
                "step_id": step.id,
                "status": "skipped",
                "title": step.title,
                "tool": step.tool,
                "message": "素材尚未处理完成，转交对话执行",
            })
            yield await _finish_plan({"completed": False, "reason": "videos_not_ready", "at_step": step.id})
            return

        _patch_step(
            step.id,
            status="running",
            title=step.title,
            tool=step.tool,
            message=f"正在执行 {step.title}",
        )
        yield _sse("plan_step_update", {
            "step_id": step.id,
            "status": "running",
            "title": step.title,
            "tool": step.tool,
            "message": f"正在执行 {step.title}",
        })

        call_id = str(uuid.uuid4())
        if needs_confirm(spec, ctx):
            preview = confirm_preview_fn(step.tool, args, ctx)
            await session_store.save_pending_confirm(
                call_id=call_id,
                session_id=session_id,
                tool_name=step.tool,
                input_json=args,
                risk=spec.risk,
            )
            hint = f"规划步骤「{step.title}」需要确认：{preview}"
            yield _sse("confirm_required", {
                "call_id": call_id,
                "tool": step.tool,
                "input": args,
                "risk": spec.risk,
                "preview": preview,
                "plan_step_id": step.id,
            })
            yield _sse("message_delta", {"content": hint})
            _patch_step(
                step.id,
                status="pending",
                title=step.title,
                tool=step.tool,
                message="等待确认",
            )
            yield _sse("plan_step_update", {
                "step_id": step.id,
                "status": "pending",
                "title": step.title,
                "tool": step.tool,
                "message": "等待确认",
            })
            await session_store.persist_studio_message(
                session_id, {"studio_type": "assistant", "text": hint}
            )
            yield await _finish_plan({"completed": False, "reason": "pending_confirm", "at_step": step.id})
            return

        yield _sse("tool_start", {"call_id": call_id, "name": step.tool, "input": args, "plan_step_id": step.id})
        await maybe_checkpoint_fn(session_id, step.tool)
        result = await invoke(step.tool, args, ctx)
        await _apply_tool_result(session_id, result, ctx)
        if result.workspace_patch:
            yield _sse("workspace_patch", {"patch": result.workspace_patch})

        async for chunk in finish_tool_result_fn(
            session_id,
            call_id=call_id,
            tool_name=step.tool,
            args=args,
            result=result,
        ):
            yield chunk

        if not result.ok:
            _patch_step(
                step.id,
                status="failed",
                title=step.title,
                tool=step.tool,
                message=result.error or result.summary,
            )
            yield _sse("plan_step_update", {
                "step_id": step.id,
                "status": "failed",
                "title": step.title,
                "tool": step.tool,
                "message": result.error or result.summary,
            })
            yield await _finish_plan({"completed": False, "reason": "step_failed", "at_step": step.id})
            return

        done_msg = result.summary[:120] if result.summary else "完成"
        _patch_step(
            step.id,
            status="done",
            title=step.title,
            tool=step.tool,
            message=done_msg,
        )
        yield _sse("plan_step_update", {
            "step_id": step.id,
            "status": "done",
            "title": step.title,
            "tool": step.tool,
            "message": done_msg,
        })

        if step.tool == "start_process_job" and result.job_id:
            yield _sse("message_delta", {"content": "\n等待素材处理完成…\n"})
            async for prog in _poll_process_job(session_id, result.job_id):
                yield prog
            row = await get_task(result.job_id)
            if row:
                payload = await reconcile_orphan_task(row)
                if str(payload.get("status")) != "done":
                    yield await _finish_plan({
                        "completed": False,
                        "reason": "process_not_done",
                        "at_step": step.id,
                    })
                    return

    yield _sse("message_delta", {"content": "\n规划步骤已全部完成。\n"})
    yield await _finish_plan({"completed": True})
