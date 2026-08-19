"""内置工作流：代码即默认值，启动时同步进 workflows 表（is_builtin=1）。

新增内置工作流 = 在 BUILTIN_WORKFLOWS 追加一段 WorkflowDef，无需改动引擎。
"""

from __future__ import annotations

from .schema import ParamSpec, WorkflowDef, WorkflowStep

_collect_to_render = WorkflowDef(
    id="collect_to_render",
    name="采集 → 处理 → 成片一条龙",
    description=(
        "输入一段成片文案：AI 提取关键词到抖音/YouTube 采集素材 → 自动预处理"
        "（切分/ASR/VLM/向量化）→ 文案逐段切分并语义匹配素材 → 按原文案逐段配音"
        "（TTS）+ 字幕烧录成片。成片口播与文案逐字一致，不重写、不丢段。"
    ),
    category="内容生产",
    is_builtin=True,
    params=[
        ParamSpec(
            name="copy_text", label="成片文案", type="textarea", required=True,
            placeholder="粘贴完整成片文案。成片口播将与文案逐字一致（仅自动切分与匹配画面）…",
            help="文案会同时用于提取采集关键词；成片时长≈文案配音时长",
        ),
        ParamSpec(
            name="platforms", label="采集平台", type="multiselect",
            default=["douyin"],
            options=[
                {"value": "douyin", "label": "抖音"},
                {"value": "youtube", "label": "YouTube（需配置代理）"},
            ],
            help="YouTube 需在设置中配置 external_search_proxy",
        ),
        ParamSpec(
            name="limit_per_keyword", label="每关键词采集条数", type="number",
            default=3, help="每个关键词下载的素材数量（1~10 为宜）",
        ),
        ParamSpec(
            name="tts_voice", label="配音音色", type="text",
            default=None, placeholder="留空使用 TTS 设置中的默认音色",
            help="如 zh-CN-XiaoxiaoNeural；非 edge 引擎时语速/音量跟随 TTS 设置",
        ),
        ParamSpec(
            name="include_subtitle", label="烧录字幕", type="switch", default=True,
            help="关闭则导出无字幕成片",
        ),
    ],
    steps=[
        WorkflowStep(
            name="ingest", title="素材采集", action="external_ingest",
            params={
                "copy_text": "${inputs.copy_text}",
                "platforms": "${inputs.platforms}",
                "limit_per_keyword": "${inputs.limit_per_keyword}",
            },
            retries=1,
        ),
        WorkflowStep(
            name="wait_process", title="素材预处理", action="wait_process",
            params={"video_ids": "${steps.ingest.video_ids}", "allow_partial": True},
            timeout_sec=6 * 3600,   # 预处理为串行队列，素材多时耗时长
        ),
        WorkflowStep(
            name="match", title="文案分段匹配", action="match_copy_segments",
            params={
                "copy_text": "${inputs.copy_text}",
                "video_ids": "${steps.wait_process.video_ids}",
            },
        ),
        WorkflowStep(
            name="render", title="按文案配音成片", action="render_copy_segments",
            params={
                "segments": "${steps.match.segments}",
                "voice": "${inputs.tts_voice}",
                "include_subtitle": "${inputs.include_subtitle}",
            },
            timeout_sec=3600,
        ),
    ],
)

BUILTIN_WORKFLOWS: list[WorkflowDef] = [
    _collect_to_render,
]
