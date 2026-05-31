# Agent Studio（智剪工作台）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `/studio` 对话式全流程工作台，通过 Agent Tool 编排现有 SmartClip API，实现「选视频 → 处理 → 生成 Plan → 编辑 → 成片」P0 闭环。

**Architecture:** 后端 `app/agent/` 提供 Session + Orchestrator（Router/Planner/Executor）+ Tool Registry；前端三栏 Studio UI 通过 SSE 接收消息与 Artifact；Workspace 存 SQLite，长任务复用 process-jobs WebSocket。

**Tech Stack:** FastAPI, aiosqlite, OpenAI-compatible tools API, Next.js 14 App Router, Zustand, 现有 `lib/api.ts` 契约。

**Design spec:** `docs/superpowers/specs/2026-05-31-agent-studio-design.md`

---

## File Map（P0 将创建/修改的文件）

| 路径 | 职责 |
|------|------|
| `backend/app/db/init_db.py` | 新增 agent 三表 |
| `backend/app/models/agent.py` | Pydantic：Workspace、SSE、Tool、Confirm |
| `backend/app/agent/session_store.py` | CRUD session/messages |
| `backend/app/agent/tool_registry.py` | 注册、风险、schema |
| `backend/app/agent/context_builder.py` | workspace 摘要 |
| `backend/app/agent/tools/*.py` | 各 tool 实现 |
| `backend/app/agent/orchestrator.py` | 主循环 + SSE 生成 |
| `backend/app/agent/router.py` | Router LLM 调用 |
| `backend/app/agent/planner.py` | Planner LLM 调用 |
| `backend/app/agent/prompts/*.py` | system prompts |
| `backend/app/api/agent.py` | HTTP 路由 |
| `backend/app/main.py` | mount agent router |
| `frontend/lib/agent-types.ts` | TS 类型 |
| `frontend/lib/agent-api.ts` | SSE 客户端 |
| `frontend/lib/studio-store.ts` | Zustand |
| `frontend/app/studio/page.tsx` | 工作台页面 |
| `frontend/app/studio/_components/*` | 三栏 UI |
| `frontend/app/_components/TopNav.tsx` | 导航改 /studio |
| `frontend/app/layout.tsx` | 移除 AIChatPanel |
| `frontend/app/page.tsx` | CTA → /studio |

---

# Phase P0 — 可交付闭环（优先完成本节全部 Task）

## Task 1: 数据库与模型

**Files:**
- Modify: `backend/app/db/init_db.py`
- Create: `backend/app/models/agent.py`

- [ ] **Step 1: 在 init_db.py 添加表定义**

在 `CREATE_PROCESS_TASKS` 之后追加：

```python
CREATE_AGENT_SESSIONS = """
CREATE TABLE IF NOT EXISTS agent_sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '未命名项目',
    workspace_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

CREATE_AGENT_MESSAGES = """
CREATE TABLE IF NOT EXISTS agent_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
);
"""

CREATE_AGENT_PENDING_CONFIRMS = """
CREATE TABLE IF NOT EXISTS agent_pending_confirms (
    call_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    input_json TEXT NOT NULL,
    risk TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
);
"""
```

在 `init_database()` 的 `executescript` 列表中加入这三条。

- [ ] **Step 2: 创建 models/agent.py**

```python
from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

PipelinePhase = Literal["idle", "ingest", "process", "match", "plan", "realize", "export"]
ToolRisk = Literal["L0", "L1", "L2", "L3"]

class WorkspaceState(BaseModel):
    session_id: str
    title: str = "未命名项目"
    selected_video_ids: list[str] = Field(default_factory=list)
    pipeline_phase: PipelinePhase = "idle"
    active_plan_id: Optional[str] = None
    plans: list[dict[str, Any]] = Field(default_factory=list)
    match_segments: list[dict[str, Any]] = Field(default_factory=list)
    jobs: dict[str, Any] = Field(default_factory=lambda: {
        "process_task_ids": [],
        "film_job_id": None,
        "realize_job_id": None,
    })
    user_preferences: dict[str, Any] = Field(default_factory=dict)
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)
    last_exports: list[dict[str, Any]] = Field(default_factory=list)

class CreateSessionRequest(BaseModel):
    title: Optional[str] = None
    video_ids: list[str] = Field(default_factory=list)

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    skip_confirm: bool = False  # 开发调试用

class ConfirmRequest(BaseModel):
    call_id: str
    approved: bool

class ArtifactRef(BaseModel):
    type: Literal["plan", "match_results", "process_job", "export", "video"]
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
```

