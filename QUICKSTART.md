# 快速启动指南

## 项目概览

LX SmartClip 是一个本地轻量化 AI 智能素材匹配剪辑工具。

**核心功能：**
- 批量素材入库
- 多模式切分（镜头识别 / 固定时长）
- 多模态理解（ASR + VLM）
- 三级精准匹配（RAG 初筛 → LLM 精排 → 人工选择）
- TTS 配音
- 工程文件导出

---

## 环境要求

- Python >= 3.10
- Node.js >= 18
- FFmpeg（系统已安装）
- Git

---

## 后端启动

### 1. 创建虚拟环境

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 启动服务

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**验证：** 访问 `http://localhost:8000/health`，应返回 `{"status": "ok"}`

---

## 前端启动

### 1. 安装依赖

```bash
cd frontend
npm install
```

### 2. 启动开发服务器

```bash
npm run dev
```

**验证：** 访问 `http://localhost:3000`，应看到首页

---

## 功能验证

### 1. 后端健康检查

```bash
curl http://localhost:8000/health
# 期望返回：{"status": "ok"}
```

### 2. 获取配置

```bash
curl http://localhost:8000/api/config
# 期望返回：包含所有配置项的 JSON
```

### 3. 上传视频

```bash
curl -X POST http://localhost:8000/api/videos/upload \
  -F "file=@test.mp4"
# 期望返回：{"id": "xxx", "name": "test.mp4", "upload_at": "..."}
```

### 4. 获取视频列表

```bash
curl http://localhost:8000/api/videos
# 期望返回：视频列表数组
```

---

## 前端页面

### 首页 (`/`)
- 系统状态显示
- 功能特性介绍
- 开始使用按钮

### 素材库 (`/library`)
- 视频上传（拖拽 / 点击）
- 视频卡片列表
- 删除功能
- 状态显示

---

## 项目结构

```
LX_SmartClip/
├── backend/
│   ├── app/
│   │   ├── api/              # 路由层
│   │   │   ├── config.py     # 配置接口
│   │   │   └── videos.py     # 视频接口
│   │   ├── core/             # 业务逻辑层（待实现）
│   │   ├── db/               # 数据库层
│   │   │   ├── database.py   # 连接管理
│   │   │   └── init_db.py    # 建表初始化
│   │   └── main.py           # 应用入口
│   ├── data/                 # SQLite 数据库（运行时生成）
│   ├── storage/              # 视频/音频/帧存储（运行时生成）
│   └── requirements.txt      # Python 依赖
│
├── frontend/
│   ├── app/
│   │   ├── page.tsx          # 首页
│   │   ├── library/
│   │   │   └── page.tsx      # 素材库页面
│   │   ├── layout.tsx        # 根布局
│   │   └── globals.css       # 全局样式
│   ├── lib/
│   │   ├── api.ts            # API 客户端
│   │   └── store.ts          # 状态管理
│   ├── package.json
│   └── tsconfig.json
│
└── memory-bank/              # 项目文档
    ├── design-document.md    # 产品设计文档
    ├── architecture.md       # 架构说明
    ├── implementation-plan.md # 实施计划
    └── tech-stack.md         # 技术栈说明
```

---

## 常见问题

### Q: 后端无法启动？
A: 确保 Python >= 3.10，虚拟环境已激活，依赖已安装。

### Q: 前端无法连接后端？
A: 检查后端是否运行在 `http://localhost:8000`，CORS 配置是否正确。

### Q: 上传视频失败？
A: 检查文件格式是否支持（mp4, mov, avi, mkv, webm, mpeg），文件大小是否合理。

### Q: 数据库文件在哪里？
A: 在 `backend/data/smartclip.db`

### Q: 上传的视频存储在哪里？
A: 在 `backend/storage/videos/` 目录

---

## 下一步开发

详见 `memory-bank/implementation-plan.md`

当前优先级：
1. Phase 3：视频切分（FFmpeg + PySceneDetect）
2. Phase 4-5：ASR + VLM 处理
3. Phase 6-8：向量化 + 三级匹配
4. Phase 9-12：TTS、导出、设置、测试

---

## 技术支持

遇到问题？检查以下文件：
- 架构说明：`memory-bank/architecture.md`
- 设计文档：`memory-bank/design-document.md`
- 实施计划：`memory-bank/implementation-plan.md`
