# LX SmartClip AI 开发维护手册

> 目标：让后续 AI/开发者在最短时间内理解项目结构、改动边界与排错路径，减少“盲改”和上下文缺失。

## 1. 项目总览（前后端）

- 前端：`frontend/`，基于 Next.js 14 + React 18 + TypeScript + Tailwind + Zustand。
- 后端：`backend/`，基于 FastAPI + SQLite + FAISS，串联 ASR/VLM/LLM/视频处理流程。
- 数据与产物：
  - DB：`backend/data/smartclip.db`
  - 静态资源：`backend/storage/`
  - 前端静态导出（发布态）：`backend/app/static/frontend/`

## 2. 目录地图（建议从这些入口读起）

### 前端（`frontend/`）

- 页面入口：
  - `app/layout.tsx`：全局布局、导航、`AIChatPanel`。
  - `app/page.tsx`：首页与基础健康检查入口。
  - `app/library/page.tsx`：素材库（上传、列表、删除等）。
  - `app/process/page.tsx`：素材处理流程可视化（WebSocket / 任务进度）。
  - `app/search/page.tsx`：素材检索（对接 `/api/search`）。
  - `app/studio/page.tsx`：智剪工作台（Agent 对话编排，P0 主入口）。
  - `app/match/page.tsx`：经典模式智能剪辑（手动匹配、自动成片、字幕、导出等）。
  - `app/tts/page.tsx`：TTS 配音。
  - `app/bgm/page.tsx`：BGM 曲库。
  - `app/settings/page.tsx`：系统配置管理。
  - `app/logs/page.tsx`：运行日志查看。
  - `app/about/page.tsx`：关于与支持。
- 核心基础层：
  - `lib/api.ts`：前后端契约中心（REST + WS + SSE + 类型定义）。
  - `lib/store.ts`：全局状态中心（Zustand + persist + migrate）。
  - `lib/runtime-config.ts`：运行时 API 地址策略。
- 复杂业务组件（高频改动区）：
  - `app/match/_components/`：自动成片、手动匹配、预览面板、计划卡片等。

### 后端（`backend/`）

- 应用入口：
  - `app/main.py`：FastAPI 初始化、路由挂载、中间件、静态资源挂载、SPA fallback。
  - `start_backend.py`：开发/打包态启动逻辑（端口选择、日志、浏览器打开）。
- API 层（`app/api/`）：
  - `videos.py`、`clips.py`：视频与片段（上传、切分、流、元数据）。
  - `process.py`：处理流水线 + `/api/process-jobs` 任务态与 WS。
  - `match.py`、`search.py`：匹配与语义检索。
  - `auto_edit.py`：自动成片（plan/session/stream/realize 等）。
  - `subtitle.py`、`tts.py`、`bgm.py`、`export.py`：字幕、TTS、BGM、工程导出。
  - `agent.py`：Agent Studio 会话、SSE 对话、Workspace。
  - `chat.py`、`copy_gen.py`：对话与文案生成（chat 将逐步由 agent 替代）。
  - `replica.py`、`logs.py`：复刻模板、日志。
  - `config.py`：配置与 `POST /models` 代理。
- 核心能力层（`app/core/`）：
  - `splitter.py`：视频切分、抽帧、音频提取。
  - `matcher.py`：匹配核心逻辑。
  - `embedder.py` + `vector_db/faiss_db.py`：向量化与检索。
  - `asr/`、`vlm/`、`llm/`：模型调用适配。
  - `auto_edit/`、`auto_edit_v2/`：自动成片规划与时间线生成。
- 数据与配置：
  - `app/db/init_db.py`：初始化与默认配置灌入（非常关键）。
  - `app/models/`：请求/响应数据模型。

## 3. 关键技术栈与依赖

- 前端依赖重点：`next`、`axios`、`zustand`、`tailwindcss`。
- 后端依赖重点：`fastapi`、`uvicorn`、`aiosqlite`、`faiss-cpu`、`openai`、`openai-whisper`、`scenedetect`、`ffmpeg-python`、`moviepy`、`edge-tts`。
- 打包链路：Nuitka / PyInstaller / PyArmor（见 `scripts/`）。

## 4. 业务主链路（理解系统行为的最短路径）

1. 素材进入：前端 `library` 上传视频 -> 后端 `videos` 入库。
2. 素材处理：前端 `process` 发起处理 -> 后端 `process` 执行分步流水线（支持实时状态）。
3. 智能匹配：前端 `match` 传 query/video_ids/top_k/top_n -> 后端 `match` 返回候选与推荐片段。
4. 自动成片：前端 `auto-edit` 模块请求 plan/session -> 后端生成方案并 realize 出成片。
5. 导出与增强：字幕烧录、TTS 合成、BGM 混音等通过对应 API 完成。

## 5. 前后端契约说明（AI 修改时必须优先对齐）

- 契约主文件：`frontend/lib/api.ts`
  - 所有新增后端接口，应先在该文件增加 typed API 封装与 TS 类型。
  - 对已有字段变更（重命名/类型变化）必须同步更新前端类型与调用点。