- [ ] **Step 3: 重启后端验证表存在**

Run: `cd backend && python -c "import asyncio; from app.db.init_db import init_database; asyncio.run(init_database())"`  
Expected: 无异常；用 sqlite3 查看 `agent_sessions` 表存在。

---

## Task 2: Session Store

**Files:**
- Create: `backend/app/agent/__init__.py`
- Create: `backend/app/agent/session_store.py`

- [ ] **Step 1: 实现 session_store.py**

核心函数：

```python
async def create_session(title: str | None, video_ids: list[str]) -> WorkspaceState
async def get_session(session_id: str) -> WorkspaceState | None
async def patch_workspace(session_id: str, patch: dict) -> WorkspaceState
async def append_message(session_id: str, role: str, content: dict) -> str
async def list_messages(session_id: str, limit: int = 50) -> list[dict]
```

`create_session` 生成 uuid，`workspace_json` 默认 `WorkspaceState.model_dump()`。

`patch_workspace` 对 `plans`、`selected_video_ids` 等做浅合并（dict update）。

- [ ] **Step 2: 空会话冒烟**

Run Python one-liner：create → get → patch `title` → 断言 title 已变。

---

## Task 3: Tool Registry 骨架 + L0 工具

**Files:**
- Create: `backend/app/agent/tool_registry.py`
- Create: `backend/app/agent/tools/__init__.py`
- Create: `backend/app/agent/tools/videos.py`
- Create: `backend/app/agent/tools/workspace.py`

- [ ] **Step 1: tool_registry.py**

```python
@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON Schema
    risk: ToolRisk
    handler: Callable[..., Awaitable[ToolResult]]

REGISTRY: dict[str, ToolSpec] = {}

def register(spec: ToolSpec) -> None: ...
def get_openai_tools() -> list[dict]: ...  # 转为 OpenAI tools 格式
async def invoke(name: str, args: dict, ctx: AgentContext) -> ToolResult: ...
```

`AgentContext` 含：`session_id`, `workspace`, `db`, `api_base_url`, `confirm_granted: set[str]`。

- [ ] **Step 2: 实现 list_videos / get_video_status**

从 `app.db.database` 查询 `videos` 表；`get_video_status` 附加 `status`, `total_clips`, `duration`。

- [ ] **Step 3: 实现 get_workspace_state / set_selected_videos**

后者返回 `workspace_patch: {"selected_video_ids": [...]}`。

- [ ] **Step 4: 注册 4 个 L0/L1 工具**

在 `tools/__init__.py` 的 `register_all_tools()` 中注册，应用启动时调用（或在 orchestrator 首次使用时懒加载）。

---

## Task 4: P0 执行类工具（process + plan + realize）

**Files:**
- Create: `backend/app/agent/tools/process_tool.py`
- Create: `backend/app/agent/tools/auto_edit_tool.py`
- Modify: 视需要抽取 `backend/app/api/auto_edit.py` 中可复用的 async 函数为 service（避免 orchestrator 发 HTTP）

- [ ] **Step 1: start_process_job**

调用逻辑对齐 `POST /api/videos/{video_id}/process-jobs`：

- 输入：`video_id`（必填）
- 返回：`job_id`，`workspace_patch.jobs.process_task_ids` 追加
- `pipeline_phase` → `process`

**注意：** 不阻塞等待完成；返回 summary 提示用户「处理已开始」。

- [ ] **Step 2: generate_auto_edit_plan**

输入：`video_ids`, `user_prompt`, 可选 `target_duration_sec`, `num_plans`。

内部调用 `call_llm_for_plans` 或现有 plan 生成入口（从 `auto_edit.py` import）。

输出 Artifact：`type=plan`，payload 为第一个 plan；`workspace_patch.plans` 追加，`active_plan_id` 设置。

- [ ] **Step 3: apply_plan_patch**

输入：`plan_id`, `patch`（dict，segment 级替换/删除/插入）。

校验 `plan_id` 属于当前 workspace；合并后写回 `plans`。

- [ ] **Step 4: realize_plan**

