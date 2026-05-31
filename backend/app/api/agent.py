from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.agent import session_store
from app.agent.orchestrator import run_chat_turn
from app.models.agent import (
    ChatRequest,
    ClearMessagesResponse,
    ConfirmRequest,
    CreateSessionRequest,
    RollbackResponse,
    SessionListResponse,
    SessionResponse,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(limit: int = 50):
    rows = await session_store.list_sessions(limit=limit)
    return SessionListResponse(sessions=rows)


@router.post("/sessions", response_model=SessionResponse)
async def create_session(req: CreateSessionRequest) -> SessionResponse:
    ws = await session_store.create_session(
        title=req.title,
        video_ids=req.video_ids,
    )
    return SessionResponse(session_id=ws.session_id, workspace=ws)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    ws = await session_store.get_session(session_id)
    if not ws:
        raise HTTPException(status_code=404, detail="会话不存在")
    return SessionResponse(session_id=session_id, workspace=ws)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    ok = await session_store.delete_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@router.patch("/sessions/{session_id}/workspace", response_model=SessionResponse)
async def patch_workspace(session_id: str, patch: dict[str, Any]) -> SessionResponse:
    try:
        ws = await session_store.patch_workspace(session_id, patch)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return SessionResponse(session_id=session_id, workspace=ws)


@router.get("/sessions/{session_id}/messages")
async def list_messages(session_id: str, limit: int = 200):
    ws = await session_store.get_session(session_id)
    if not ws:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"messages": await session_store.list_messages(session_id, limit=limit)}


@router.post("/sessions/{session_id}/clear-messages", response_model=ClearMessagesResponse)
async def clear_messages(session_id: str):
    ws = await session_store.get_session(session_id)
    if not ws:
        raise HTTPException(status_code=404, detail="会话不存在")
    deleted = await session_store.clear_messages(session_id)
    return ClearMessagesResponse(ok=True, deleted=deleted)


@router.post("/sessions/{session_id}/reset", response_model=SessionResponse)
async def reset_session(session_id: str):
    """清空对话并重置工作区（保留会话 ID 与标题）。"""
    try:
        ws = await session_store.reset_workspace(session_id, keep_title=True)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return SessionResponse(session_id=session_id, workspace=ws)


@router.post("/sessions/{session_id}/rollback", response_model=RollbackResponse)
async def rollback_session(session_id: str):
    try:
        ws, label = await session_store.rollback_one_step(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return RollbackResponse(ok=True, label=label, workspace=ws)


@router.post("/sessions/{session_id}/rollback-to/{message_id}", response_model=RollbackResponse)
async def rollback_session_to_message(session_id: str, message_id: str):
    try:
        ws, label = await session_store.rollback_to_message(session_id, message_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return RollbackResponse(ok=True, label=label, workspace=ws)


@router.post("/sessions/{session_id}/chat")
async def chat(session_id: str, req: ChatRequest):
    ws = await session_store.get_session(session_id)
    if not ws:
        raise HTTPException(status_code=404, detail="会话不存在")
    return StreamingResponse(
        run_chat_turn(session_id, req),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/sessions/{session_id}/confirm")
async def confirm_tool(session_id: str, req: ConfirmRequest):
    if not req.approved:
        await session_store.pop_pending_confirm(req.call_id)
        return {"ok": True, "approved": False}
    pending = await session_store.pop_pending_confirm(req.call_id)
    if not pending or pending["session_id"] != session_id:
        raise HTTPException(status_code=404, detail="确认不存在")
    return {
        "ok": True,
        "approved": True,
        "resume": {
            "call_id": req.call_id,
            "tool": pending["tool_name"],
            "input": pending["input_json"],
        },
    }
