# LX_SmartClip 实施计划

> 原则：小步前进，每步可验证，先通基础链路，再叠 AI 能力。

---

## Phase 0：环境搭建与项目骨架

### 0.1 后端环境初始化

**任务：**
- 创建 Python 虚拟环境（Python >= 3.10）
- 创建 `backend/` 目录，初始化 `requirements.txt`
- 安装核心依赖：`fastapi uvicorn[standard] pydantic>=2.0 python-multipart aiosqlite`
- 创建 `app/main.py`，注册一个 `GET /health` 接口

**验证：**
```bash
uvicorn app.main:app --reload
curl http://localhost:8000/health
# 期望返回：{"status": "ok"}
```

---

### 0.2 前端环境初始化

**任务：**
- 创建 `frontend/` 目录
- 初始化 Next.js 14 项目（TypeScript + App Router + TailwindCSS）
- 安装 shadcn/ui、Lucide React、Zustand、Axios、TanStack Query
- 创建首页，展示「LX SmartClip」标题

**验证：**
```bash
npm run dev
# 浏览器访问 http://localhost:3000，页面正常渲染
```

---

### 0.3 前后端联通验证

**任务：**
- 前端配置 Axios baseURL 指向 `http://localhost:8000`
- 首页启动时调用 `/health`，展示后端状态

**验证：**
```
浏览器控制台无跨域报错，页面显示后端状态「已连接」
```

---

## Phase 1：数据库基础层

### 1.1 SQLite 数据库初始化

**任务：**
- 创建 `app/db/database.py`：aiosqlite 连接管理，单例模式
- 创建 `app/db/init.py`：建表 SQL（`videos`、`clips`、`config` 三张表，暂不建向量表）
- 服务启动时自动执行建表（表不存在则创建）

**验证：**
```bash
# 启动服务后，检查 SQLite 文件已生成，三张表存在
sqlite3 data/smartclip.db ".tables"
# 期望输出：clips  config  videos
```

---

### 1.2 全局配置表初始化

**任务：**
- 服务启动时向 `config` 表写入默认配置项（若 key 不存在才插入）：
  - `split_mode`: `scene`
  - `fixed_duration`: `10`
  - `scene_threshold`: `0.4`
  - `vector_dimension`: `1536`
  - `top_k`: `12`
  - `vlm_provider`: `openai`
  - `vlm_base_url`: `https://api.openai.com/v1`
  - `vlm_model`: `gpt-4o`
  - `vlm_api_key`: ``
  - `tts_provider`: `edge-tts`
  - `asr_model`: `base`
- 创建 `GET /api/config` 接口，返回全部配置
- 创建 `PATCH /api/config` 接口，接收 `{key, value}` 更新单条配置

**验证：**
```bash
curl http://localhost:8000/api/config
# 期望：返回包含所有默认 key 的 JSON
curl -X PATCH http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{"key": "top_k", "value": "20"}'
curl http://localhost:8000/api/config
# 期望：top_k 已变为 20
```

---

## Phase 2：视频上传与管理

### 2.1 视频上传接口

**任务：**
- 创建上传目录 `storage/videos/`
- 创建 `app/api/videos.py`：
  - `POST /api/videos/upload`：接收视频文件，保存到 `storage/videos/`，写入 `videos` 表（id、name、file_path、upload_at），返回视频 id
  - `GET /api/videos`：返回所有视频列表
  - `DELETE /api/videos/{id}`：删除视频记录与文件

**验证：**
```bash
curl -X POST http://localhost:8000/api/videos/upload \
  -F "file=@test.mp4"
# 期望：返回 {"id": "xxx", "name": "test.mp4"}
curl http://localhost:8000/api/videos
# 期望：返回包含刚上传视频的数组
```

---

### 2.2 前端素材库页面（基础版）

**任务：**
- 创建 `/`（素材库）页面
- 实现视频上传组件（拖拽 / 点击选择）
- 上传后展示视频卡片列表（名称、上传时间、状态）
- 支持删除视频

**验证：**
```
浏览器拖拽视频文件上传，页面出现视频卡片，刷新后仍存在，可删除
```

---

## Phase 3：视频切分（核心管线第一段）

### 3.1 FFmpeg 集成与音频提取

**任务：**
- 安装 `ffmpeg-python`，确认系统 FFmpeg 可用
- 创建 `app/core/splitter.py`：
  - `extract_audio(video_path) -> audio_path`：用 FFmpeg 提取音频为 WAV
- 创建 `POST /api/videos/{id}/extract-audio` 接口

**验证：**
```bash
curl -X POST http://localhost:8000/api/videos/{id}/extract-audio
# 期望：storage/audio/ 下生成对应 WAV 文件，接口返回音频路径
```

