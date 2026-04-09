# 快速启动指南

## 项目概览

LX SmartClip（洛曦智剪）是本地轻量化 **AI 智能素材剪辑** 工具：入库、多模式切分、ASR + VLM、向量检索与 LLM 精排、TTS、字幕与自动剪辑辅助、工程导出等。前后端可分开开发；也可将前端静态导出放到 `backend/app/static/frontend` 由同一进程托管（见 `backend/app/main.py`）。

**核心能力（已实现）：**

- 素材：上传 / URL 导入 / 管理 / 检索 / 处理流水线  
- 匹配：`/api/match` + 工作台 `/match`（含自动成片、字幕、导出等模块）  
- 生成：TTS、文案生成、对话、字幕烧录、自动剪辑计划与实现、BGM、复刻模板  
- 系统：设置页、日志、可选卡密授权  

**环境要求**

- Python >= 3.10  
- Node.js >= 18  
- FFmpeg（已在 PATH 中）  
- Git  

---

## 后端启动

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

**验证：** 打开 `http://127.0.0.1:8000/health`，应返回 `{"status":"ok"}`。

---

## 前端启动

```bash
cd frontend
npm install
npm run dev
```

**验证：** 打开 `http://localhost:3000`。

前端默认通过 `lib/runtime-config.ts` / 环境变量指向后端 API；开发时一般为 `http://127.0.0.1:8000`。

---

## 功能验证（curl 示例）

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/config
curl -X POST http://127.0.0.1:8000/api/videos/upload -F "file=@test.mp4"
curl http://127.0.0.1:8000/api/videos
```

完整接口列表见 `memory-bank/progress.md`。

---

## 前端路由一览

| 路径 | 说明 |
|------|------|
| `/` | 首页 |
| `/library` | 素材库 |
| `/process` | 素材处理与进度 |
| `/search` | 素材检索 |
| `/match` | 智能剪辑 |
| `/tts` | TTS 配音 |
| `/bgm` | BGM 音乐库 |
| `/settings` | 系统设置 |
| `/logs` | 运行日志 |
| `/license` | 卡密 / 授权 |
| `/about` | 关于与支持 |

---

## 仓库目录（精简）

```
LX_SmartClip/
├── backend/
│   ├── app/
│   │   ├── main.py           # 入口：路由、CORS、静态资源、SPA 兜底
│   │   ├── api/              # HTTP/WS 路由（videos、clips、process、match、…）
│   │   ├── core/             # 业务与 AI 实现
│   │   ├── db/               # SQLite 连接与 init/migrate
│   │   ├── middleware/       # 授权等
│   │   └── static/frontend/  # 可选：Next 静态导出产物（发布）
│   ├── data/                 # smartclip.db（默认不提交）
│   └── storage/              # 视频、音频、帧等产物（默认不提交）
├── frontend/
│   ├── app/                  # 页面与组件
│   └── lib/                  # api、store、runtime-config
├── memory-bank/              # 设计、架构、进度、实施计划
├── docs/                     # 专题文档与策略说明
├── CHECKLIST.md
├── PROJECT_SUMMARY.md
└── QUICKSTART.md
```

---

## 常见问题

**Q: 后端无法启动？**  
A: 确认 Python 版本、虚拟环境已激活、`pip install -r requirements.txt` 成功；若端口占用可换端口启动 uvicorn。

**Q: 前端连不上 API？**  
A: 确认后端已监听 `127.0.0.1:8000`；检查前端 `.env.local` 或 `NEXT_PUBLIC_*` 与 `lib/runtime-config.ts`。

**Q: 上传失败？**  
A: 确认格式在支持列表内（如 mp4 / mov / avi / mkv / webm / mpeg 等，以 `videos` 路由校验为准），磁盘与 `backend/storage` 可写。

**Q: 数据库与文件在哪？**  
A: 数据库 `backend/data/smartclip.db`；上传与中间产物多在 `backend/storage/`。

**Q: CORS 报错？**  
A: 当前后端对开发较宽松（见 `main.py` 中 `CORSMiddleware`）。若仍有问题，核对浏览器访问的前端源与 API 地址是否一致。

**Q: 卡密 / LICENSE_REQUIRED？**  
A: 部分接口受 `LicenseMiddleware` 约束，需在 `/license` 页或 `/api/license` 完成激活（具体策略见 `backend/app/core/license.py`）。

---

## 下一步（开发维护）

- 阶段清单：[CHECKLIST.md](./CHECKLIST.md)  
- 接口与进度：[memory-bank/progress.md](./memory-bank/progress.md)  
- AI/人类共读维护手册：[docs/AI_DEV_GUIDE.md](./docs/AI_DEV_GUIDE.md)  

---

**最后更新：** 2026-04-09
