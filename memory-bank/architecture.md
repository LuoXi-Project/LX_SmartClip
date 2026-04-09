# LX_SmartClip 架构说明

> 描述目录职责与请求链路，便于快速定位代码。接口清单以 [progress.md](./progress.md) 为准。

---

## 仓库顶层

```
LX_SmartClip/
├── backend/           # FastAPI 应用
├── frontend/          # Next.js 14（App Router）
├── memory-bank/       # 设计、进度、本架构说明
├── docs/              # 专题文档（策略、AI 维护手册等）
├── scripts/           # 构建/发布脚本（如有）
└── CHECKLIST.md / PROJECT_SUMMARY.md / QUICKSTART.md
```

---

## backend/

```
backend/
├── app/
│   ├── main.py              # FastAPI 入口：路由、CORS、License 中间件、storage 挂载、静态前端、404 兜底
│   ├── api/                 # 路由层（仅 HTTP/WS 编排）
│   ├── core/                # 业务与 AI 实现
│   ├── db/                  # SQLite 连接、init_db、migrate_db
│   ├── models/              # Pydantic 请求/响应模型
│   ├── middleware/          # 授权等
│   └── utils/               # 日志、路径、FFprobe 等工具
├── data/                    # smartclip.db（运行时生成，通常不提交）
├── storage/                 # 视频、音频、帧、索引文件等（通常不提交）
└── requirements.txt
```

### `app/main.py`（要点）

1. `lifespan`：`init_db()`、`init_blocking_pool()` / 关闭时 `shutdown_blocking_pool()`。  
2. 中间件：`LicenseMiddleware`、`CORSMiddleware`（当前 `allow_origins` 偏宽松，生产可按需收紧）。  
3. 挂载路由（节选）：`config`、`videos`、`clips`、`asr`、`vlm`、`embed`、`process` + `process-jobs`、`match`、`search`、`tts`、`export`、`chat`、`copy_gen`、`subtitle`、`auto_edit`、`bgm`、`replica`、`license`、`logs`。  
4. 静态资源：`/storage` → `backend/storage`；若存在 `app/static/frontend/index.html`，则挂载整站前端并配合 SPA fallback。

### `app/api/` — 路由模块一览

| 文件 | 前缀 / 说明 |
|------|-------------|
| `config.py` | `/api/config` |
| `license.py` | `/api/license` |
| `videos.py` | `/api/videos` |
| `clips.py` | `/api/videos`（片段、切分、流） |
| `asr.py` / `vlm.py` / `embed.py` | `/api/videos`（分步处理） |
| `process.py` | `/api/videos`（一键处理、取消、WS）；`jobs_router` → `/api/process-jobs` |
| `match.py` | `/api/match` |
| `search.py` | `/api/search` |
| `tts.py` | `/api/tts` |
| `export.py` | `/api/export` |
| `chat.py` | `/api/chat` |
| `copy_gen.py` | `/api/copy-gen` |
| `subtitle.py` | `/api/subtitle` |
| `auto_edit.py` | `/api/auto-edit` |
| `bgm.py` | `/api/bgm` |
| `replica.py` | `/api/replica` |
| `logs.py` | `/api/logs` |

各文件内路径为相对上述 `prefix` 的子路径；WebSocket 见 `process.py` 等。

### `app/db/`

- `database.py`：`get_db_conn()`、`get_db()`（异步上下文）。  
- `init_db.py`：建表、`DEFAULT_CONFIG` 灌入；含 `replica_templates`、`process_tasks` 及历史迁移逻辑。  

**表（核心）：**

| 表名 | 用途 |
|------|------|
| `videos` | 视频元数据、状态、时长等 |
| `clips` | 片段路径、时间轴、ASR/VLM 文本等 |
| `config` | 全局配置键值（部分 key 不对 `/api/config` 暴露） |
| `replica_templates` | 复刻模板 JSON 与状态 |
| `process_tasks` | 处理任务进度与结束态 |

向量检索：由 `core/vector_db`（如 FAISS）与磁盘索引文件配合，具体路径由实现写入 `storage`。

### `app/core/` — 能力分层（目录级）

| 区域 | 职责 |
|------|------|
| `splitter.py` | 切分、抽帧、音频 |
| `asr/` | ASR 抽象与 Whisper/OpenAI 等实现 |
| `vlm/` | 视觉描述 |
| `embedder.py` | 文本向量 |
| `vector_db/` | FAISS / sqlite-vss 等 |
| `rag.py`、`matcher.py` | 召回与精排 |
| `llm/` | 大模型调用与各类 prompt |
| `tts/` | TTS 抽象与多提供商 |
| `subtitle/` | 字幕时间线、SRT、烧录 |
| `auto_edit/`、`auto_edit_v2/` | 自动剪辑规划与 DSL |
| `bgm/` | BGM 选择与混音相关逻辑 |
| `license.py` | 授权校验 |
| `blocking_pool.py` | 阻塞任务线程池 |
| `metrics/` | 如 token 统计等 |

---

## frontend/

- `app/`：页面与布局（`layout.tsx` 内全局导航、`LicenseGate`、`AIChatPanel`）。  
- `lib/api.ts`：前后端契约（优先于此处对齐类型）。  
- `lib/store.ts`：Zustand 持久化状态。  
- `lib/runtime-config.ts`：API Base URL 等运行时策略。

---

## memory-bank/

| 文件 | 用途 |
|------|------|
| `design-document.md` | 产品与设计 |
| `implementation-plan.md` | 阶段计划（里程碑表已更新） |
| `progress.md` | **进度与接口索引（推荐常更新）** |
| `tech-stack.md` | 技术栈说明 |
| `architecture.md` | 本文件 |
| `PHASE*_SUMMARY.md` 等 | 历史阶段小结 |

---

## 数据流（简化）

```
上传 → POST /api/videos/upload → videos 表 + storage
处理 → POST /api/videos/{id}/process-jobs 或 WS → process_tasks + 流水线
      → clips 更新 + ASR/VLM/向量索引落盘
匹配 → POST /api/match → 召回 + LLM → 返回候选
导出 → TTS / subtitle / auto-edit realize → ZIP 或成片文件
```

---

**最后更新：** 2026-04-09
