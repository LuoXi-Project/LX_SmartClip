# 开发检查清单

## ✅ Phase 0-7 完成

- [x] 后端环境搭建
- [x] 前端环境搭建
- [x] 前后端联通
- [x] 数据库设计
- [x] 配置管理
- [x] 视频上传/列表/删除
- [x] 素材库页面
- [x] FFmpeg 音频提取
- [x] 视频切分（双模式：镜头识别 + 固定时长）
- [x] 自动抽帧
- [x] ASR 语音识别（Whisper）
- [x] VLM 视觉描述（OpenAI Vision）
- [x] 向量化与入库（SQLite-VSS）
- [x] 全处理管线整合（HTTP + WebSocket）
- [x] 前端处理管线页面（实时进度）
- [x] 全局导航栏

## ✅ Phase 8 完成

- [x] RAG 初筛（Embedding + SQLiteVSS）
- [x] LLM 精排
- [x] 匹配接口 POST /api/match
- [x] 前端文案匹配页面

## ✅ Phase 9 完成

- [x] TTS 抽象层 backend/app/core/tts/base.py
- [x] edge-tts 实现 backend/app/core/tts/edge_tts_impl.py
- [x] TTS API（POST /api/tts/synthesize, GET /api/tts/voices, GET /api/tts/audio/{filename}）
- [x] 前端 TTS 配音页面 frontend/app/tts/page.tsx
- [x] 顶部导航新增 TTS 配音入口
- [x] 默认配置 tts_voice / tts_rate / tts_volume

## ⏳ Phase 10-12 待开始

- [ ] 工程文件导出（ZIP）
- [ ] 系统设置页面
- [ ] 端到端集成测试

## 📊 项目进度

**完成：** 10/12 Phase (83%)

**后端文件数：** 27 个

**前端文件数：** 11 个

**已实现接口：** 19 个

---

**最后更新：** 2026-03-23
