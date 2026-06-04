from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any, Optional

import aiosqlite

from app.agent import session_store
from app.agent.context_builder import build_workspace_summary
from app.agent.export_intent import ExportIntent, detect_export_intent
from app.agent.planner import build_task_plan
from app.agent.prompts.executor import EXECUTOR_SYSTEM
from app.agent.intent_preflight import run_intent_preflight
from app.agent.router import classify_route
from app.agent.tool_registry import AgentContext, get_openai_tools, invoke, needs_confirm
from app.agent.tools import register_all_tools
from app.agent.tool_registry import REGISTRY, ToolSpec
from app.core.llm import LLMConfig
from app.db.database import DB_PATH
from app.models.agent import ChatRequest, ToolResult

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6


def _emit_content_chunks(content: str) -> list[tuple[str, dict[str, Any]]]:
    """将助手文本拆成 reasoning（思考：）与 message 事件。"""
    if not content:
        return []
    events: list[tuple[str, dict[str, Any]]] = []
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("思考：") or stripped.startswith("思考:"):
            events.append(("reasoning_delta", {"content": stripped + "\n"}))
        else:
            events.append(("message_delta", {"content": line + "\n"}))
    if events and events[-1][0] == "message_delta":
        # 去掉最后一行多余换行
        last = events[-1][1]["content"]
        events[-1] = ("message_delta", {"content": last.rstrip("\n")})
    return events

CHECKPOINT_BEFORE = frozenset({
    "set_selected_videos",
    "select_videos_by_keyword",
    "set_production_preset",
    "resolve_production_intent",
    "apply_production_patch",
    "generate_auto_edit_plan",
    "apply_plan_patch",
    "realize_plan",
    "export_jianying_draft",
    "start_process_job",
})


def _sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


async def _load_llm_cfg() -> dict[str, Any]:
    async with aiosqlite.connect(DB_PATH) as db:
        return await LLMConfig.get_llm_params_with_defaults(
            db,
            base_url_key="llm_base_url",
            api_key_key="llm_api_key",
            model_key="llm_model",
            fallback_model_key="vlm_model",
            default_temperature=0.5,
            default_max_tokens=4096,
        )


async def _apply_tool_result(session_id: str, result: ToolResult, ctx: AgentContext) -> None:
    if result.workspace_patch:
        ctx.workspace = await session_store.patch_workspace(session_id, result.workspace_patch)


async def _maybe_checkpoint(session_id: str, tool_name: str) -> None:
    if tool_name in CHECKPOINT_BEFORE:
        await session_store.push_checkpoint(session_id, f"before {tool_name}")


async def _persist_tool_message(
    session_id: str,
    *,
    call_id: str,
    name: str,
    status: str,
    summary: str = "",
    input_data: dict[str, Any] | None = None,
) -> None:
    await session_store.persist_studio_message(
        session_id,
        {
            "studio_type": "tool",
            "call_id": call_id,
            "name": name,
            "status": status,
            "summary": summary,
            "input": input_data or {},
        },
    )


async def _persist_artifact_message(session_id: str, artifact: dict[str, Any]) -> None:
    await session_store.persist_studio_message(
        session_id,
        {"studio_type": "artifact", "artifact": artifact},
    )


async def _maybe_autotitle(session_id: str, user_message: str, ws) -> None:
    title = (ws.title or "").strip()
    if title not in ("未命名项目", "智剪项目", ""):
        return
    snippet = user_message.strip().replace("\n", " ")[:32]
    if len(snippet) >= 4:
        await session_store.update_session_title(session_id, snippet)


def _plan_title(ctx: AgentContext, plan_id: str) -> str:
    raw = next((p for p in ctx.workspace.plans if str(p.get("plan_id")) == plan_id), None)
    if not raw:
        return plan_id
    return str(raw.get("title") or plan_id)


def _confirm_preview(tool_name: str, args: dict[str, Any], ctx: AgentContext) -> str:
    plan_id = str(args.get("plan_id") or ctx.workspace.active_plan_id or "").strip()
    title = _plan_title(ctx, plan_id) if plan_id else "当前方案"
    if tool_name == "realize_plan":
        tts = "（TTS 配音）" if args.get("force_tts_pipeline") else ""
        return f"将按方案「{title}」渲染成片{tts}，含字幕与混音，预计耗时数分钟。"
    if tool_name == "export_jianying_draft":
        return f"将方案「{title}」导出为剪映草稿（ZIP 或写入剪映目录）。"
    if tool_name == "start_process_job":
        return "将开始处理选中素材（抽帧/ASR/向量等），耗时较长。"
    return f"将执行 {tool_name}"


