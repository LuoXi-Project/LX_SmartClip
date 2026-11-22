# LX SmartClip 项目总结（与代码同步）

洛曦智剪（LX SmartClip）：本地偏轻量的 **AI 素材理解 + 文案匹配 + 配音/字幕 + 自动剪辑辅助** 工具。前端为 Next.js 14，后端为 FastAPI；元数据在 SQLite，向量检索使用 FAISS；支持可选卡密授权与静态前端一体化部署。

---

## 当前已实现能力

### 素材与处理

- 视频上传、列表、删除、缩略图与流式预览、URL 导入、可选重编码
- 切分（场景 / 固定 / 混合等）、抽帧、音频提取
- 流水线处理：ASR → VLM → Embedding，一键处理与 WebSocket / 任务维度进度（`process_tasks` + `/api/process-jobs`）

### 检索与匹配

- 向量召回 + LLM 精排：`POST /api/match`
- 语义资源检索、高光浏览等：`/api/search/*`

### 生成与导出

- 多提供商 TTS、工程 ZIP 导出（`POST /api/export/project`）
- 字幕生成 / 导出 / 烧录：`/api/subtitle/*`
- 自动剪辑计划与实现：`/api/auto-edit/*`
- 文案生成、对话补全：`/api/copy-gen/*`、`/api/chat/*`
- BGM 曲库管理：`/api/bgm/*`
- 复刻模板（Replica）：从素材生成与确认模板：`/api/replica/*`

### 系统与运维

- 全局配置 `GET/PATCH /api/config`
- `POST /api/config/models`：代理拉取模型列表（避免浏览器 CORS）
- 运行日志：`GET /api/logs`

### 前端页面（App Router）

| 路径 | 说明 |
|------|------|
| `/` | 首页与状态 |
| `/library` | 素材库 |
| `/process` | 处理进度 |
| `/search` | 素材检索 |
| `/match` | 智能剪辑主工作台 |
| `/tts` | TTS 配音 |
| `/bgm` | BGM 音乐库 |
| `/settings` | 系统设置 |
| `/logs` | 日志 |
| `/about` | 关于与支持 |

全局：底部栏、`AIChatPanel`（见 `frontend/app/layout.tsx`）。

---

## 架构要点

- **API 层** `backend/app/api/`：按域拆分路由模块，在 `main.py` 统一挂载；可挂载 `storage` 与静态前端目录。
- **核心层** `backend/app/core/`：切分、ASR/VLM、向量库、RAG、匹配、LLM、TTS 多提供商、字幕、自动剪辑、BGM、授权等。
- **数据** `backend/data/smartclip.db`；**产物** `backend/storage/`；向量索引等按现有实现落盘于 storage 侧（与 FAISS 封装一致）。
- **阻塞任务** `blocking_pool`：在应用 lifespan 中初始化，避免 CPU 密集任务阻塞事件循环。

---

## 快速启动

```bash
# 后端（在 backend 目录）
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 前端（在 frontend 目录）
npm install
npm run dev
```

浏览器访问 `http://localhost:3000`；API 默认 `http://127.0.0.1:8000`。

---

## 文档导航

| 文档 | 用途 |
|------|------|
| [QUICKSTART.md](./QUICKSTART.md) | 环境、验证步骤、目录说明 |
| [CHECKLIST.md](./CHECKLIST.md) | 阶段清单与统计 |
| [memory-bank/progress.md](./memory-bank/progress.md) | 进度与接口一览（维护时优先更新） |
| [memory-bank/implementation-plan.md](./memory-bank/implementation-plan.md) | 分阶段计划（里程碑表已同步；正文部分为历史草案时可对照 CHECKLIST） |
| [memory-bank/architecture.md](./memory-bank/architecture.md) | 目录与模块职责 |
| [memory-bank/design-document.md](./memory-bank/design-document.md) | 产品设计 |
| [docs/](./docs/) | 专题文档（自动剪辑策略、复刻质量、AI 维护手册等） |

---

## 后续建议（非阻塞）

1. 补齐端到端测试与关键 API 契约测试。  
2. 统一对外错误码与用户可见文案（鉴权、配额、第三方 AI 失败）。  
3. 按需收紧生产环境 CORS（开发态当前为宽松配置，以 `main.py` 为准）。

---

**最后更新：** 2026-04-09
