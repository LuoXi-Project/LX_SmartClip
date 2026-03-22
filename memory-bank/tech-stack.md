# LX_SmartClip 技术栈文档

## 一、总体技术架构概览

本项目采用前后端分离架构，后端提供 RESTful API，前端独立部署，所有 AI 服务模块均通过抽象接口实现，支持无缝替换模型/服务商。全程本地运行，数据存储使用单文件 SQLite，无外部服务依赖，拷贝即移植。

---

## 二、后端技术栈

### 2.1 核心框架

| 技术 | 版本要求 | 用途 |
|------|----------|------|
| Python | >= 3.10 | 后端主语言 |
| FastAPI | latest | Web 框架，提供 RESTful API + WebSocket |
| Uvicorn | latest | ASGI 服务器 |
| Pydantic | v2 | 数据校验与配置模型 |

### 2.2 视频处理

| 技术 | 用途 |
|------|------|
| FFmpeg | 视频切分、抽帧、抽取音频 |
| PySceneDetect | 智能镜头识别切分（模式 A）|
| ffmpeg-python | Python 调用 FFmpeg 的封装库 |

**切分双模式：**
- **模式 A（默认）**：PySceneDetect 镜头识别，自动识别镜头切换点，结果自然
- **模式 B**：固定时长切分（5s / 10s / 15s 可选），适合课程、录屏等无镜头变化素材

### 2.3 ASR 语音识别（抽象层）

| 实现 | 说明 |
|------|------|
| Whisper（默认） | OpenAI 开源本地模型，支持 tiny/base/small/medium/large |
| OpenAI Whisper API | 在线替换方案 |
| 讯飞 ASR | 备选在线方案 |

**抽象接口：**
```python
class IASR:
    def transcribe(self, audio_path: str) -> str:
        ...
```

### 2.4 VLM 视觉语言模型（抽象层）

| 实现 | 说明 |
|------|------|
| GPT-4V / GPT-4o（默认） | OpenAI 标准协议，通过 base_url 配置 |
| Qwen-VL | 阿里通义视觉模型 |
| MiniCPM-V | 本地轻量 VLM |
| 任意 OpenAI 兼容 VLM | 只需修改 base_url + model_name |

**抽象接口：**
```python
class IVLM:
    def generate_description(self, frame_paths: list[str]) -> str:
        ...
```

### 2.5 TTS 文字转语音（抽象层）

| 实现 | 说明 |
|------|------|
| edge-tts（默认） | 微软 Edge 免费 TTS，无需 API Key |
| OpenAI TTS | 在线替换，音质更高 |
| 火山 TTS | 字节跳动 TTS 服务 |

**抽象接口：**
```python
class ITTS:
    def synthesize(self, text: str, output_path: str) -> str:
        ...
```

### 2.6 LLM 大语言模型（抽象层）

| 实现 | 说明 |
|------|------|
| GPT-4o / GPT-4（默认） | OpenAI 标准协议 |
| 通义千问 | OpenAI 兼容接口 |
| 任意 OpenAI 兼容 LLM | 修改 base_url 即可 |

**抽象接口：**
```python
class ILLM:
    def chat(self, messages: list) -> str:
        ...
    def rerank(self, query: str, candidates: list) -> list:
        ...
```

### 2.7 RAG 检索增强生成

| 技术 | 用途 |
|------|------|
| LlamaIndex | RAG 框架，负责向量检索与上下文组装 |
| sqlite-vss | SQLite 向量扩展，支持任意维度向量存储与 ANN 检索 |

**向量维度动态配置：**
- 配置文件中指定 `vector_dimension`（默认 1536，支持 768 / 1024 / 1536）
- SQLite-VSS 建表时动态读取维度，切换 Embedding 模型无需重建表结构

**抽象接口：**
```python
class IVectorDB:
    def add_embedding(self, id: str, embedding: list[float]) -> None:
        ...
    def search(self, embedding: list[float], top_k: int) -> list:
        ...
```

### 2.8 数据存储

| 技术 | 用途 |
|------|------|
| SQLite | 元数据 + 向量一体化存储，单文件，零依赖 |
| sqlite-vss | SQLite 向量检索扩展 |

**数据库表结构：**

```sql
-- 原视频表
CREATE TABLE videos (
    id TEXT PRIMARY KEY,
    name TEXT,
    file_path TEXT,
    duration REAL,
    total_clips INTEGER,
    split_mode TEXT,   -- 'scene' | 'fixed'
    upload_at TEXT
);

-- 片段表
CREATE TABLE clips (
    id TEXT PRIMARY KEY,
    video_id TEXT,
    clip_path TEXT,
    start_time REAL,
    end_time REAL,
    duration REAL,
    asr_text TEXT,
    vlm_description TEXT,
    tags TEXT
);

-- 向量表（动态维度）
CREATE VIRTUAL TABLE clip_embeddings USING vss0(
    embedding(1536)   -- 维度从 config 动态读取
);

-- 全局配置表
CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT,
    type TEXT,
    label TEXT,
    options TEXT
);
```

