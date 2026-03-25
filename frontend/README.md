# LX SmartClip - AI 智能剪辑工具

本地轻量化 AI 智能素材匹配剪辑工具，支持批量素材入库、多模式切分、多模态理解、三级精准匹配、TTS 配音、导出工程文件。

## 项目结构

```
LX_SmartClip/
├── backend/          # Python FastAPI 后端
├── frontend/         # Next.js 14 前端
└── memory-bank/      # 项目文档
```

## 快速开始

### 后端启动

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

后端将在 `http://localhost:8000` 启动

### 前端启动

```bash
cd frontend
npm install
npm run dev
```

前端将在 `http://localhost:3000` 启动

## 功能特性

- 📹 **素材库管理** - 上传、预览、删除视频
- ✂️ **智能切分** - 镜头识别 / 固定时长双模式
- 🧠 **多模态理解** - ASR 语音识别 + VLM 视觉描述
- 🎯 **三级匹配** - RAG 初筛 → LLM 精排 → 人工选择
- 🎙️ **TTS 配音** - 自动生成高质量配音
- 📦 **工程导出** - 导出剪辑工程文件

## 技术栈

### 后端
- FastAPI
- SQLite + FAISS（向量存储）
- FFmpeg + PySceneDetect（视频处理）
- Whisper（ASR）
- OpenAI API（VLM + LLM）
- edge-tts（TTS）

### 前端
- Next.js 14
- React 18
- TypeScript
- TailwindCSS
- Zustand（状态管理）
- Axios（HTTP 客户端）

## 开发进度

详见 `memory-bank/implementation-plan.md`

## 许可证

MIT