def _export_prerequisite_error(intent: ExportIntent, ws) -> str | None:
    if not ws.plans:
        return "当前还没有剪辑方案。请先说剪辑诉求让我生成方案，例如：「用选中素材做 60 秒口播方案」。"
    plan_id = (ws.active_plan_id or "").strip()
    if not plan_id and ws.plans:
        plan_id = str(ws.plans[0].get("plan_id") or "")
    if not plan_id:
        return "未找到可用方案 ID，请重新生成方案后再试。"
    if intent.kind in ("realize", "tts_realize", "jianying"):
        if not any(str(p.get("plan_id")) == plan_id for p in ws.plans):
            return f"方案 {plan_id} 不存在，请重新生成或选中方案。"
    return None


def _build_export_tool_call(intent: ExportIntent, ws) -> tuple[str, dict[str, Any]]:
    plan_id = str(ws.active_plan_id or (ws.plans[0].get("plan_id") if ws.plans else "") or "")
    if intent.kind == "jianying":
        return "export_jianying_draft", {
            "plan_id": plan_id,
            "force_tts_pipeline": intent.force_tts_pipeline,
        }
    return "realize_plan", {
        "plan_id": plan_id,
        "force_tts_pipeline": intent.force_tts_pipeline,
    }


async def _finish_tool_result(
    session_id: str,
    *,
    call_id: str,
    tool_name: str,
    args: dict[str, Any],
    result: ToolResult,
) -> AsyncIterator[bytes]:
    payload: dict[str, Any] = {
        "call_id": call_id,
        "ok": result.ok,
        "summary": result.summary,
    }
    if result.artifact:
        art = result.artifact.model_dump()
        payload["artifact"] = art
        yield _sse("artifact", art)
        await _persist_artifact_message(session_id, art)
    if result.error:
        payload["error"] = result.error
    if result.next_suggestions:
        payload["suggestions"] = result.next_suggestions
        yield _sse("suggestions", {"items": result.next_suggestions})
    await _persist_tool_message(
        session_id,
        call_id=call_id,
        name=tool_name,
        status="done" if result.ok else "failed",
        summary=result.summary or result.error or "",
        input_data=args,
    )
    yield _sse("tool_end", payload)
    yield _sse(
        "message_delta",
        {"content": result.summary if result.ok else f"操作失败：{result.error}"},
    )


async def _dispatch_tool(
    *,
    session_id: str,
    tool_name: str,
    args: dict[str, Any],
    ctx: AgentContext,
    call_id: str | None = None,
) -> AsyncIterator[bytes]:
    """执行工具；L2/L3 则暂停并等待用户确认。"""
    spec = REGISTRY.get(tool_name)
    if not spec:
        yield _sse("error", {"detail": f"未知工具 {tool_name}"})
        yield _sse("done", {"idle_reason": "unknown_tool"})
        return

    cid = call_id or str(uuid.uuid4())
    if needs_confirm(spec, ctx):
        preview = _confirm_preview(tool_name, args, ctx)
        await session_store.save_pending_confirm(
            call_id=cid,
            session_id=session_id,
            tool_name=tool_name,
            input_json=args,
            risk=spec.risk,
        )
        yield _sse(
            "confirm_required",
            {
                "call_id": cid,
                "tool": tool_name,
                "input": args,
                "risk": spec.risk,
                "preview": preview,
            },
        )
        yield _sse("message_delta", {"content": f"需要确认：{preview}\n请点击下方「确认执行」继续。"})
        yield _sse("done", {"pending_confirm": cid})
        return

    yield _sse("tool_start", {"call_id": cid, "name": tool_name, "input": args})
    await _maybe_checkpoint(session_id, tool_name)
    result = await invoke(tool_name, args, ctx)
    await _apply_tool_result(session_id, result, ctx)
    async for chunk in _finish_tool_result(
        session_id, call_id=cid, tool_name=tool_name, args=args, result=result
    ):
        yield chunk
    yield _sse("done", {})


async def _handle_export_intent(
    session_id: str,
    intent: ExportIntent,
    ctx: AgentContext,
) -> AsyncIterator[bytes]:
    err = _export_prerequisite_error(intent, ctx.workspace)
    if err:
        yield _sse("message_delta", {"content": err})
        await session_store.persist_studio_message(
            session_id, {"studio_type": "assistant", "text": err}
        )
        yield _sse("done", {"idle_reason": "missing_prerequisite", "detail": err})
        return

    tool_name, args = _build_export_tool_call(intent, ctx.workspace)
    async for chunk in _dispatch_tool(
        session_id=session_id,
        tool_name=tool_name,
        args=args,
        ctx=ctx,
    ):
        yield chunk