### 2.9 配置管理

- 配置文件：`config.json`（可导入导出，移植方便）
- 前端配置页直接读写 `config` 表
- 配置变更即时生效，无需重启服务

---

## 三、前端技术栈

### 3.1 核心框架

| 技术 | 版本要求 | 用途 |
|------|----------|------|
| Next.js | >= 14 (App Router) | 前端框架，SSR + CSR |
| React | >= 18 | UI 组件库基础 |
| TypeScript | >= 5 | 类型安全 |

### 3.2 UI 与样式

| 技术 | 用途 |
|------|------|
| TailwindCSS | 原子化 CSS，快速布局与样式 |
| shadcn/ui | 高质量无头组件库（基于 Radix UI）|
| Lucide React | 图标库 |

### 3.3 状态管理与数据请求

| 技术 | 用途 |
|------|------|
| Zustand | 轻量全局状态管理 |
| TanStack Query (React Query) | 服务端数据请求、缓存与同步 |
| Axios | HTTP 客户端 |

### 3.4 实时通信

| 技术 | 用途 |
|------|------|
| WebSocket（原生 / Next.js） | 处理进度实时推送 |

---

## 四、三级素材匹配引擎

| 阶段 | 技术 | 说明 |
|------|------|------|
| 第一级：RAG 初筛 | LlamaIndex + sqlite-vss | 向量检索 TOP12 候选片段 |
| 第二级：LLM 精排 | ILLM 抽象层 | 大模型重排序，输出 TOP3~5 最优 |
| 第三级：人工自选 | 前端交互 | 展示所有候选，用户手动替换/增删/调序 |

---

## 五、后端项目结构

```
app/
├── core/
│   ├── config.py          # 全局配置单例
│   ├── splitter.py        # 双模式切分（抽象）
│   ├── asr/
│   │   ├── base.py        # IASR 接口
│   │   └── whisper.py     # Whisper 实现
│   ├── vlm/
│   │   ├── base.py        # IVLM 接口
│   │   └── openai_vlm.py  # OpenAI 兼容实现
│   ├── tts/
│   │   ├── base.py        # ITTS 接口
│   │   └── edge_tts.py    # edge-tts 实现
│   ├── llm/
│   │   ├── base.py        # ILLM 接口
│   │   └── openai_llm.py  # OpenAI 兼容实现
│   ├── vector_db.py       # IVectorDB 抽象 + SQLite-VSS 实现
│   ├── rag.py             # LlamaIndex RAG 封装
│   └── matcher.py         # 三级匹配引擎
├── api/
│   ├── videos.py          # 视频上传/管理路由
│   ├── clips.py           # 片段管理路由
│   ├── match.py           # 匹配路由
│   ├── tts.py             # 配音路由
│   └── config.py          # 配置读写路由
├── db/
│   ├── database.py        # SQLite 连接管理
│   └── models.py          # ORM 模型
└── main.py                # FastAPI 入口
```

---

## 六、前端页面结构

| 页面 | 路由 | 核心功能 |
|------|------|----------|
| 素材库 | `/` | 上传视频、勾选素材、预览、触发处理 |
| 素材处理 | `/process` | 处理进度、片段列表、ASR/VLM 结果查看 |
| 文案匹配 | `/match` | 输入文案、三级筛选、人工选片段、调序 |
| 配音导出 | `/export` | TTS 生成配音、导出工程文件 |
| 系统设置 | `/settings` | 全局配置中心（模型、参数、API Key） |

---

## 七、开发环境依赖

### 后端 `requirements.txt`（核心）

```
fastapi
uvicorn[standard]
pydantic>=2.0
python-multipart
ffmpeg-python
scenedetect[opencv]
openai
whisper
edge-tts
llama-index
sqlite-vss
aiosqlite
```

### 前端 `package.json`（核心依赖）

```json
{
  "dependencies": {
    "next": "^14.0.0",
    "react": "^18.0.0",
    "react-dom": "^18.0.0",
    "typescript": "^5.0.0",
    "tailwindcss": "^3.0.0",
    "@shadcn/ui": "latest",
    "zustand": "^4.0.0",
    "@tanstack/react-query": "^5.0.0",
    "axios": "^1.0.0",
    "lucide-react": "latest"
  }
}
```

---

## 八、可插拔扩展路线图

| 模块 | 当前默认 | 可替换为 |
|------|----------|----------|
| ASR | Whisper (本地) | OpenAI Whisper API / 讯飞 |
| VLM | GPT-4o (OpenAI) | Qwen-VL / MiniCPM-V / 本地 VLM |
| TTS | edge-tts | OpenAI TTS / 火山 TTS |
| LLM | GPT-4o (OpenAI) | 通义千问 / 任意 OpenAI 兼容 LLM |
| 向量库 | SQLite-VSS | FAISS / Chroma / Milvus |
| Embedding | OpenAI text-embedding | 本地 Sentence-Transformers |

> 所有替换只需修改 `config.json` 或在设置页操作，无需改动业务代码。
