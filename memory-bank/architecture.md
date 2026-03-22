# LX_SmartClip 架构说明

> 本文档描述项目每个文件/目录的职责，供后续开发者快速定位代码。

---

## 项目根目录结构

```
LX_SmartClip/
├── backend/          # Python 后端（FastAPI）
├── memory-bank/      # 项目文档（需求、架构、进度、实施计划）
├── venv/             # Python 虚拟环境（不提交 git）
└── .gitignore
```

---

## backend/ 目录

```
backend/
├── app/              # FastAPI 应用主包
├── data/             # SQLite 数据库文件（运行时生成，不提交 git）
│   └── smartclip.db  # 主数据库：元数据 + 配置（向量表后续加入）
├── verify_db.py      # Phase 1 验证脚本（开发阶段用，可删除）
└── requirements.txt  # Python 依赖清单
```

### requirements.txt
核心依赖版本声明。当前已安装：`fastapi`、`uvicorn[standard]`、`pydantic>=2.0`、`python-multipart`、`aiosqlite`。后续 Phase 会追加 `ffmpeg-python`、`scenedetect`、`openai`、`edge-tts`、`llama-index`、`sqlite-vss` 等。

---

## backend/app/ — 应用主包

```
app/
├── main.py           # FastAPI 应用入口
├── api/              # 路由层（HTTP 接口）
├── core/             # 业务逻辑层（AI 模块、处理管线）
├── db/               # 数据库层（连接管理、建表、初始化）
└── __init__.py
```

### app/main.py
**职责：** FastAPI 应用的唯一入口，负责：
1. 创建 `FastAPI` 实例（title、version）
2. 注册 `lifespan` 钩子：服务启动时自动调用 `init_db()` 建表并写入默认配置
3. 注册 CORS 中间件（允许来自 `http://localhost:3000` 的跨域请求，为前端 Next.js 预留）
4. 注册各业务路由（当前：`config_router`）
5. 提供 `GET /health` 健康检查接口

**启动命令：**
```bash
# 在 backend/ 目录下
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

---

## backend/app/api/ — 路由层

路由层只负责 HTTP 请求/响应处理：参数校验、调用业务逻辑、返回结果。不含业务逻辑。

```
api/
├── config.py         # 全局配置 CRUD 接口
└── __init__.py
```

### api/config.py
**职责：** 全局配置的读写接口。

| 接口 | 方法 | 路径 | 说明 |
|------|------|------|------|
| `get_config` | GET | `/api/config` | 返回所有配置项（key → {value, type, label, options}） |
| `update_config` | PATCH | `/api/config` | 更新单条配置，接收 `{key, value}`，key 不存在返回 404 |

**数据模型：** `ConfigUpdate(key: str, value: str)`

**设计说明：**
- PATCH 接口先查询 key 是否存在（404 友好提示），再执行 UPDATE，避免静默失败
- 所有配置值均以字符串存储，前端根据 `type` 字段决定渲染方式（number/select/string）
- `options` 字段为 JSON 字符串，前端解析后渲染下拉选项

**后续新增文件（按 Phase）：**
- `videos.py`（Phase 2）：视频上传、列表、删除
- `clips.py`（Phase 3）：片段管理、切分触发
- `match.py`（Phase 8）：三级匹配接口
- `tts.py`（Phase 9）：TTS 配音接口
- `export.py`（Phase 10）：导出接口

---

## backend/app/db/ — 数据库层

```
db/
├── database.py       # 连接管理
├── init_db.py        # 建表 + 默认数据初始化
└── __init__.py
```

### db/database.py
**职责：** 提供数据库连接的两种方式。

```python
DB_PATH  # 绝对路径，基于 __file__ 计算，指向 backend/data/smartclip.db

get_db_conn() -> aiosqlite.Connection
# 返回裸连接，row_factory 设为 aiosqlite.Row（支持按列名访问）
# 调用方必须在 finally 中调用 db.close()
# 适合：简单路由函数