- 状态主文件：`frontend/lib/store.ts`
  - 任何 `persist` 字段调整都要同步考虑：`version`、`migrate`、`partialize`、`merge`。
  - 若修改 match 页面状态结构，优先补齐默认值与兼容逻辑，避免老缓存导致运行时异常。

## 6. 高频改动场景 SOP（给 AI 的执行步骤）

### 场景 A：新增一个后端接口并前端接入

1. 后端：
   - 在 `backend/app/api/*.py` 增加路由；
   - 必要时补 `backend/app/models/*.py`；
   - 在 `backend/app/main.py` 确认 router 已挂载。
2. 前端：
   - 在 `frontend/lib/api.ts` 增加 typed 方法与类型；
   - 页面/组件接入新方法；
   - 若涉及全局状态，更新 `frontend/lib/store.ts`。
3. 验证：
   - 最少完成一次“请求 -> 响应 -> UI 状态变化”闭环验证。

### 场景 B：修改自动成片能力

1. 优先阅读：
   - 前端：`frontend/app/match/_components/` 下自动成片相关组件；
   - 后端：`backend/app/api/auto_edit.py` + `backend/app/core/auto_edit*/`。
2. 改动原则：
   - 不要绕开既有 plan 数据结构，尽量在兼容字段上增量扩展；
   - 需要跨层新增字段时，先改后端 schema/响应，再改前端类型与渲染。
3. 风险点：
   - 计划结构变化会影响持久化、预览、realize 三条链路，必须逐条回归。

### 场景 C：修改素材处理流水线

1. 核心位置：`backend/app/api/process.py`（编排）、`backend/app/core/splitter.py`（处理细节）。
2. 保持步骤状态字段稳定（前端依赖 step/status/message 进行展示）。
3. 一旦新增步骤，前端 `ProcessMessage` 类型与 UI 状态机需同步。

## 7. 本地运行与验证命令

### 前端

- 安装依赖：`npm install`（目录：`frontend/`）
- 开发启动：`npm run dev`
- 构建：`npm run build`
- Lint：`npm run lint`

### 后端

- 安装依赖：`pip install -r requirements.txt`（目录：`backend/`）
- 开发启动（常用）：`uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`
- 启动脚本：`python start_backend.py`

### 脚本式测试（当前仓库形态）

- `python backend/test_splitter.py`
- `python backend/test_asr.py`
- `python backend/test_vlm.py`

## 8. 快速排错手册

- 前端页面空白/接口失败：
  - 先看 `frontend/lib/runtime-config.ts` 与实际 `API_BASE_URL`；
  - 再看后端 `health` 与浏览器网络请求状态码。
- 处理流程“卡住”：
  - 先看 `process` WebSocket 是否连接与首包发送；
  - 后端检查 `process.py` 日志与每步返回状态。
- 自动成片“有计划无导出”：
  - 核查 `auto_edit.py` realize 请求体与 plan 字段是否完整；
  - 核查字幕/TTS/BGM 关联资源路径是否可读写。
- 路由直达 404（发布态）：
  - 重点检查 `backend/app/main.py` 的静态挂载与 fallback 逻辑是否被改坏。

## 9. 建议维护的长期文档（AI 连续开发必备）

- `docs/AI_DEV_GUIDE.md`（本文件）：架构和开发入口，保持最新。
- 根目录 `CHECKLIST.md`、`PROJECT_SUMMARY.md`、`QUICKSTART.md`：阶段清单与快速上手。
- `memory-bank/progress.md`：进度与按模块整理的接口索引（新增路由时建议同步）。
- 可选新增：`docs/CHANGELOG_AI.md`、`docs/API_CONTRACT.md`、`docs/TROUBLESHOOTING.md`（按团队需要再建，避免与 `progress.md` 重复）。

## 10. 给后续 AI 的约束建议（可直接复制到任务提示词）

1. 先读本文件，再读 `frontend/lib/api.ts`、`frontend/lib/store.ts`、`backend/app/main.py`。
2. 任何跨前后端字段改动，先更新类型与契约，再改业务逻辑。
3. 涉及持久化状态改动，必须处理 `version/migrate` 兼容。
4. 涉及自动成片改动，必须验证：plan 生成、预览渲染、realize 导出三个阶段。
5. 提交前至少完成一条主流程自测，并记录到变更说明。

---

## 11. Agent Studio（智剪工作台）

- 入口：`/studio`；设计见 `docs/superpowers/specs/2026-05-31-agent-studio-design.md`。
- API 前缀：`/api/agent`（`sessions`、`chat` SSE、`workspace` PATCH）。
- 后端实现：`backend/app/agent/`（orchestrator、tool_registry、tools）。
- P0 工具：`list_videos`、`get_video_status`、`get_workspace_state`、`set_selected_videos`、`start_process_job`、`generate_auto_edit_plan`、`apply_plan_patch`、`realize_plan`。

---

**最后更新：** 2026-05-31
