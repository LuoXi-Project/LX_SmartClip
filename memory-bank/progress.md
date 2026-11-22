# LX SmartClip 开发进度记录

> 与仓库同步的进度快照。接口以 `backend/app/api/*.py` 为准。

## 当前阶段（摘要）

- **原始 Phase 0–11：** 已完成（基础管线、匹配、TTS、导出、设置）。  
- **扩展能力：** 检索、对话、文案生成、字幕、自动剪辑、BGM、复刻模板、卡密、日志、任务化 process-jobs 等已并入主线。  
- **Phase 12：** 端到端测试与统一错误/容错策略 — 进行中 / 待加强。

---

## 模块与路由（按前缀）

| 前缀 | 模块文件 | 说明 |
|------|-----------|------|
| `/health` | `main.py` | 健康检查 |
| `/api/config` | `config.py` | 配置读写；`POST /models` 代理模型列表 |
| `/api/videos` | `videos.py` | 上传、列表、流/缩略图、URL 导入、重编码、高光等 |
| `/api/videos` | `clips.py` | 切分、抽帧、音频、片段 CRUD/流 |
| `/api/videos` | `asr.py` / `vlm.py` / `embed.py` | 分步 ASR / VLM / 嵌入 |
| `/api/videos` | `process.py` | 一键处理、取消、兼容 WS；`POST .../process-jobs` |
| `/api/process-jobs` | `process.py`（jobs_router） | 任务查询、取消、任务级 WS |
| `/api/match` | `match.py` | 文案匹配 |
| `/api/search` | `search.py` | 语义检索、高光浏览 |
| `/api/tts` | `tts.py` | 合成、音色列表、音频文件 |
| `/api/export` | `export.py` | 工程 ZIP |
| `/api/chat` | `chat.py` | 对话补全 |
| `/api/copy-gen` | `copy_gen.py` | 文案生成 |
| `/api/subtitle` | `subtitle.py` | 字幕生成、烧录、导出、下载 |
| `/api/auto-edit` | `auto_edit.py` | 模板、计划、流式会话、快剪、实现 |
| `/api/bgm` | `bgm.py` | 曲库 CRUD |
| `/api/replica` | `replica.py` | 模板摄入、生成、确认、列表 |
| `/api/logs` | `logs.py` | 运行日志 |

**统计：** `app/api` 下 HTTP/WS 路由装饰器约 **60+**（含 WebSocket）。

---

## 数据库表（`init_db.py`）

| 表 | 用途 |
|----|------|
| `videos` | 视频元数据与状态 |
| `clips` | 片段与 ASR/VLM 等字段 |
| `config` | 全局配置（`ui_onboarding_v1` 等对前端配置接口隐藏） |
| `replica_templates` | 复刻模板草稿与确认态 |
| `process_tasks` | 处理任务状态与进度 JSON |

向量索引：由 `core/vector_db`（FAISS 等）与 storage 侧文件配合，不单表名 `clip_embeddings`。

---

## 前端页面（`frontend/app`）

| 路径 | 文件 |
|------|------|
| `/` | `page.tsx` |
| `/library` | `library/page.tsx` |
| `/process` | `process/page.tsx` |
| `/search` | `search/page.tsx` |
| `/match` | `match/page.tsx` |
| `/tts` | `tts/page.tsx` |
| `/bgm` | `bgm/page.tsx` |
| `/settings` | `settings/page.tsx` |
| `/logs` | `logs/page.tsx` |
| `/about` | `about/page.tsx` |

全局布局与导航：`layout.tsx`（含 `AIChatPanel`）。

---

## 下一步（Phase 12 建议）

1. 为核心链路增加可重复执行的自动化测试（上传 → 处理 → 匹配 → 导出最小路径）。  
2. 梳理对外错误模型：鉴权失败、第三方 AI 超时/限额、磁盘与 FFmpeg 失败等。  
3. 文档：保持本文件与 `CHECKLIST.md`、`PROJECT_SUMMARY.md` 同频更新。

---

**最后更新：** 2026-04-09
