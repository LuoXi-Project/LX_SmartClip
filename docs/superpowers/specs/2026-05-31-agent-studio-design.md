# Agent Studio 设计规格（智剪工作台）

> **状态：** 已批准（用户确认：全流程 C、极致方案、主入口 A、多 Agent A）  
> **日期：** 2026-05-31  
> **替代：** 全局 `AIChatPanel` 浮层聊天；`/match` 降为经典模式入口

---

## 1. 目标与成功标准

### 1.1 产品目标

将洛曦智剪从「多 Tab 表单驱动」升级为 **对话编排操作系统**：

- 用户用自然语言描述端到端目标（上传 → 处理 → 匹配/规划 → 编辑 → 成片 → 导出）。
- Agent 通过 **Tool Registry** 调用现有后端能力，不重复实现业务逻辑。
- 结构化产物以 **Artifact** 呈现在画布，支持内联编辑与撤销。
- 长任务通过现有 WebSocket / 任务 API 回传进度到对话线程。

### 1.2 成功标准（P0 闭环）

在 `/studio` 完成以下路径，无需切换工作区 Tab：

1. 选择素材库视频  
2. 触发处理（或未处理则自动 `start_process_job`）  
3. 生成 `AutoEditPlan`  
4. 在 Artifact 画布预览/编辑 Plan  
5. `realize_plan` 出片  
6. 导出剪映草稿或下载成片  

### 1.3 非目标（首期不做）

- 多用户协作 / 云端会话同步  
- 自定义 Tool 插件市场  
- 替换现有 FFmpeg/模型推理实现  

---

## 2. 架构决策（已锁定）

| 决策 | 选择 | 理由 |
|------|------|------|
| 主入口 | `/studio` 为默认；`/match` → 经典模式 | 对话原生，降低 Tab 认知负担 |
| Agent 形态 | Router + Planner + Executor（同模型不同 system prompt） | 与影视解说「编剧层+执行层」一致 |
| 业务复用 | Tool 薄封装现有 `app/api` + `app/core` | 避免双轨维护 |
| 状态中心 | `Workspace` 持久化于 SQLite，非仅 chat messages | 支持恢复、撤销、手改同步 |
| 部署 | 本地单用户，LLM 读 `config` 表 | 与现有系统设置一致 |

---

## 3. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend /studio                                            │
│  StudioThread │ ArtifactCanvas │ Inspector                   │
│  studioStore(sessionId) ←→ agentApi (SSE)                    │
└───────────────────────────┬─────────────────────────────────┘
                            │ POST /api/agent/sessions/{id}/chat (SSE)
                            │ PATCH workspace / confirm