---

### 3.2 视频切分（双模式）

**任务：**
- 安装 `scenedetect[opencv]`
- `splitter.py` 新增两个函数：
  - `split_by_scene(video_path, threshold) -> list[ClipInfo]`：PySceneDetect 镜头切分
  - `split_by_fixed(video_path, duration) -> list[ClipInfo]`：FFmpeg 固定时长切分
  - `ClipInfo`: `{clip_path, start_time, end_time, duration}`
- 创建 `POST /api/videos/{id}/split` 接口：
  - 从 config 读取 `split_mode`、`scene_threshold`、`fixed_duration`
  - 执行对应切分，将结果写入 `clips` 表
  - 更新 `videos.total_clips` 和 `videos.split_mode`

**验证：**
```bash
curl -X POST http://localhost:8000/api/videos/{id}/split
# 期望：clips 表中有对应片段记录，storage/clips/ 下有切出的视频文件
curl http://localhost:8000/api/videos/{id}/clips
# 期望：返回片段列表，每条有 start_time、end_time、duration
```

---

### 3.3 抽帧

**任务：**
- `splitter.py` 新增 `extract_frames(clip_path, n_frames=3) -> list[frame_path]`：每个片段等间隔抽取 N 帧，存 `storage/frames/{clip_id}/`
- 切分完成后自动触发抽帧

**验证：**
```
切分后，storage/frames/{clip_id}/ 下存在 3 张 JPG 图片
```

---

## Phase 4：ASR 语音识别

### 4.1 ASR 抽象层

**任务：**
- 创建 `app/core/asr/base.py`：定义 `IASR` 抽象基类
- 创建 `app/core/asr/whisper_asr.py`：实现 `WhisperASR`
  - 安装 `openai-whisper`
  - 从 config 读取 `asr_model` 大小
  - `transcribe(audio_path) -> str`

**验证：**
```python
# 单元测试（直接运行脚本）
from app.core.asr.whisper_asr import WhisperASR
asr = WhisperASR(model_size="base")
result = asr.transcribe("test_audio.wav")
assert isinstance(result, str) and len(result) > 0
print("ASR OK:", result)
```

---

### 4.2 批量 ASR 处理

**任务：**
- 创建 `POST /api/videos/{id}/process-asr` 接口：
  - 遍历该视频所有片段
  - 提取每个片段音频（若未提取）
  - 调用 ASR，结果写入 `clips.asr_text`

**验证：**
```bash
curl -X POST http://localhost:8000/api/videos/{id}/process-asr
# 期望：clips 表中各片段 asr_text 字段有内容
curl http://localhost:8000/api/videos/{id}/clips
# 期望：返回的片段包含 asr_text
```

---

## Phase 5：VLM 视觉描述

### 5.1 VLM 抽象层

**任务：**
- 创建 `app/core/vlm/base.py`：定义 `IVLM` 抽象基类
- 创建 `app/core/vlm/openai_vlm.py`：实现 `OpenAIVLM`
  - 从 config 读取 `vlm_base_url`、`vlm_model`、`vlm_api_key`
  - `generate_description(frame_paths: list[str]) -> str`：base64 编码帧，调用 VLM 接口

**验证：**
```python
# 单元测试
from app.core.vlm.openai_vlm import OpenAIVLM
vlm = OpenAIVLM(base_url="...", model="gpt-4o", api_key="...")
result = vlm.generate_description(["frame1.jpg", "frame2.jpg"])
assert isinstance(result, str) and len(result) > 10
print("VLM OK:", result)
```

---

### 5.2 批量 VLM 处理

**任务：**
- 创建 `POST /api/videos/{id}/process-vlm` 接口：
  - 遍历所有片段，传入该片段的帧路径
  - 调用 VLM 生成描述，写入 `clips.vlm_description`

**验证：**
```bash
curl -X POST http://localhost:8000/api/videos/{id}/process-vlm
curl http://localhost:8000/api/videos/{id}/clips
# 期望：每个片段有非空的 vlm_description
```

---

## Phase 6：向量化与入库

### 6.1 SQLite-VSS 向量表初始化

**任务：**
- 安装 `sqlite-vss`
- `app/db/init.py` 新增：从 config 读取 `vector_dimension`，动态建立 `clip_embeddings` 虚拟表
- 创建 `app/core/vector_db.py`：
  - 定义 `IVectorDB` 抽象基类
  - 实现 `SQLiteVSSDB`：`add_embedding(clip_id, embedding)`、`search(embedding, top_k, video_ids=None) -> list[clip_id]`