输入：`plan_id`，可选字幕/BGM 参数（从 `user_preferences` 默认）。

调用 `auto_edit` realize 路径；返回 `job_id` 或 direct download info；`pipeline_phase` → `realize`。

- [ ] **Step 5: 手动 API 验证**

用 curl 创建 session 后，在 orchestrator 完成前可用临时脚本直接 `await invoke("generate_auto_edit_plan", ...)` 验证 ToolResult 结构。

---

## Task 5: Context Builder + Prompts

**Files:**
- Create: `backend/app/agent/context_builder.py`
- Create: `backend/app/agent/prompts/router.py`
- Create: `backend/app/agent/prompts/planner.py`
- Create: `backend/app/agent/prompts/executor.py`

- [ ] **Step 1: context_builder.build_workspace_summary(ws) -> str**

输出 Markdown 要点：< 1500 字符：

- 阶段、选中视频数与 id 列表、是否有 plan、active_plan_id、进行中的 job_ids

- [ ] **Step 2: 编写三个 system prompt 文件**

- Router：只输出 JSON `{route, reason}`
- Planner：只输出 JSON `{steps[], estimated_minutes}`
- Executor：角色为剪辑助手；工具使用规则；禁止编造 clip_id；L2/L3 说明

- [ ] **Step 3: 单元冒烟**

传入 dummy workspace，断言 summary 非空且包含 `pipeline_phase`。

---

## Task 6: Router + Planner + Orchestrator

**Files:**
- Create: `backend/app/agent/router.py`
- Create: `backend/app/agent/planner.py`
- Create: `backend/app/agent/orchestrator.py`

- [ ] **Step 1: router.classify(messages, workspace_summary) -> dict**

使用 `LLMClient` + `response_utils.extract_json_object`（与 `auto_edit` 一致）。

- [ ] **Step 2: planner.plan(user_goal, workspace_summary) -> dict**

返回 steps 列表。

- [ ] **Step 3: orchestrator.run_chat_turn(session_id, user_message) -> AsyncIterator[bytes]**

伪代码：

```python
async def run_chat_turn(...):
    yield sse("route", ...)
    if route == "plan":
        plan = await planner.plan(...)
        yield sse("plan_steps", plan)
    # executor loop
    while tool_calls_remaining:
        response = await llm.chat_with_tools(...)
        for tc in tool_calls:
            if needs_confirm(tc): yield sse("confirm_required"); wait confirm
            yield sse("tool_start", ...)
            result = await registry.invoke(...)
            yield sse("tool_end", ...)
            if result.artifact: yield sse("artifact", ...)
            if result.workspace_patch: await patch; yield sse("workspace_patch", ...)
    yield sse("done", {})
```

- [ ] **Step 4: 确认挂起**

`confirm_required` 时：

- 写入 `agent_pending_confirms`
- 中断本轮；`POST /confirm` 后恢复执行（P0 可先同步：前端 confirm 后同连接继续，或 P0 简化为一轮一次 confirm 需重新发消息——**推荐 P0**：confirm 在同 session 存 `approved_call_ids`，用户 confirm 后 POST `/chat` 带 `resume_call_id`）

**P0 简化确认流：**

```python
class ChatRequest(BaseModel):
    message: str
    resume_call_id: Optional[str] = None
    confirm_approved: Optional[bool] = None
```

若 `resume_call_id` 存在，跳过 Router，直接执行 pending tool。

- [ ] **Step 5: SSE 编码辅助**

```python
def sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()
```

---

## Task 7: Agent HTTP API

**Files:**
- Create: `backend/app/api/agent.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: 路由**

```python
router = APIRouter(prefix="/api/agent", tags=["agent"])

@router.post("/sessions")
async def create_session(req: CreateSessionRequest): ...

@router.get("/sessions/{session_id}")
async def get_session(session_id: str): ...

@router.patch("/sessions/{session_id}/workspace")
async def patch_workspace(session_id: str, patch: dict): ...

@router.get("/sessions/{session_id}/messages")
async def list_messages(session_id: str): ...

@router.post("/sessions/{session_id}/chat")
async def chat(session_id: str, req: ChatRequest):
    return StreamingResponse(orchestrator.run_chat_turn(...), media_type="text/event-stream")
