from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent import mcp_manager, prefs, session_store, skills
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


# ── Agent 技能包 ──────────────────────────────────────────────────────────


@router.get("/skills")
async def list_skills():
    return {"items": await skills.list_skills()}


@router.get("/skills/{slug}/content")
async def get_skill_content(slug: str):
    content = skills.load_skill_content(slug)
    if content is None:
        raise HTTPException(status_code=404, detail=f"技能 {slug} 不存在")
    return {"slug": slug, "content": content}


class SkillCreateRequest(BaseModel):
    name: str
    description: str = ""
    body: str
    slug: str | None = None


@router.post("/skills")
async def create_skill(req: SkillCreateRequest):
    try:
        created = await skills.create_skill(
            name=req.name, description=req.description, body=req.body, slug=req.slug
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, **created}


@router.patch("/skills/{slug}")
async def toggle_skill(slug: str, patch: dict[str, Any]):
    enabled = patch.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=400, detail="需要布尔字段 enabled")
    ok = await skills.set_skill_enabled(slug, enabled)
    if not ok:
        raise HTTPException(status_code=404, detail=f"技能 {slug} 不存在")
    return {"ok": True, "slug": slug, "enabled": enabled}


@router.delete("/skills/{slug}")
async def delete_skill(slug: str):
    info = await skills.list_skills()
    builtin = {s["slug"] for s in info if s["source"] == "builtin"}
    if slug in builtin and not any(
        s["slug"] == slug and s["source"] == "user" for s in info
    ):
        raise HTTPException(status_code=400, detail="内置技能不可删除，可停用")
    ok = await skills.delete_skill(slug)
    if not ok:
        raise HTTPException(status_code=404, detail=f"技能 {slug} 不存在")
    return {"ok": True}


class SkillImportRequest(BaseModel):
    """从 URL / GitHub / 本地路径导入技能（与 agent install_skill 工具共用底层）。"""
    source_type: str
    url: str = ""
    repo: str = ""
    path: str = ""
    local_path: str = ""
    slug: str | None = None
    enable: bool | None = None


@router.post("/skills/import")
async def import_skill(req: SkillImportRequest):
    try:
        info = await skills.install_skill_from_source(
            source_type=req.source_type,
            url=req.url,
            repo=req.repo,
            path=req.path,
            local_path=req.local_path,
            slug=req.slug,
            enable=req.enable,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, **info}


# ── Agent MCP 服务 ─────────────────────────────────────────────────────────


@router.get("/mcp/servers")
async def list_mcp_servers():
    return {"items": await mcp_manager.list_servers()}


class McpServerRequest(BaseModel):
    id: str | None = None
    name: str = ""
    transport: str = "stdio"
    command: str = ""
    args: list[str] = []
    env: dict[str, str] = {}
    url: str = ""
    headers: dict[str, str] = {}
    enabled: bool = True
    trusted: bool = False
    timeout_sec: int = 60


@router.post("/mcp/servers")
async def upsert_mcp_server(req: McpServerRequest):
    try:
        saved = await mcp_manager.upsert_server(req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "server": saved}


@router.patch("/mcp/servers/{server_id}")
async def patch_mcp_server(server_id: str, patch: dict[str, Any]):
    servers = await mcp_manager.list_servers()
    current = next((s for s in servers if s["id"] == server_id), None)
    if not current:
        raise HTTPException(status_code=404, detail=f"MCP 服务 {server_id} 不存在")
    merged = {**current, **{k: v for k, v in patch.items() if k in current}}
    try:
        saved = await mcp_manager.upsert_server(merged)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "server": saved}


@router.delete("/mcp/servers/{server_id}")
async def delete_mcp_server(server_id: str):
    ok = await mcp_manager.delete_server(server_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"MCP 服务 {server_id} 不存在")
    return {"ok": True}


@router.post("/mcp/servers/test")
async def test_mcp_server(req: McpServerRequest):
    """测试连接：从零建立连接并列出工具（不写配置）。"""
    return await mcp_manager.test_server(req.model_dump())


# ── Agent 行为偏好 ─────────────────────────────────────────────────────────


@router.get("/prefs")
async def get_agent_prefs():
    return {"cot_enabled": await prefs.load_cot_enabled()}


class AgentPrefsUpdate(BaseModel):
    cot_enabled: bool | None = None


@router.patch("/prefs")
async def update_agent_prefs(req: AgentPrefsUpdate):
    if req.cot_enabled is not None:
        await prefs.save_cot_enabled(req.cot_enabled)
    return {"ok": True, "cot_enabled": await prefs.load_cot_enabled()}