**验证：**
```python
# 单元测试
from app.core.vector_db import SQLiteVSSDB
db = SQLiteVSSDB()
db.add_embedding("test-id", [0.1] * 1536)
results = db.search([0.1] * 1536, top_k=1)
assert results[0] == "test-id"
print("VectorDB OK")
```

---

### 6.2 Embedding 生成与入库

**任务：**
- 创建 `app/core/embedder.py`：
  - 调用 OpenAI Embedding API（`text-embedding-3-small` 默认）
  - `embed(text: str) -> list[float]`
- 创建 `POST /api/videos/{id}/process-embed` 接口：
  - 拼接每个片段的 `asr_text + vlm_description` 作为文本
  - 生成 embedding，写入向量表

**验证：**
```bash
curl -X POST http://localhost:8000/api/videos/{id}/process-embed
# 期望：向量表中有对应 rowid 记录
# 可用 sqlite3 查询 clip_embeddings 表行数
```

---

## Phase 7：全处理管线整合

### 7.1 一键处理接口

**任务：**
- 创建 `POST /api/videos/{id}/process`：串联执行
  1. 切分（读 config 模式）
  2. 抽帧
  3. 音频提取
  4. ASR
  5. VLM
  6. Embedding 入库
- 通过 WebSocket `ws://localhost:8000/ws/progress/{task_id}` 实时推送进度（`{step, total, message}`）
- `videos` 表新增 `status` 字段：`pending / processing / done / error`

**验证：**
```bash
curl -X POST http://localhost:8000/api/videos/{id}/process
# WebSocket 客户端（wscat）监听进度，逐步收到各阶段消息
# 完成后 videos.status = 'done'
```

---

### 7.2 前端处理进度页面

**任务：**
- 创建 `/process` 页面
- 点击「开始处理」后建立 WebSocket 连接，实时展示处理进度条与步骤日志
- 处理完成后展示片段列表（缩略图、时长、ASR 文本、VLM 描述）

**验证：**
```
触发处理后，页面进度条逐步推进，5 个步骤依次完成
处理完成后片段列表展示正确
```

---

## Phase 8：三级匹配引擎

### 8.1 RAG 初筛

**任务：**
- 安装 `llama-index`
- 创建 `app/core/rag.py`：
  - `search(query: str, video_ids: list[str] = None, top_k: int = 12) -> list[clip_id]`
  - 对 query 生成 embedding，调用 `IVectorDB.search()`，支持按 `video_ids` 过滤

**验证：**
```python
from app.core.rag import RAGSearcher
searcher = RAGSearcher()
results = searcher.search("产品介绍开场", top_k=12)
assert len(results) <= 12
assert all(isinstance(r, str) for r in results)
print("RAG OK:", results)
```

---

### 8.2 LLM 精排

**任务：**
- 创建 `app/core/llm/base.py`：定义 `ILLM` 抽象基类
- 创建 `app/core/llm/openai_llm.py`：实现 `OpenAILLM`
  - `rerank(query: str, candidates: list[dict]) -> list[dict]`
  - 构造 prompt，让 LLM 对候选片段打分/排序，返回 TOP5
- 创建 `app/core/matcher.py`：
  - `match(query, video_ids) -> {recommended: list, candidates: list}`
  - 串联 RAG 初筛 → LLM 精排 → 返回全部候选供前端展示

**验证：**
```python
from app.core.matcher import Matcher
matcher = Matcher()
result = matcher.match("展示产品功能的片段", video_ids=None)
assert "recommended" in result
assert "candidates" in result
assert len(result["recommended"]) <= 5
print("Matcher OK")
```

---

### 8.3 匹配接口

**任务：**
- 创建 `POST /api/match`：
  - 接收 `{query: str, video_ids: list[str]}`
  - 调用 `Matcher.match()`
  - 返回 `{recommended: [clip详情], candidates: [clip详情]}`

**验证：**
```bash
curl -X POST http://localhost:8000/api/match \
  -H "Content-Type: application/json" \
  -d '{"query": "产品开场介绍", "video_ids": []}'
# 期望：返回 recommended（≤5条）和 candidates（≤12条），每条含 clip 详情
```

---

### 8.4 前端文案匹配页面

**任务：**
- 创建 `/match` 页面
- 左侧：文案输入框 + 勾选要检索的视频
- 右侧：匹配结果
  - 推荐片段（蓝色高亮卡片，LLM 推荐）
  - 备选片段（灰色卡片，一键替换）
- 支持：替换片段、增删片段、拖拽调整顺序

**验证：**
```
输入文案点击匹配，结果卡片正确展示
点击备选片段「替换」按钮，主选片段更新
拖拽卡片可重排顺序
```

