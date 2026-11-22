# LX_SmartClip 实施计划

> **阅读说明（2026-04）：** 下文 Phase 3–11 的逐条任务块为早期草案，部分排版仍写「待完成」，**请以仓库实际代码与 [CHECKLIST.md](../CHECKLIST.md)、[progress.md](./progress.md) 为准。** 文末「阶段里程碑总览」表已按当前实现更新。

原则：小步前进，每步可验证，先通基础链路，再叠 AI 能力。

---

## Phase 0：环境搭建与项目骨架 ✅

- 后端 FastAPI、`/health`、lifespan、`init_db`、阻塞线程池初始化  
- 前端 Next.js 14、Tailwind、Zustand、Axios、首页联通  

## Phase 1：数据库基础层 ✅

- SQLite、`videos` / `clips` / `config` 及后续迁移表（`replica_templates`、`process_tasks`）  
- `GET/PATCH /api/config`  

## Phase 2：视频上传与管理 ✅

- 上传、列表、删除；前端素材库；后续扩展 URL 导入、重编码、缩略图等（见 `videos.py`）  

---

## Phase 3–7：切分、ASR、VLM、向量、一键处理 ✅

（详细子任务见历史正文；实现集中在 `splitter.py`、`asr`、`vlm`、`embedder`、`vector_db`、`process*.py` 与对应 `api` 路由。）

## Phase 8：匹配引擎 ✅

- `rag.py`、`matcher.py`、`POST /api/match`、前端 `/match`  

## Phase 9：TTS ✅

- 多提供商 TTS 抽象与实现、`/api/tts/*`、前端 `/tts`  

## Phase 10：导出 ✅

- `POST /api/export/project`（ZIP 工程包）  

## Phase 11：系统设置 ✅

- `/settings` 分组配置、模型列表代理等  

## Phase 12：集成测试与收尾 ⏳

- 端到端测试、错误处理与用户可见反馈统一  

---

## 阶段里程碑总览（与代码同步）

| Phase | 内容 | 状态 |
|-------|------|------|
| 0 | 环境骨架 | ✅ |
| 1 | 数据库与配置 | ✅ |
| 2 | 视频上传与管理 | ✅ |
| 3 | 视频切分 / 抽帧 / 音频 | ✅ |
| 4 | ASR | ✅ |
| 5 | VLM | ✅ |
| 6 | 向量化与入库 | ✅ |
| 7 | 一键处理与进度 | ✅ |
| 8 | 匹配引擎 | ✅ |
| 9 | TTS | ✅ |
| 10 | 工程导出 | ✅ |
| 11 | 设置页 | ✅ |
| 12 | 测试与容错 | ⏳ |

---

## 扩展里程碑（原计划外，已落地）

| 主题 | 状态 | 主要位置 |
|------|------|-----------|
| 语义检索 / 高光 | ✅ | `api/search.py`、前端 `/search` |
| 对话 / 文案生成 | ✅ | `api/chat.py`、`api/copy_gen.py` |
| 字幕管线 | ✅ | `api/subtitle.py`、`core/subtitle` |
| 自动剪辑 | ✅ | `api/auto_edit.py`、`core/auto_edit*` |
| BGM 曲库 | ✅ | `api/bgm.py`、`core/bgm` |
| 复刻模板 Replica | ✅ | `api/replica.py`、`replica_templates` |
| 处理任务表与 jobs API | ✅ | `process_tasks`、`/api/process-jobs` |
| 静态前端一体化部署 | ✅ | `main.py` 挂载 `static/frontend`、SPA fallback |

---

## 历史正文（Phase 3 起逐条任务 — 仅供参考）

以下保留原始分条描述，便于对照设计意图；**实现状态以上表与 progress 为准。**

### Phase 3：视频切分（核心管线第一段）

#### 3.1 FFmpeg 集成与音频提取

**任务：**
- 安装 `ffmpeg-python`，确认系统 FFmpeg 可用
- 创建 `app/core/splitter.py`：
  - `extract_audio(video_path) -> audio_path`：用 FFmpeg 提取音频为 WAV
- 创建 `POST /api/videos/{id}/extract-audio` 接口

**⏳ 待完成**（历史标记 — 实际已完成，见 `clips.py` / `splitter.py`）

---

#### 3.2 视频切分（双模式）

**任务：**
- 安装 `scenedetect[opencv]`
- `splitter.py` 新增两个函数：
  - `split_by_scene(video_path, threshold) -> list[ClipInfo]`：PySceneDetect 镜头切分
  - `split_by_fixed(video_path, duration) -> list[ClipInfo]`：FFmpeg 固定时长切分
- 创建 `POST /api/videos/{id}/split` 接口

**⏳ 待完成**（历史标记 — 实际已完成）

---

#### 3.3 抽帧

**任务：**
- `splitter.py` 新增 `extract_frames(clip_path, n_frames=3) -> list[frame_path]`
- 切分完成后自动触发抽帧

**⏳ 待完成**（历史标记 — 实际已完成）

---

### Phase 4：ASR 语音识别

（历史条目略 — 已实现 `core/asr`、`api/asr.py`。）

### Phase 5：VLM 视觉描述

（历史条目略 — 已实现 `core/vlm`、`api/vlm.py`。）

### Phase 6：向量化与入库

（历史条目略 — 已实现 `faiss_db`、`embedder`、`api/embed.py`。）

### Phase 7：全素材处理整合

（历史条目略 — 已实现 `process.py`、`process-jobs`、前端 `/process`。）

### Phase 8：三级匹配引擎

（历史条目略 — 已实现 `rag`、`matcher`、`match.py`、前端 `/match`。）

### Phase 9：TTS 配音

（历史条目略 — 已实现多提供商 TTS、`tts.py`、前端 `/tts`。）

### Phase 10：导出功能

（历史条目略 — 已实现 `POST /api/export/project`。）

### Phase 11：系统设置页面

（历史条目略 — 已实现 `/settings`。）

### Phase 12：集成测试与收尾

**⏳ 待完成**

---

## 当前进度总结（2026-04）

**已完成：** Phase 0–11 全链路 + 表中「扩展里程碑」所列能力。  

**下一步优先级：**  
1. Phase 12：端到端测试与错误处理统一  
2. 按需补充运维文档（部署、日志、备份 DB + storage）  

---

**最后更新：** 2026-04-09
