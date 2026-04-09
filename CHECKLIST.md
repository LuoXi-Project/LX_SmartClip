# 开发检查清单

> 与仓库代码同步；细粒度任务以 `memory-bank/progress.md` 为准。

## ✅ Phase 0–7（基础管线）

- [x] 后端环境搭建
- [x] 前端环境搭建
- [x] 前后端联通
- [x] 数据库设计与迁移（`videos` / `clips` / `config` / `replica_templates` / `process_tasks`）
- [x] 配置管理（含模型列表代理 `POST /api/config/models`）
- [x] 视频上传 / 列表 / 删除 / 元数据补丁 / URL 导入 / 可选重编码
- [x] 素材库页面（含检索入口、分页等）
- [x] FFmpeg 音频提取
- [x] 视频切分（镜头 / 固定时长 / 混合等，见配置）
- [x] 自动抽帧
- [x] ASR（Whisper / OpenAI 协议）
- [x] VLM（OpenAI 兼容视觉）
- [x] 向量化与入库（FAISS + `embedder`）
- [x] 全素材处理整合（HTTP + WebSocket；`process_tasks` 任务态 + `/api/process-jobs`）
- [x] 前端素材处理页 `/process`（实时进度）
- [x] 全局导航栏与布局组件（含卡密门闸、全局 AI 对话面板）

## ✅ Phase 8–11（匹配、配音、导出、设置）

- [x] RAG 初筛 + LLM 精排（`matcher` / `rag`）
- [x] `POST /api/match`
- [x] 前端智能剪辑工作台 `/match`（手动匹配、自动成片、字幕工作区、导出侧栏等）
- [x] TTS 抽象层与多提供商（edge-tts、OpenAI 系、百炼、火山、GSV、IndexTTS、自定义 HTTP 等）
- [x] TTS API：`POST /api/tts/synthesize`、`GET /api/tts/voices`、`GET /api/tts/audio/{filename}`
- [x] 前端 `/tts`
- [x] 工程导出 `POST /api/export/project`（ZIP：片段 + TTS 音频 + `project.json`）
- [x] 系统设置 `/settings`（分组表单项、模型拉取等）

## ✅ Phase 12 之外已落地的扩展能力

- [x] 语义检索与高光浏览：`POST /api/search/*`（见 `search.py`）
- [x] 对话补全：`POST /api/chat/completions`
- [x] 文案生成：`POST /api/copy-gen/generate`
- [x] 字幕时间线与烧录：`/api/subtitle/*`
- [x] 自动剪辑 v2：`/api/auto-edit/*`（计划、流式会话、实现导出等）
- [x] BGM 曲库：`/api/bgm/*`
- [x] 复刻模板（Replica）：`/api/replica/*`
- [x] 卡密与授权中间件：`/api/license/*`、`LicenseMiddleware`
- [x] 运行日志查询：`GET /api/logs`
- [x] 前端页面：`/search`、`/bgm`、`/license`、`/logs`、`/about`
- [x] 发布态：可挂载 `backend/app/static/frontend`（Next 静态导出）+ SPA 404 兜底

## ⏳ Phase 12（收尾与质量）

- [ ] 端到端自动化测试（核心链路回归）
- [ ] 错误边界与容错策略统一（用户可感知错误、重试、部分失败恢复）

## 📊 项目进度（概览）

| 项 | 约数（2026-04） |
|----|-----------------|
| 后端 `backend/app` 下 Python 文件 | 115 |
| 前端 `frontend/app` 下 TS/TSX | 约 70+ |
| `app/api` 路由装饰器（HTTP + WS） | 约 60+ |
| 原始计划 Phase 0–11 | 已完成 |
| 扩展功能 | 已并入主线产品 |

**完成度（按原始 12 Phase）：** 11/12 核心阶段完成 + 多项扩展已上线；剩余主要为测试与健壮性。

---

**最后更新：** 2026-04-09