---

## Phase 9：TTS 配音

### 9.1 TTS 抽象层

**任务：**
- 安装 `edge-tts`
- 创建 `app/core/tts/base.py`：定义 `ITTS` 抽象基类
- 创建 `app/core/tts/edge_tts_impl.py`：实现 `EdgeTTS`
  - 从 config 读取音色、语速
  - `synthesize(text: str, output_path: str) -> str`

**验证：**
```python
from app.core.tts.edge_tts_impl import EdgeTTS
tts = EdgeTTS()
path = tts.synthesize("这是一段测试配音", "test_output.mp3")
import os
assert os.path.exists(path) and os.path.getsize(path) > 0
print("TTS OK")
```

---

### 9.2 配音接口

**任务：**
- 创建 `POST /api/tts/synthesize`：
  - 接收 `{text: str}`
  - 生成配音文件，返回文件下载路径
- 创建 `GET /api/tts/voices`：返回可用音色列表

**验证：**
```bash
curl -X POST http://localhost:8000/api/tts/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "你好，欢迎使用智能剪辑工具"}'
# 期望：返回音频文件路径，可直接下载播放
```

---

## Phase 10：导出功能

### 10.1 导出接口

**任务：**
- 创建 `POST /api/export`：
  - 接收 `{clips: list[clip_id], text: str, audio_path: str}`
  - 生成导出文件（JSON 格式）：
    ```json
    {
      "text": "...",
      "audio": "path/to/audio.mp3",
      "clips": [
        {"clip_path": "...", "start": 0.0, "end": 5.2, "duration": 5.2}
      ]
    }
    ```
  - 返回可下载的 ZIP 包（JSON 工程文件 + 音频文件）

**验证：**
```bash
curl -X POST http://localhost:8000/api/export \
  -H "Content-Type: application/json" \
  -d '{"clips": ["id1","id2"], "text": "文案内容", "audio_path": "..."}'
# 期望：返回可下载 ZIP，解压后含 project.json 和 audio.mp3
```

---

### 10.2 前端配音导出页面

**任务：**
- 创建 `/export` 页面
- 展示最终片段列表 + 文案预览
- TTS 配音按钮，生成后可在线试听
- 「导出工程文件」按钮，触发下载

**验证：**
```
点击生成配音，音频控件可播放
点击导出，浏览器下载 ZIP 文件，解压后结构正确
```

---

## Phase 11：系统设置页面

### 11.1 前端设置页

**任务：**
- 创建 `/settings` 页面
- 从 `GET /api/config` 读取配置，动态渲染表单（文本框、下拉、滑块）
- 修改后调用 `PATCH /api/config` 保存
- 支持配置导出（下载 config.json）与导入（上传 config.json）

**验证：**
```
修改 top_k 值保存后，刷新页面值仍保持
导出 config.json 内容正确
导入后配置项正确更新
```

---

## Phase 12：集成测试与收尾

### 12.1 完整链路端到端测试

**测试场景：**
1. 上传一个真实视频文件（建议 1~3 分钟）
2. 触发一键处理，等待完成
3. 在匹配页输入文案，执行三级匹配
4. 手动替换一个片段
5. 生成 TTS 配音
6. 导出工程文件，验证内容正确

**通过标准：**
- 全流程无报错
- 切分片段数量合理
- ASR 文本可读
- VLM 描述与画面相符
- 匹配结果与文案相关
- 导出 ZIP 可正常解压

---

### 12.2 错误处理补全

**任务：**
- 上传非视频文件时，返回 400 错误提示
- VLM/ASR API Key 未配置时，接口返回友好错误信息（而非 500）
- 前端对所有接口错误进行 Toast 提示

---

## 阶段里程碑总览

| Phase | 内容 | 完成标志 |
|-------|------|----------|
| 0 | 环境骨架 | 前后端启动，/health 通 |
| 1 | 数据库基础 | 三表建立，配置读写正常 |
| 2 | 视频上传 | 上传/列表/删除正常 |
| 3 | 视频切分 | 双模式切分，抽帧正常 |
| 4 | ASR | 片段字幕入库 |
| 5 | VLM | 片段描述入库 |
| 6 | 向量化 | 向量检索返回正确结果 |
| 7 | 处理管线 | 一键处理 + 进度推送 |
| 8 | 三级匹配 | 匹配返回推荐+备选，前端可替换 |
| 9 | TTS | 配音生成可播放 |
| 10 | 导出 | ZIP 导出结构正确 |
| 11 | 设置页 | 配置修改即时生效 |
| 12 | 收尾 | 端到端全链路无报错 |

