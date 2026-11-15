"""动效渲染模块（HyperFrames 集成）：HTML 合成 → 确定性 MP4。

- runtime.py：Node / node_modules / Chromium / FFmpeg 运行时解析与就绪态
- bridge/render.mjs：Node 渲染桥（@hyperframes/producer 程序化 API）
- renderer.py：渲染编排（组合落盘 → node 子进程 → job 进度 → renders 入库）
- caption_render.py（阶段 3）：SRT → kinetic captions
"""
