# LX_SmartClip 开发进度记录

## 当前阶段
Phase 0-6 已完成，Phase 7（处理管线整合）准备开始。

---

## 已完成工作

### Phase 0：环境搭建与项目骨架（✅ 完成）

#### 0.1 后端环境
- FastAPI 框架初始化，`/health` 接口，CORS 中间件，lifespan 钩子

#### 0.2 前端环境
- Next.js 14 + TypeScript + TailwindCSS + Zustand + Axios

#### 0.3 前后端联通
- Axios API 客户端，首页健康检查（5秒轮询），后端状态显示

---

### Phase 1：数据库基础层（✅ 完成）

#### 1.1 SQLite 数据库初始化
- `app/db/database.py`：aiosqlite 连接管理
- `app/db/init_db.py`：三张表建表 SQL
  - `videos`：id, name, file_path, duration, total_clips, split_mode, status, upload_at
  - `clips`：id, video_id, clip_path, start_time, end_time, duration, asr_text, vlm_description, tags
  - `config`：key, value, type, label, options

#### 1.2 全局配置表
- 11 条默认配置项（INSERT OR IGNORE）
- `GET /api/config`，`PATCH /api/config`

---

### Phase 2：视频上传与管理（✅ 完成）

#### 2.1 视频上传接口
- `POST /api/videos/upload`：多格式支持，UUID 管理
- `GET /api/videos`：按时间倒序
- `DELETE /api/videos/{id}`：同时删除文件

#### 2.2 前端素材库页面
- `/library` 页面：拖拽上传、卡片展示、状态徽章、删除功能

---

### Phase 3：视频切分（✅ 完成）

- `app/core/splitter.py`：VideoSplitter 类
  - `extract_audio()` - FFmpeg 音频提取为 WAV
  - `get_video_duration()` - 获取视频时长
  - `split_by_fixed()` - 固定时长切分
  - `split_by_scene()` - PySceneDetect 镜头识别
  - `extract_frames()` - 等间隔抽帧
- `app/api/clips.py`：
  - `POST /api/videos/{id}/extract-audio`
  - `POST /api/videos/{id}/split`（读 config 模式）
  - `POST /api/videos/{id}/extract-frames`
  - `GET /api/videos/{id}/clips`
- 新增依赖：`ffmpeg-python`, `scenedetect[opencv]`

---

### Phase 4：ASR 语音识别（✅ 完成）

- `app/core/asr/base.py`：IASR 抽象接口
- `app/core/asr/whisper_asr.py`：WhisperASR 实现
  - 支持 tiny/base/small/medium/large 模型
  - 支持 CPU/GPU，中文优化
- `app/api/asr.py`：
  - `POST /api/videos/{id}/process-asr`
  - `GET /api/asr/info`
- 新增依赖：`openai-whisper`

---

### Phase 5：VLM 视觉描述（✅ 完成）

- `app/core/vlm/base.py`：IVLM 抽象接口
- `app/core/vlm/openai_vlm.py`：OpenAIVLM 实现
  - OpenAI 兼容 API，Base64 图像编码，中文描述
- `app/api/vlm.py`：
  - `POST /api/videos/{id}/process-vlm`（自动抽帧）
  - `GET /api/vlm/info`
- 新增依赖：`openai`

---

### Phase 6：向量化与入库（✅ 完成）

- `app/core/vector_db/base.py`：IVectorDB 抽象接口
- `app/core/vector_db/sqlite_vss.py`：SQLiteVSSDB 实现
  - 动态向量维度，支持 video_ids 过滤搜索
  - 增删改查完整实现
- `app/core/embedder.py`：Embedder 文本向量化
  - 调用 OpenAI Embedding API，支持批量
- `app/api/embed.py`：
  - `POST /api/videos/{id}/process-embed`（拼接 asr_text + vlm_description）
- 新增依赖：`sqlite-vss`

---

## 后端文件全览

