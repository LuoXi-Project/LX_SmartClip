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

# ── 库内素材混剪出片（AI 自动剪辑）────────────────────────────────────────

_library_mix_edit = WorkflowDef(
    id="library_mix_edit",
    name="库内素材混剪出片",
    description=(
        "从素材库选视频：自动完成预处理 → AI 生成混剪方案（结构 / 节奏 / 画面由 LLM 把控）"
        " → TTS 配音、字幕烧录成片。默认关闭原声由 AI 生成旁白；也可保留原声快剪。"
    ),
    category="智能成片",
    is_builtin=True,
    params=[
        ParamSpec(
            name="video_ids", label="素材范围", type="video_ids", required=True,
            help="选择素材库中参与剪辑的视频；未预处理的会自动排队处理",
        ),
        ParamSpec(
            name="user_prompt", label="剪辑诉求 / 旁白文案", type="textarea", required=True,
            placeholder="例：节奏快、情绪燃的 60 秒带货混剪；也可直接粘贴旁白文案",
            help="默认由 AI 据此生成旁白并配音；「保留原声」模式下作为剪辑风格指引",
        ),
        ParamSpec(
            name="mix_audio_mode", label="音频模式", type="select", default="mute_all_original",
            options=[
                {"value": "mute_all_original", "label": "关闭原声（AI 旁白 / 仅 BGM）"},
                {"value": "keep_original", "label": "保留原声"},
            ],
            help="关闭原声时下方「配音音轨」生效",
        ),
        ParamSpec(
            name="mute_audio_track", label="配音音轨", type="select", default="ai_tts_llm",
            options=[
                {"value": "ai_tts_llm", "label": "AI 生成旁白 + TTS"},
                {"value": "ai_tts_asr", "label": "原话 TTS（按素材原声文本配音）"},
                {"value": "bgm_only", "label": "仅 BGM"},
            ],
            help="仅「关闭原声」模式生效",
        ),
        ParamSpec(
            name="target_duration_sec", label="目标成片时长（秒）", type="number",
            placeholder="留空由 AI 决定",
            help="成片超长时自动裁剪",
        ),
        ParamSpec(
            name="include_subtitle", label="烧录字幕", type="switch", default=True,
            help="关闭则导出无字幕成片",
        ),
    ],
    steps=[
        WorkflowStep(
            name="wait_process", title="素材预处理", action="wait_process",
            params={"video_ids": "${inputs.video_ids}", "allow_partial": True},
            timeout_sec=6 * 3600,
        ),
        WorkflowStep(
            name="plan", title="AI 混剪方案", action="mix_edit_plan",
            params={
                "video_ids": "${steps.wait_process.video_ids}",
                "user_prompt": "${inputs.user_prompt}",
                "mix_audio_mode": "${inputs.mix_audio_mode}",
                "mute_audio_track": "${inputs.mute_audio_track}",
                "target_duration_sec": "${inputs.target_duration_sec}",
            },
        ),
        WorkflowStep(
            name="render", title="渲染成片", action="realize_plan",
            params={
                "plan": "${steps.plan.plan}",
                "include_subtitle": "${inputs.include_subtitle}",
                "force_tts_pipeline": True,
            },
            when="${inputs.mix_audio_mode} == 'mute_all_original'",
            timeout_sec=3600,
        ),
        WorkflowStep(
            name="render_keep_audio", title="渲染成片（保留原声）", action="realize_plan",
            params={
                "plan": "${steps.plan.plan}",
                "include_subtitle": "${inputs.include_subtitle}",
            },
            when="${inputs.mix_audio_mode} == 'keep_original'",
            timeout_sec=3600,
        ),
    ],
)

# ── 文案成片 · 库内素材（不出库采集）───────────────────────────────────────

_library_copy_render = WorkflowDef(
    id="library_copy_render",
    name="文案成片 · 库内素材",
    description=(
        "输入成片文案，从素材库选视频：自动预处理 → 文案逐段切分并语义匹配画面 → "
        "按原文案逐段 TTS 配音 + 字幕烧录成片。成片口播与文案逐字一致，不重写、不丢段。"
        "与「采集→处理→成片一条龙」的区别：不出库采集，直接用你库里的素材。"
    ),
    category="内容生产",
    is_builtin=True,
    params=[
        ParamSpec(
            name="copy_text", label="成片文案", type="textarea", required=True,
            placeholder="粘贴完整成片文案。成片口播将与文案逐字一致（仅自动切分与匹配画面）…",
            help="支持空行分段；无空行时按句读自动切分",
        ),
        ParamSpec(
            name="video_ids", label="素材范围", type="video_ids", required=True,
            help="选择素材库中参与匹配的视频；未预处理的会自动排队处理",
        ),
        ParamSpec(
            name="tts_voice", label="配音音色", type="text",
            default=None, placeholder="留空使用 TTS 设置中的默认音色",
            help="如 zh-CN-XiaoxiaoNeural",
        ),
        ParamSpec(
            name="include_subtitle", label="烧录字幕", type="switch", default=True,
            help="关闭则导出无字幕成片",
        ),
    ],
    steps=[
        WorkflowStep(
            name="wait_process", title="素材预处理", action="wait_process",
            params={"video_ids": "${inputs.video_ids}", "allow_partial": True},
            timeout_sec=6 * 3600,
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

# ── 素材批量采集入库（只囤弹药，不剪）─────────────────────────────────────

_batch_ingest = WorkflowDef(
    id="batch_ingest",
    name="素材批量采集入库",
    description=(
        "按关键词批量从抖音 / YouTube 搜索下载素材入库，可选直接完成切分 / ASR / VLM / "
        "向量化全量预处理，为后续混剪与文案成片备好弹药。"
    ),
    category="素材采集",
    is_builtin=True,
    params=[
        ParamSpec(
            name="keywords", label="搜索关键词", type="text", required=True,
            placeholder="多个关键词用逗号分隔，如：健身餐,减脂食谱",
            help="每个关键词独立搜索下载",
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
            default=5, help="1~10 为宜",
        ),
        ParamSpec(
            name="resolution", label="下载清晰度", type="select", default="720p",
            options=[
                {"value": "best", "label": "最高"},
                {"value": "1080p", "label": "1080p"},
                {"value": "720p", "label": "720p"},
                {"value": "480p", "label": "480p"},
            ],
        ),
        ParamSpec(
            name="auto_process", label="下载后自动预处理", type="switch", default=True,
            help="开启则入库后直接排队切分 / ASR / VLM / 向量化",
        ),
    ],
    steps=[
        WorkflowStep(
            name="ingest", title="素材采集", action="external_ingest",
            params={
                "keywords": "${inputs.keywords}",
                "platforms": "${inputs.platforms}",
                "limit_per_keyword": "${inputs.limit_per_keyword}",
                "resolution": "${inputs.resolution}",
            },
            retries=1,
        ),
        WorkflowStep(
            name="wait_process", title="素材预处理", action="wait_process",
            params={"video_ids": "${steps.ingest.video_ids}", "allow_partial": True},
            when="${inputs.auto_process}",
            timeout_sec=6 * 3600,
        ),
    ],
)

BUILTIN_WORKFLOWS: list[WorkflowDef] = [
    _collect_to_render,
    _library_mix_edit,
    _library_copy_render,
    _batch_ingest,
]