```

- [ ] **Step 2: main.py 注册**

```python
from app.api.agent import router as agent_router
app.include_router(agent_router)
```

- [ ] **Step 3: curl 验证 SSE**

```bash
curl -N -X POST http://127.0.0.1:8000/api/agent/sessions -H "Content-Type: application/json" -d "{\"video_ids\":[]}"
# 记下 session_id
curl -N -X POST http://127.0.0.1:8000/api/agent/sessions/<id>/chat -H "Content-Type: application/json" -d "{\"message\":\"列出素材库视频\"}"
```

Expected: 看到 `event: tool_start` / `tool_end` / `event: done`。

---

## Task 8: 前端类型与 SSE 客户端

**Files:**
- Create: `frontend/lib/agent-types.ts`
- Create: `frontend/lib/agent-api.ts`

- [ ] **Step 1: agent-types.ts**

定义 `WorkspaceState`, `StudioMessage`, `SseEvent`, `ArtifactRef` 与 spec 一致。

- [ ] **Step 2: agent-api.ts**

```typescript
export async function createAgentSession(body: { title?: string; video_ids?: string[] })
export async function getAgentSession(sessionId: string)
export function streamAgentChat(
  sessionId: string,
  body: { message: string; resume_call_id?: string; confirm_approved?: boolean },
  handlers: {
    onEvent: (event: string, data: unknown) => void
    onError: (err: Error) => void
    signal?: AbortSignal
  }
): Promise<void>
```

`streamAgentChat` 使用 `fetch` + `ReadableStream`，解析 `event:` / `data:` 行（参考 `AIChatPanel` 的 SSE 解析，改为通用 event 名）。

- [ ] **Step 3: 在浏览器 Network 面板验证事件解析**

---

## Task 9: Studio Store + 页面骨架

**Files:**
- Create: `frontend/lib/studio-store.ts`
- Create: `frontend/app/studio/page.tsx`
- Create: `frontend/app/studio/_components/StudioLayout.tsx`
- Create: `frontend/app/studio/_components/StudioThread.tsx`
- Create: `frontend/app/studio/_components/ArtifactCanvas.tsx`
- Create: `frontend/app/studio/_components/InspectorPanel.tsx`

- [ ] **Step 1: studio-store.ts**

```typescript
interface StudioStore {
  sessionId: string | null
  workspace: WorkspaceState | null
  messages: StudioMessage[]
  streaming: boolean
  pendingConfirm: ConfirmPayload | null
  selectedArtifactId: string | null
  // actions: loadSession, sendMessage, applyWorkspacePatch, ...
}
```

- [ ] **Step 2: StudioLayout 三栏**

Tailwind：`grid grid-cols-12`，左 `col-span-3`，中 `col-span-5`，右 `col-span-4`，`h-[calc(100vh-3rem)]`。

- [ ] **Step 3: StudioThread**

- 消息列表渲染 `user` / `assistant` / `tool` / `confirm` 卡片
- 底部 textarea + 发送；streaming 时中止按钮
- `confirm` 卡片用 `useConfirm()` 或内联按钮 → 带 `resume_call_id` 再发

- [ ] **Step 4: page.tsx 初始化**

`useSearchParams` 读 `session`；无则 `createAgentSession`；有则 `getAgentSession`。

- [ ] **Step 5: 访问 http://localhost:3000/studio 可见空工作台**

---

## Task 10: Artifact 画布接入 Plan

**Files:**
- Modify: `frontend/app/studio/_components/ArtifactCanvas.tsx`
- Reuse: `frontend/app/match/_components/PlanEditWorkspace.tsx`
- Reuse: `frontend/app/match/_components/planTimelineAdapter.ts`

- [ ] **Step 1: ArtifactCanvas 根据 selectedArtifact 渲染**

`type === 'plan'` 时渲染 `PlanEditWorkspace`（从 workspace.plans 取 plan）。

- [ ] **Step 2: Plan 编辑回写**

`setPlan` 回调 → `PATCH /api/agent/sessions/{id}/workspace` 更新对应 plan。

- [ ] **Step 3: 对话触发 plan 后画布自动聚焦**

收到 SSE `artifact`且 `type=plan` → `setSelectedArtifactId`。

- [ ] **Step 4: E2E 手测**

对话：「用素材库第一个视频生成 60 秒口播方案」→ 画布出现时间线。

---

## Task 11: 导航与退役旧 Chat

**Files:**
- Modify: `frontend/app/_components/TopNav.tsx`
- Modify: `frontend/app/layout.tsx`
- Modify: `frontend/app/page.tsx`

- [ ] **Step 1: TopNav**

```typescript
{ href: '/studio', label: '智剪工作台' },
{ href: '/match', label: '经典模式' },
```

移除原「智能剪辑」项或改为上述两项。

- [ ] **Step 2: layout.tsx 删除 AIChatPanel**

- [ ] **Step 3: 首页 CTA**

主按钮 `Link href="/studio"` 文案「开始智剪」。

- [ ] **Step 4: /match 页顶栏加提示条**

「经典模式：完整 Tab 工作区。推荐使用智剪工作台。」+ Link to /studio。

---

## Task 12: P0 端到端验收

- [ ] **Step 1: 准备素材**

素材库至少 1 个已处理视频（有 clips）。

- [ ] **Step 2: Studio 全流程**

对话顺序建议：

1. 「列出我的视频」
2. 「用视频 xxx 生成 60 秒方案，电商风格」
3. 画布检查 Plan → 手动改一 segment 字幕
4. 「按当前方案成片」
5. 确认 L2 对话框 → 等待完成 → 出现 export artifact 或下载提示

- [ ] **Step 3: 更新文档**

在 `docs/AI_DEV_GUIDE.md` 增加 § Agent Studio 入口与 API 列表。

- [ ] **Step 4: 记录已知限制到 spec 底部（可选）**

如：未处理视频自动 process 后需用户再说「继续」等。

---

# Phase P1 — 全流程工具 + 进度 + Checkpoint（P0 完成后）

## Task 13: WS 进度桥接

**Files:**
- Create: `backend/app/agent/job_watcher.py`
- Modify: `backend/app/agent/orchestrator.py`

- [ ] 订阅 `connectProcessJobWebSocket` 对应后端 task_id，在 tool 执行后启动 background watcher，向 session 队列推送 `progress` SSE（若 chat 流已断则写 DB 待轮询）。

- [ ] 前端 `StudioThread` 渲染 `progress` 消息条。

## Task 14: 剩余 12 个 Tool

- [ ] 按 spec §4.2 P1 表逐个实现并注册。
- [ ] `run_film_commentary` 封装 `film_commentary.pipeline`。
- [ ] `export_jianying` / `burn_subtitle` 返回 export artifact。

## Task 15: Checkpoint

- [ ] `create_checkpoint` / `restore_checkpoint` tool + workspace.checkpoints。
- [ ] Inspector「撤销」按钮调用 restore。

## Task 16: 确认流完善

- [ ] 本会话「不再询问」存入 workspace.user_preferences。
- [ ] L3 `delete_video` 必须 ConfirmDialog。

---

# Phase P2 — 极致体验（P1 完成后）

## Task 17: Editor Agent

- [ ] `backend/app/agent/editor.py` 将自然语言转为 `apply_plan_patch` 的 patch JSON。

## Task 18: 语音输入

- [ ] Studio 输入框旁接入 `components/ui/voice-input.tsx`。

## Task 19: 会话列表页

- [ ] `/studio` 无 session 时展示历史 sessions 列表（GET `/api/agent/sessions` 需新增）。

## Task 20: Token 仪表盘

- [ ] 顶栏显示本轮/本会话 token（复用 `core/metrics/token_usage.py`）。

---

## Spec Coverage Self-Review

| Spec 章节 | Task |
|-----------|------|
| §3 Workspace / SSE | Task 1–2, 6–7, 8 |
| §4 Tool Registry P0 | Task 3–4 |
| §5 多 Agent | Task 5–6 |
| §6 上下文 | Task 5 |
| §7 前端 | Task 8–11 |
| §8 安全 | Task 4（校验 id）、Task 6（confirm） |
| §9 P1/P2 | Task 13–20 |

无 TBD 占位；P0 共 12 个 Task，可独立交付闭环。

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-31-agent-studio.md`.**

**两种执行方式：**

1. **Subagent-Driven（推荐）** — 按 Task 1→12 派发子 agent，每 Task 完成后你做验收  
2. **Inline Execution** — 本会话直接按 Task 逐步实现，每 2–3 个 Task 设检查点  

你回复 **「1」** 或 **「2」**（也可说「从 Task 1 开始」），即开始写代码。
