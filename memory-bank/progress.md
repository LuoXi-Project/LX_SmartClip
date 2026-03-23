# LX_SmartClip 开发进度记录

## 当前阶段
Phase 0-8 已完成，Phase 9（TTS 配音）准备开始。

---

## 已完成工作

### Phase 0：环境搭建与项目骨架（✅ 完成）
- FastAPI 后端初始化（`/health`、CORS、lifespan）
- Next.js 14 前端初始化（TypeScript + Tailwind + Zustand + Axios）
- 前后端联通（首页健康检查）

### Phase 1：数据库基础层（✅ 完成）
- SQLite 三表：`videos`、`clips`、`config`
- 配置管理接口：`GET /api/config`、`PATCH /api/config`

### Phase 2：视频上传与管理（✅ 完成）
- `POST /api/videos/upload`
- `GET /api/videos`
- `DELETE /api/videos/{id}`
- 前端素材库页面 `/library`

### Phase 3：视频切分（✅ 完成）
- `app/core/splitter.py`：音频提取、固定时长切分、镜头切分、抽帧
- `app/api/clips.py`：
  - `POST /api/videos/{id}/extract-audio`
  - `POST /api/videos/{id}/split`
  - `POST /api/videos/{id}/extract-frames`
  - `GET /api/videos/{id}/clips`

### Phase 4：ASR 语音识别（✅ 完成）
- `app/core/asr/base.py` + `app/core/asr/whisper_asr.py`
- `app/api/asr.py`：
  - `POST /api/videos/{id}/process-asr`
  - `GET /api/asr/info`

### Phase 5：VLM 视觉描述（✅ 完成）
- `app/core/vlm/base.py` + `app/core/vlm/openai_vlm.py`
- `app/api/vlm.py`：
  - `POST /api/videos/{id}/process-vlm`
  - `GET /api/vlm/info`

### Phase 6：向量化与入库（✅ 完成）
- `app/core/vector_db/base.py` + `app/core/vector_db/sqlite_vss.py`
- `app/core/embedder.py`
- `app/api/embed.py`：
  - `POST /api/videos/{id}/process-embed`

### Phase 7：全处理管线整合（✅ 完成）
- `app/api/process.py`：
  - `POST /api/videos/{id}/process`
  - `WS /api/videos/{id}/process-ws`
- 前端处理页面：`/process`

### Phase 8：三级匹配引擎（✅ 完成）
- `app/core/rag.py`：RAG 初筛（Embedding + SQLiteVSS）
- `app/core/llm/base.py` + `app/core/llm/openai_llm.py`：LLM 精排
- `app/core/matcher.py`：初筛 + 精排 + 推荐
- `app/api/match.py`：
  - `POST /api/match`
- 前端匹配页面：`/match`
- 导航新增“文案匹配”入口
- 配置新增：`llm_model`、`match_top_k`、`match_top_n`

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
| POST | `/api/videos/{id}/process` | 一键全流程处理 |
| WS | `/api/videos/{id}/process-ws` | 实时进度推送 |
| POST | `/api/match` | 文案匹配（三级匹配引擎） |

---

## 下一步：Phase 9 — TTS 配音

**优先级：** 🔴 高

**任务：**
1. `app/core/tts/base.py` + `app/core/tts/edge_tts_impl.py`
2. `POST /api/tts/synthesize`
3. `GET /api/tts/voices`
4. 前端配音与导出工作流联调

---

**最后更新：** 2026-03-23
**状态：** ✅ Phase 0-8 完成，Phase 9 准备开始