```
backend/
├── requirements.txt             # fastapi, uvicorn, aiosqlite, ffmpeg-python,
│                                # scenedetect, openai-whisper, openai, sqlite-vss
└── app/
    ├── main.py                  # FastAPI 入口，注册所有路由
    ├── api/
    │   ├── config.py            # GET/PATCH /api/config
    │   ├── videos.py            # upload / list / delete
    │   ├── clips.py             # split / extract-audio / extract-frames / clips
    │   ├── asr.py               # process-asr
    │   ├── vlm.py               # process-vlm
    │   └── embed.py             # process-embed
    ├── core/
    │   ├── splitter.py          # 视频切分（双模式+音频+抽帧）
    │   ├── embedder.py          # OpenAI Embedding
    │   ├── asr/
    │   │   ├── base.py          # IASR
    │   │   └── whisper_asr.py   # Whisper 实现
    │   ├── vlm/
    │   │   ├── base.py          # IVLM
    │   │   └── openai_vlm.py    # OpenAI Vision 实现
    │   └── vector_db/
    │       ├── base.py          # IVectorDB
    │       └── sqlite_vss.py    # SQLite-VSS 实现
    └── db/
        ├── database.py          # 连接管理
        └── init_db.py           # 建表初始化
```

---

## 前端文件全览

```
frontend/
├── app/
│   ├── page.tsx                 # 首页（健康检查 + 功能介绍）
│   ├── library/page.tsx         # 素材库（上传/列表/删除）
│   ├── layout.tsx               # 根布局
│   └── globals.css              # 全局样式（深色主题）
├── lib/
│   ├── api.ts                   # Axios 客户端
│   └── store.ts                 # Zustand 状态管理
├── package.json
├── tsconfig.json
├── tailwind.config.js
└── .env.local                   # NEXT_PUBLIC_API_URL
```

---

## 当前已实现接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/config` | 获取全部配置 |
| PATCH | `/api/config` | 更新单条配置 |
| POST | `/api/videos/upload` | 上传视频 |
| GET | `/api/videos` | 视频列表 |
| DELETE | `/api/videos/{id}` | 删除视频 |
| POST | `/api/videos/{id}/split` | 切分视频 |
| POST | `/api/videos/{id}/extract-audio` | 提取音频 |
| POST | `/api/videos/{id}/extract-frames` | 批量抽帧 |
| GET | `/api/videos/{id}/clips` | 片段列表 |
| POST | `/api/videos/{id}/process-asr` | ASR 批量处理 |
| POST | `/api/videos/{id}/process-vlm` | VLM 批量处理 |
| POST | `/api/videos/{id}/process-embed` | Embedding 入库 |

---

## 技术决策记录

### 1. 数据库路径策略
`DB_PATH` 使用 `__file__` 相对路径计算绝对路径，保证任意位置启动正常。

### 2. 向量存储策略
SQLite-VSS 虚拟表 + 映射表，支持动态维度，无需外部服务。

### 3. Embedding 文本构造
拼接 `asr_text + vlm_description`，多模态信息融合，提升检索准确度。

### 4. VLM 单例模式
ASR/VLM 实例使用模块级单例，避免重复加载模型。

### 5. Windows 开发环境
- PowerShell 使用 `;` 分隔命令
- venv 位于 `f:\LuoXi-Project\LX_SmartClip\venv\`

---

## 快速启动

### 后端
```bash
cd backend
venv\Scripts\activate
uvicorn app.main:app --reload
```

### 前端
```bash
cd frontend
npm run dev
```

---

## 下一步：Phase 7 — 全处理管线整合

**优先级：** 🔴 高

**任务：**
1. `POST /api/videos/{id}/process` - 一键处理接口（串联所有步骤）
2. WebSocket 实时进度推送
3. 前端处理进度页面

---

**最后更新：** 2026-03-23
**状态：** ✅ Phase 0-6 完成，Phase 7 准备开始
