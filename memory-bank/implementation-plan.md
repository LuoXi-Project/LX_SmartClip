# LX_SmartClip 实施计划

> 原则：小步前进，每步可验证，先通基础链路，再叠 AI 能力。

---

## Phase 0：环境搭建与项目骨架

### 0.1 后端环境初始化

**✅ 已完成**
- 后端环境已初始化，FastAPI 应用正常启动
- `/health` 接口已实现
- CORS 中间件已配置（允许 localhost:3000）
- lifespan 钩子已注册，服务启动时自动初始化数据库

---

### 0.2 前端环境初始化

**✅ 已完成**
- Next.js 14 项目结构完整（TypeScript + App Router）
- TailwindCSS 已配置
- 核心依赖已安装（Lucide React、Zustand、Axios、TanStack Query）
- 全局样式和配置已设置
- API 客户端和状态管理已实现
- 首页展示「LX SmartClip」标题和系统状态
- 首页包含后端健康检查（5秒轮询）

---

### 0.3 前后端联通验证

**✅ 已完成**
- 前端配置 Axios baseURL 指向 `http://localhost:8000`
- 首页启动时调用 `/health`，展示后端状态
- CORS 配置正确，无跨域报错
- 首页显示后端连接状态（已连接/未连接/检查中）

---

## Phase 1：数据库基础层

### 1.1 SQLite 数据库初始化

**✅ 已完成**
- `app/db/database.py` 已实现，提供 `get_db_conn()` 异步连接管理
- `app/db/init_db.py` 已实现，包含三张表的 CREATE TABLE 语句
- 数据库文件路径使用绝对路径计算，与工作目录无关
- 表结构设计完整：
  - `videos`：id, name, file_path, duration, total_clips, split_mode, status, upload_at
  - `clips`：id, video_id, clip_path, start_time, end_time, duration, asr_text, vlm_description, tags
  - `config`：key, value, type, label, options

---

### 1.2 全局配置表初始化

**✅ 已完成**
- 11 条默认配置项已定义并在启动时初始化（INSERT OR IGNORE）
- `app/api/config.py` 已实现 GET 和 PATCH 接口
- 配置项支持动态读写，前端可直接修改
- 配置表结构支持前端动态渲染表单（type、label、options 字段）

---

## Phase 2：视频上传与管理

### 2.1 视频上传接口

**✅ 已完成**
- `app/api/videos.py` 已实现三个接口
- 支持多种视频格式（mp4, mov, avi, mkv, webm, mpeg）
- 文件上传使用 UUID 生成唯一 ID，保留原始扩展名
- 视频列表按上传时间倒序排列
- 删除时同时删除数据库记录和物理文件

---

### 2.2 前端素材库页面

**✅ 已完成**
- 创建 `/library` 页面（素材库）
- 实现视频上传组件（拖拽 / 点击选择）
- 上传后展示视频卡片列表（名称、上传时间、状态、片段数）
- 支持删除视频
- 视频卡片展示状态徽章（待处理/处理中/已完成/错误）
- 拖拽上传区域有视觉反馈
- 支持批量上传

---

## Phase 3：视频切分（核心管线第一段）

### 3.1 FFmpeg 集成与音频提取

**任务：**
- 安装 `ffmpeg-python`，确认系统 FFmpeg 可用
- 创建 `app/core/splitter.py`：
  - `extract_audio(video_path) -> audio_path`：用 FFmpeg 提取音频为 WAV
- 创建 `POST /api/videos/{id}/extract-audio` 接口

**⏳ 待完成**

---

### 3.2 视频切分（双模式）

**任务：**
- 安装 `scenedetect[opencv]`
- `splitter.py` 新增两个函数：
  - `split_by_scene(video_path, threshold) -> list[ClipInfo]`：PySceneDetect 镜头切分
  - `split_by_fixed(video_path, duration) -> list[ClipInfo]`：FFmpeg 固定时长切分
- 创建 `POST /api/videos/{id}/split` 接口

**⏳ 待完成**

---

### 3.3 抽帧

**任务：**
- `splitter.py` 新增 `extract_frames(clip_path, n_frames=3) -> list[frame_path]`
- 切分完成后自动触发抽帧

**⏳ 待完成**

---

## Phase 4：ASR 语音识别

### 4.1 ASR 抽象层

**任务：**
- 创建 `app/core/asr/base.py`：定义 `IASR` 抽象基类
- 创建 `app/core/asr/whisper_asr.py`：实现 `WhisperASR`

**⏳ 待完成**

---

### 4.2 批量 ASR 处理