get_db() -> AsyncGenerator[aiosqlite.Connection, None]
# 异步生成器，自动管理连接生命周期
# 适合：FastAPI Depends 依赖注入（推荐后续路由使用）
```

**路径策略：** `DB_PATH` 使用 `os.path.abspath(__file__ + ../../data/smartclip.db)` 计算，与工作目录无关，保证任意位置启动都能找到正确路径。

### db/init_db.py
**职责：** 数据库结构初始化，服务启动时由 `main.py` lifespan 调用。

**建表（均为 `CREATE TABLE IF NOT EXISTS`，幂等）：**

| 表名 | 核心字段 | 用途 |
|------|----------|------|
| `videos` | id, name, file_path, duration, total_clips, split_mode, status, upload_at | 原始视频元数据 |
| `clips` | id, video_id, clip_path, start_time, end_time, duration, asr_text, vlm_description, tags | 切分后的视频片段 |
| `config` | key, value, type, label, options | 全局配置（前端配置页直接读写） |

**默认配置（`INSERT OR IGNORE`，幂等，不覆盖已有值）：**
11 条默认配置项，涵盖：切分模式、场景阈值、固定时长、向量维度、TopK、VLM/ASR/TTS 服务参数。

**注意：** `videos.status` 字段已预建（`pending/processing/done/error`），为 Phase 7 处理管线状态追踪预留，当前 Phase 不使用。

---

## backend/app/core/ — 业务逻辑层

```
core/
└── __init__.py       # 当前为空，后续 Phase 填充
```

**后续将按 Phase 新增（均含抽象基类 + 具体实现）：**

| 文件/目录 | Phase | 职责 |
|-----------|-------|------|
| `splitter.py` | 3 | 视频切分（镜头识别 / 固定时长）、抽帧、音频提取 |
| `asr/base.py` | 4 | ASR 抽象接口 `IASR` |
| `asr/whisper_asr.py` | 4 | Whisper 本地 ASR 实现 |
| `vlm/base.py` | 5 | VLM 抽象接口 `IVLM` |
| `vlm/openai_vlm.py` | 5 | OpenAI 兼容 VLM 实现 |
| `tts/base.py` | 9 | TTS 抽象接口 `ITTS` |
| `tts/edge_tts_impl.py` | 9 | edge-tts 实现 |
| `llm/base.py` | 8 | LLM 抽象接口 `ILLM` |
| `llm/openai_llm.py` | 8 | OpenAI 兼容 LLM 实现（用于精排） |
| `vector_db.py` | 6 | 向量库抽象 `IVectorDB` + SQLite-VSS 实现 |
| `embedder.py` | 6 | Embedding 生成（调用 OpenAI Embedding API） |
| `rag.py` | 8 | RAG 初筛（LlamaIndex + IVectorDB） |
| `matcher.py` | 8 | 三级匹配引擎（RAG初筛 → LLM精排 → 返回候选） |

**抽象层设计原则：** 所有 AI 服务（ASR/VLM/TTS/LLM/向量库）均定义抽象基类，具体实现通过工厂函数或配置项选择。替换服务商只需修改配置，不改业务代码。

---

## memory-bank/ — 项目文档

```
memory-bank/
├── projectbrief.md          # 项目简介（如有）
├── design-document.md       # 产品设计文档（最终极完善版）
├── implementation-plan.md   # 分阶段实施计划（Phase 0~12）
├── tech-stack.md            # 技术栈详细说明
├── architecture.md          # 本文件：架构说明，每个文件的职责
├── progress.md              # 开发进度记录，每完成一个 Phase 更新
└── feature-implementation/  # 功能实现细节（按需新增）
```

**规范：** 每完成一个 Phase，必须更新 `progress.md`（记录完成内容、验证结果、技术决策）；有架构变化时更新本文件（`architecture.md`）。

---

## 数据流总览

```
用户上传视频
    │
    ▼
POST /api/videos/upload
    │  写入 videos 表
    ▼
POST /api/videos/{id}/process  （一键处理，Phase 7）
    │
    ├─► splitter.py      → 切分片段，写入 clips 表
    ├─► splitter.py      → 抽帧，存 storage/frames/
    ├─► splitter.py      → 提取音频，存 storage/audio/
    ├─► WhisperASR       → 转写文本，写入 clips.asr_text
    ├─► OpenAIVLM        → 生成描述，写入 clips.vlm_description
    └─► embedder.py      → 生成向量，写入 clip_embeddings 表

用户输入文案
    │
    ▼
POST /api/match
    │
    ├─► RAGSearcher      → 向量检索 TOP12 候选片段
    ├─► OpenAILLM        → 精排，输出 TOP5 推荐
    └─► 返回 {recommended, candidates}

用户确认片段
    │
    ▼
POST /api/tts/synthesize  → edge-tts 生成配音
    │
    ▼
POST /api/export          → ZIP（project.json + audio.mp3）
```

---

## 当前已实现接口一览

| 方法 | 路径 | 状态 | 说明 |
|------|------|------|------|
| GET | `/health` | ✅ | 健康检查 |
| GET | `/api/config` | ✅ | 获取全部配置 |
| PATCH | `/api/config` | ✅ | 更新单条配置 |

