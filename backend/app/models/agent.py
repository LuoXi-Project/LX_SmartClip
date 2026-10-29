from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

PipelinePhase = Literal["idle", "ingest", "process", "match", "plan", "realize", "export"]
ToolRisk = Literal["L0", "L1", "L2", "L3"]
ArtifactType = Literal["plan", "match_results", "process_job", "export", "video"]
AgentRoute = Literal["plan", "execute", "ask", "clarify"]

# 执行权限档位：ask=每次询问（默认） / auto=自动审核 / full=完全访问
AgentPermissionMode = Literal["ask", "auto", "full"]


class AgentPermissions(BaseModel):
    mode: AgentPermissionMode = "ask"
    """本会话内已授权、不再逐次确认的工具名（L3 除外）"""
    session_granted: list[str] = Field(default_factory=list)


class WorkspaceState(BaseModel):
    session_id: str
    title: str = "未命名项目"
    selected_video_ids: list[str] = Field(default_factory=list)
    pipeline_phase: PipelinePhase = "idle"
    active_plan_id: Optional[str] = None
    plans: list[dict[str, Any]] = Field(default_factory=list)
    match_segments: list[dict[str, Any]] = Field(default_factory=list)
    jobs: dict[str, Any] = Field(
        default_factory=lambda: {
            "process_task_ids": [],
            "film_job_id": None,
            "realize_job_id": None,
        }
    )
    user_preferences: dict[str, Any] = Field(default_factory=dict)
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)
    last_exports: list[dict[str, Any]] = Field(default_factory=list)
    permissions: AgentPermissions = Field(default_factory=AgentPermissions)


class CreateSessionRequest(BaseModel):
    title: Optional[str] = None
    video_ids: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    resume_call_id: Optional[str] = None
    confirm_approved: Optional[bool] = None
    """确认执行时勾选「本会话不再询问」：把该工具写入 permissions.session_granted"""
    grant_session: bool = False


class ConfirmRequest(BaseModel):
    call_id: str
    approved: bool


class ArtifactRef(BaseModel):
    type: ArtifactType
    id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    ok: bool
    summary: str
    artifact: Optional[ArtifactRef] = None
    workspace_patch: Optional[dict[str, Any]] = None
    job_id: Optional[str] = None
    next_suggestions: list[str] = Field(default_factory=list)
    error: Optional[str] = None


class SessionResponse(BaseModel):
    session_id: str
    workspace: WorkspaceState


class PlannerStep(BaseModel):
    id: str
    title: str
    tool: str
    depends_on: list[str] = Field(default_factory=list)


class PlannerOutput(BaseModel):
    steps: list[PlannerStep] = Field(default_factory=list)
    estimated_minutes: int = 5


class SessionListItem(BaseModel):
    session_id: str
    title: str
    pipeline_phase: PipelinePhase = "idle"
    created_at: str
    updated_at: str
    message_count: int = 0
    preview: str = ""


class SessionListResponse(BaseModel):
    sessions: list[SessionListItem] = Field(default_factory=list)


class RollbackResponse(BaseModel):
    ok: bool
    label: str = ""
    workspace: WorkspaceState


class ClearMessagesResponse(BaseModel):
    ok: bool
    deleted: int = 0


class RouterOutput(BaseModel):
    route: AgentRoute
    reason: str = ""