**任务：**
- 创建 `POST /api/videos/{id}/process-asr` 接口

**⏳ 待完成**

---

## Phase 5：VLM 视觉描述

### 5.1 VLM 抽象层

**任务：**
- 创建 `app/core/vlm/base.py`：定义 `IVLM` 抽象基类
- 创建 `app/core/vlm/openai_vlm.py`：实现 `OpenAIVLM`

**⏳ 待完成**

---

### 5.2 批量 VLM 处理

**任务：**
- 创建 `POST /api/videos/{id}/process-vlm` 接口

**⏳ 待完成**

---

## Phase 6：向量化与入库

### 6.1 FAISS 向量表初始化

**任务：**
- 安装 `faiss-cpu`
- 创建 `app/core/vector_db/faiss_db.py`

**⏳ 待完成**

---

### 6.2 Embedding 生成与入库

**任务：**
- 创建 `app/core/embedder.py`
- 创建 `POST /api/videos/{id}/process-embed` 接口

**⏳ 待完成**

---

## Phase 7：全处理管线整合

### 7.1 一键处理接口

**任务：**
- 创建 `POST /api/videos/{id}/process`：串联执行所有处理步骤
- 通过 WebSocket 实时推送进度

**⏳ 待完成**

---

### 7.2 前端处理进度页面

**任务：**
- 创建 `/process` 页面
- 实时展示处理进度条与步骤日志

**⏳ 待完成**

---

## Phase 8：三级匹配引擎

### 8.1 RAG 初筛

**任务：**
- 安装 `llama-index`
- 创建 `app/core/rag.py`

**⏳ 待完成**

---

### 8.2 LLM 精排

**任务：**
- 创建 `app/core/llm/base.py` 和 `app/core/llm/openai_llm.py`
- 创建 `app/core/matcher.py`

**⏳ 待完成**

---

### 8.3 匹配接口

**任务：**
- 创建 `POST /api/match` 接口

**⏳ 待完成**

---

### 8.4 前端文案匹配页面

**任务：**
- 创建 `/match` 页面

**⏳ 待完成**

---

## Phase 9：TTS 配音

### 9.1 TTS 抽象层

**任务：**
- 安装 `edge-tts`
- 创建 `app/core/tts/base.py` 和 `app/core/tts/edge_tts_impl.py`

**⏳ 待完成**

---

### 9.2 配音接口

**任务：**
- 创建 `POST /api/tts/synthesize` 接口
- 创建 `GET /api/tts/voices` 接口

**⏳ 待完成**

---

## Phase 10：导出功能

### 10.1 导出接口

**任务：**
- 创建 `POST /api/export` 接口

**⏳ 待完成**

---

### 10.2 前端配音导出页面

**任务：**
- 创建 `/export` 页面

**⏳ 待完成**

---

## Phase 11：系统设置页面

### 11.1 前端设置页

**任务：**
- 创建 `/settings` 页面

**⏳ 待完成**

---

## Phase 12：集成测试与收尾

### 12.1 完整链路端到端测试

**⏳ 待完成**

---

### 12.2 错误处理补全

**⏳ 待完成**

---

## 阶段里程碑总览

| Phase | 内容 | 状态 |
|-------|------|------|
| 0 | 环境骨架 | ✅ 完成 |
| 1 | 数据库基础 | ✅ 完成 |
| 2 | 视频上传 | ✅ 完成 |
| 3 | 视频切分 | ⏳ 待做 |
| 4 | ASR | ⏳ 待做 |
| 5 | VLM | ⏳ 待做 |
| 6 | 向量化 | ⏳ 待做 |
| 7 | 处理管线 | ⏳ 待做 |
| 8 | 三级匹配 | ⏳ 待做 |
| 9 | TTS | ⏳ 待做 |
| 10 | 导出 | ⏳ 待做 |
| 11 | 设置页 | ⏳ 待做 |
| 12 | 收尾 | ⏳ 待做 |

---

## 当前进度总结

**已完成（Phase 0-2）：**
- 后端环境搭建 + FastAPI 框架
- 前端环境搭建 + Next.js 14 框架
- 前后端联通验证（健康检查）
- 数据库三表设计 + 配置管理
- 视频上传/列表/删除接口
- 前端素材库页面（拖拽上传、卡片展示、删除功能）

**下一步优先级：**
1. Phase 3：视频切分（FFmpeg + PySceneDetect 双模式）
2. Phase 4-5：ASR + VLM 处理
3. Phase 6-8：向量化 + 三级匹配引擎
4. Phase 9-12：TTS、导出、设置、测试