async def _run_confirmed_tool(
    *,
    session_id: str,
    tool_name: str,
    args: dict[str, Any],
    ctx: AgentContext,
) -> AsyncIterator[bytes]:
    call_id = str(uuid.uuid4())
    spec = REGISTRY.get(tool_name)
    if not spec:
        yield _sse("error", {"detail": f"未知工具 {tool_name}"})
        yield _sse("done", {})
        return

    yield _sse("tool_start", {"call_id": call_id, "name": tool_name, "input": args})
    await _maybe_checkpoint(session_id, tool_name)
    result = await invoke(tool_name, args, ctx)
    await _apply_tool_result(session_id, result, ctx)
    async for chunk in _finish_tool_result(
        session_id,
        call_id=call_id,
        tool_name=tool_name,
        args=args,
        result=result,
    ):
        yield chunk
    yield _sse("done", {})


async def run_chat_turn(session_id: str, req: ChatRequest) -> AsyncIterator[bytes]:
    register_all_tools()

    ws = await session_store.get_session(session_id)
    if not ws:
        yield _sse("error", {"detail": "会话不存在"})
        yield _sse("done", {})
        return

    if not req.resume_call_id:
        preview = req.message.strip().replace("\n", " ")[:40]
        await session_store.push_checkpoint(session_id, f"对话: {preview}")

    msg_id = await session_store.persist_studio_message(
        session_id, {"studio_type": "user", "text": req.message}
    )
    if not req.resume_call_id:
        yield _sse("user_message", {"id": msg_id, "text": req.message})
    await _maybe_autotitle(session_id, req.message, ws)

    ctx = AgentContext(session_id=session_id, workspace=ws)
    summary = build_workspace_summary(ws)

    preflight = await run_intent_preflight(
        req.message,
        selected_video_ids=list(ws.selected_video_ids or []),
    )
    if preflight and preflight.get("workspace_patch"):
        ctx.workspace = await session_store.patch_workspace(
            session_id, preflight["workspace_patch"]
        )
        ws = ctx.workspace
        summary = build_workspace_summary(ws)
        note = preflight.get("note")
        if note:
            yield _sse("message_delta", {"content": note + "\n\n"})

    history = await session_store.list_messages(session_id, limit=20)
    history_text = ""
    for item in history[-10:]:
        role = item.get("role")
        content = item.get("content") or {}
        text = content.get("text") or content.get("summary") or ""
        if content.get("studio_type") == "user":
            text = content.get("text") or text
        if role in ("user", "assistant") and text:
            history_text += f"{role}: {text[:500]}\n"

    # 恢复已确认的 pending tool
    if req.resume_call_id:
        pending = await session_store.pop_pending_confirm(req.resume_call_id)
        if not pending:
            yield _sse("error", {"detail": "确认已过期或不存在"})
            yield _sse("done", {})
            return
        if not req.confirm_approved:
            yield _sse("message_delta", {"content": "已取消该操作。"})
            yield _sse("done", {})
            return
        async for chunk in _run_confirmed_tool(
            session_id=session_id,
            tool_name=pending["tool_name"],
            args=pending["input_json"],
            ctx=ctx,
        ):
            yield chunk
        return

    export_intent = detect_export_intent(req.message)
    if export_intent:
        async for chunk in _handle_export_intent(session_id, export_intent, ctx):
            yield chunk
        return

    route_out = await classify_route(user_message=req.message, workspace_summary=summary)
    yield _sse("route", route_out.model_dump())

    planner_note = ""
    if route_out.route == "plan":
        plan_out = await build_task_plan(user_message=req.message, workspace_summary=summary)
        yield _sse("plan_steps", plan_out.model_dump())
        if plan_out.steps:
            planner_note = "建议步骤：\n" + "\n".join(
                f"{s.id}. {s.title} (tool={s.tool})" for s in plan_out.steps
            )

    if route_out.route == "clarify":
        route_out.route = "execute"

    cfg = await _load_llm_cfg()
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=cfg["api_key"],
        base_url=cfg["base_url"],
        timeout=float(cfg.get("timeout") or 600),
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": EXECUTOR_SYSTEM},
        {
            "role": "user",
            "content": (
                f"【工作区】\n{summary}\n\n"
                f"【近期对话】\n{history_text or '（无）'}\n\n"
                f"{planner_note}\n\n"
                f"【当前用户消息】\n{req.message}\n\n"
                f"（ReAct 最多 {MAX_TOOL_ROUNDS} 轮工具调用，请合理规划步骤。）"
            ),
        },
    ]

    tools = get_openai_tools()

    try:
        for round_idx in range(MAX_TOOL_ROUNDS):
            try:
                resp = await client.chat.completions.create(
                    model=cfg["model"],
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=cfg.get("temperature", 0.5),
                    max_tokens=cfg.get("max_tokens", 4096),
                )
            except Exception as e:
                logger.exception("executor LLM call failed")
                detail = f"模型调用失败：{e}。请检查「设置」中的 LLM API 地址、密钥与模型名。"
                yield _sse("error", {"detail": detail})
                yield _sse("message_delta", {"content": detail})
                await session_store.persist_studio_message(
                    session_id, {"studio_type": "assistant", "text": detail}
                )
                yield _sse("done", {"idle_reason": "llm_error"})
                return

            choice = resp.choices[0]
            msg = choice.message

            if msg.content:
                for evt, payload in _emit_content_chunks(msg.content):
                    yield _sse(evt, payload)

            tool_calls = msg.tool_calls or []
            if not tool_calls:
                final_text = msg.content or ""
                await session_store.persist_studio_message(
                    session_id,
                    {"studio_type": "assistant", "text": final_text},
                )
                done_payload: dict[str, Any] = {"rounds_used": round_idx}
                if detect_export_intent(req.message) and not final_text.strip():
                    hint = (
                        "已收到导出指令，但助手未执行工具。"
                        "请再说「导出成片」或点击方案区「一键成片」；"
                        "若需 Agent 导出，请确认 LLM 配置正常。"
                    )
                    done_payload["idle_reason"] = "no_tool_for_export_intent"
                    done_payload["detail"] = hint
                    yield _sse("message_delta", {"content": hint})
                elif detect_export_intent(req.message):
                    done_payload["idle_reason"] = "model_text_only"
                    done_payload["detail"] = (
                        "助手仅回复了文字，未调用成片工具。"
                        "请再说「导出成片」或使用右侧方案区的「一键成片」。"
                    )
                yield _sse("done", done_payload)
                return

            messages.append(msg.model_dump())

            for tc in tool_calls:
                fn = tc.function
                name = fn.name or ""
                try:
                    args = json.loads(fn.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}

                call_id = tc.id or str(uuid.uuid4())
                spec = REGISTRY.get(name)
                if spec and needs_confirm(spec, ctx):
                    preview = _confirm_preview(name, args, ctx)
                    await session_store.save_pending_confirm(
                        call_id=call_id,
                        session_id=session_id,
                        tool_name=name,
                        input_json=args,
                        risk=spec.risk,
                    )
                    yield _sse(
                        "confirm_required",
                        {
                            "call_id": call_id,
                            "tool": name,
                            "input": args,
                            "risk": spec.risk,
                            "preview": preview,
                        },
                    )
                    yield _sse(
                        "message_delta",
                        {"content": f"需要确认：{preview}\n请点击下方「确认执行」继续。"},
                    )
                    yield _sse("done", {"pending_confirm": call_id})
                    return

                yield _sse(
                    "tool_start",
                    {"call_id": call_id, "name": name, "input": args, "round": round_idx + 1},
                )
                await _maybe_checkpoint(session_id, name)
                result = await invoke(name, args, ctx)
                await _apply_tool_result(session_id, result, ctx)
                async for chunk in _finish_tool_result(
                    session_id,
                    call_id=call_id,
                    tool_name=name,
                    args=args,
                    result=result,
                ):
                    yield chunk

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(
                            result.model_dump(),
                            ensure_ascii=False,
                        ),
                    }
                )

            if choice.finish_reason == "stop":
                break
    except Exception as e:
        logger.exception("executor loop failed")
        detail = f"对话执行异常：{e}"
        yield _sse("error", {"detail": detail})
        yield _sse("done", {"idle_reason": "executor_error"})
        return

    limit_msg = (
        f"\n\n（已达 {MAX_TOOL_ROUNDS} 轮工具调用上限；如需继续请补充说明或指定下一步。）"
    )
    yield _sse("message_delta", {"content": limit_msg})
    await session_store.persist_studio_message(
        session_id,
        {"studio_type": "assistant", "text": limit_msg.strip()},
    )
    yield _sse("done", {"rounds_used": MAX_TOOL_ROUNDS, "limit_reached": True})