┌───────────────────────────▼─────────────────────────────────┐
│  backend/app/agent/                                          │
│  orchestrator → router → planner? → executor loop            │
│  context_builder │ tool_registry │ session_store               │
│  tools/* → 调用现有 api 层 service 函数（非 HTTP 自调用）      │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│  现有：process, match, auto_edit, subtitle, film, ...        │
└─────────────────────────────────────────────────────────────┘
```

### 3.1 SSE 事件类型

| 事件 | 载荷 | 用途 |
|------|------|------|
| `message_delta` | `{ content }` | 助手文本流 |
| `reasoning_delta` | `{ content }` | 可折叠推理摘要 |
| `route` | `{ route, reason }` | Router 决策 |
| `plan_steps` | `{ steps[] }` | Planner 任务分解 |
| `tool_start` | `{ call_id, name, input }` | 工具开始 |
| `tool_end` | `{ call_id, ok, summary, artifact? }` | 工具结束 |
| `progress` | `{ job_id, percent, step, message }` | 长任务进度 |
| `confirm_required` | `{ call_id, tool, preview, risk }` | 待用户确认 |
| `artifact` | `{ type, id, payload }` | 新/更新产物 |
| `workspace_patch` | `{ patch }` | 工作区增量更新 |
| `error` | `{ code, detail }` | 失败 |
| `done` | `{ usage? }` | 本轮结束 |

### 3.2 Workspace  schema（JSON 列存储）

```json
{
  "session_id": "uuid",
  "title": "string",
  "selected_video_ids": ["vid"],
  "pipeline_phase": "idle|ingest|process|match|plan|realize|export",
  "active_plan_id": "string|null",
  "plans": [],
  "match_segments": [],
  "jobs": {
    "process_task_ids": [],
    "film_job_id": null,
    "realize_job_id": null
  },
  "user_preferences": {
    "target_duration_sec": 60,
    "subtitle_policy": "auto",
    "bgm_policy": "auto",
    "content_style": "generic"
  },
  "checkpoints": [
    { "id": "cp1", "label": "before_patch", "plan_snapshot": {}, "created_at": "iso" }
  ],
  "last_exports": []
}
```

### 3.3 数据库表

```sql
-- agent_sessions
id TEXT PRIMARY KEY,
title TEXT,
workspace_json TEXT NOT NULL,
created_at TEXT NOT NULL,
updated_at TEXT NOT NULL

-- agent_messages
id TEXT PRIMARY KEY,
session_id TEXT NOT NULL,
role TEXT NOT NULL,  -- user|assistant|tool|system
content_json TEXT NOT NULL,
created_at TEXT NOT NULL,
FOREIGN KEY (session_id) REFERENCES agent_sessions(id)

-- agent_pending_confirms
call_id TEXT PRIMARY KEY,
session_id TEXT NOT NULL,
tool_name TEXT NOT NULL,
input_json TEXT NOT NULL,
risk TEXT NOT NULL,
expires_at TEXT
```

迁移：在 `init_db.py` 增加 `CREATE_AGENT_*` 与 `migrate_*` 版本号。

---

## 4. Tool Registry

### 4.1 风险等级

- **L0** 只读：自动执行  
- **L1** 普通写：自动执行  
- **L2** 重任务：默认需确认，可「本会话不再询问」  
- **L3** 破坏性：必须 `ConfirmDialog`  

### 4.2 工具清单（分阶段）

**P0（8 个）**

| 工具 | 风险 | 封装来源 |
|------|------|----------|
| `list_videos` | L0 | `videos` 列表查询 |
| `get_video_status` | L0 | `videos` + clips 计数 |
| `get_workspace_state` | L0 | session store |
| `set_selected_videos` | L1 | workspace patch |
| `start_process_job` | L2 | `process.py` jobs |
| `generate_auto_edit_plan` | L1 | `auto_edit` plan 生成 |
| `apply_plan_patch` | L1 | Plan JSON merge |
| `realize_plan` | L2 | `auto_edit` realize |

**P1（+12）**

`search_clips`, `match_script`, `get_process_job_status`, `cancel_process_job`, `run_film_commentary`, `generate_srt`, `burn_subtitle`, `export_jianying`, `list_bgm`, `select_bgm`, `generate_copy`, `import_video_url`

**P2（+8）**

`run_replica_pipeline`, `run_script_stock`, `run_mix_edit`, `run_video_dub`, `run_voiceover_quick_cut`, `delete_video`, `create_checkpoint`, `restore_checkpoint`

### 4.3 Tool 返回 Envelope

```python
class ToolResult(BaseModel):
    ok: bool
    summary: str
    artifact: Optional[ArtifactRef] = None
    workspace_patch: Optional[dict] = None
    job_id: Optional[str] = None
    next_suggestions: list[str] = []
    error: Optional[str] = None
```

---

## 5. 多 Agent Prompt 职责

### 5.1 Router

输入：用户消息 + workspace 摘要（phase、视频数、是否有 plan）  
输出 JSON：`{ "route": "plan"|"execute"|"ask"|"clarify", "reason": "..." }`

- `plan`：多步、全流程、新目标  
- `execute`：单步明确（「换成 90 秒」「直接导出」）  
- `ask`：仅信息查询  
- `clarify`：缺关键参数（未选视频等）  

### 5.2 Planner

输出 JSON：

```json
{
  "steps": [
    { "id": "s1", "title": "处理素材", "tool": "start_process_job", "depends_on": [] }
  ],
  "estimated_minutes": 8
}
```

Executor 按序执行；某步失败可局部重试或向用户澄清。

### 5.3 Executor

- OpenAI-compatible `tools` 参数调用  
- 最大并行：重任务串行（process/realize 队列）  
- 每轮最多 N 次 tool call（默认 8，可配置）  
- 将 tool 结果摘要写回 messages，避免塞入原始大 JSON  

### 5.4 Editor（P2）

专用于 `apply_plan_patch`：接收用户自然语言修改意图，输出 RFC6902 或结构化 segment patch。

---

## 6. 上下文工程

1. **System prompt 固定**：角色、风险规则、中文、禁止编造 clip_id  
2. **Workspace 摘要**：< 2KB JSON 摘要注入  
3. **按需检索**：Executor 调 `search_clips` / `get_clip_detail`，禁止预加载全库 ASR  
4. **对话历史**：最近 10 轮 + 重要决策写入 `user_preferences`  
5. **截断**：单 clip 描述 max 200 字；Planner 用视频级 meta  

---

## 7. 前端规格

### 7.1 路由

| 路径 | 说明 |
|------|------|
| `/studio` | 主工作台（新建或 `?session=` 恢复） |
| `/studio/[sessionId]` | 可选显式会话路由 |
| `/match` | 保留；顶栏标注「经典模式」 |

### 7.2 布局（≥1280px）

- 左 28%：对话线程 + 输入（`VoiceInput` 可选 P2）  
- 中 44%：Artifact 画布  
- 右 28%：Inspector  

### 7.3 组件映射

| Artifact type | 组件 |
|---------------|------|
| `plan` | `PlanEditWorkspace` |
| `match_results` | `SegmentRow` / clip 卡片 |
| `process_job` | 进度条 + 步骤列表 |
| `export` | 下载按钮 + 剪映路径 hint |
| `video` | 内联 preview |

### 7.4 确认流

`confirm_required` SSE → `ConfirmDialog`（`components/ui`）→ `POST .../confirm` → Orchestrator 继续或取消。

### 7.5 导航变更

- `TopNav`：「智能剪辑」→ `/studio`；增加「经典模式」链到 `/match`  
- `layout.tsx`：移除 `<AIChatPanel />`  
- 首页 `page.tsx`：主 CTA 指向 `/studio`  

---

## 8. 安全与可靠性

- Tool 输入 JSON Schema 校验（pydantic）  
- `clip_id` / `video_id` 必须存在于 DB 否则拒绝  
- realize/process 超时沿用现有 env（`SMARTCLIP_MATCH_TIMEOUT_SEC` 等）  
- 会话级 realize 互斥锁，防止并发双出片  
- LLM 失败：返回可读错误 + 保留 workspace 可手动继续  

---

## 9. 实施阶段

| 阶段 | 交付 |
|------|------|
| **P0** | `/studio` + Session + SSE + 8 tools + Plan Artifact + 闭环 realize |
| **P1** | 全 tool 集 + WS 进度 + 确认流 + checkpoint + film/export |
| **P2** | Editor agent + 语音输入 + 评测集 + 性能/token 仪表盘 |

---

## 10. 迁移与兼容

- `useMatchStore` 字段逐步迁入 `useStudioStore`；classic `/match` 可读同一 `session_id`（P1）  
- `/api/chat` 保留但标记 deprecated，文档指向 `/api/agent`  
- `docs/AI_DEV_GUIDE.md` 增加 Agent Studio 章节（P0 完成后）  

---

## 11. 参考文件

- `frontend/app/match/page.tsx` — 现有工作流与 API 调用范式  
- `frontend/lib/api.ts` — 契约中心，新增 `agentApi`  
- `frontend/lib/store.ts` — 状态迁移来源  
- `backend/app/api/auto_edit.py` — Plan/realize  
- `backend/app/api/process.py` — process-jobs + WS  
- `backend/app/api/summary/ask.py` — 流式 LLM 模式参考  
- `docs/AI影视剪辑方案.md` — 长视频分层上下文策略  
