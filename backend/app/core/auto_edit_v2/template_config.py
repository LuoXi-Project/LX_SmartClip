from __future__ import annotations

from typing import Dict, List, Literal, Optional, TypedDict

TemplatePresetId = str
ContentStyleId = Literal["generic", "ecommerce", "voiceover", "commentary"]
CONTENT_STYLE_IDS: tuple[str, ...] = ("generic", "ecommerce", "voiceover", "commentary")


def normalize_content_style(style: Optional[str]) -> str:
    s = (style or "generic").strip().lower()
    return s if s in CONTENT_STYLE_IDS else "generic"


class TemplateSlotSpec(TypedDict):
    name: str
    role: Literal["hook", "context", "highlight", "cta"]
    description: str


class TemplateDefSpec(TypedDict):
    label: str
    slots: List[TemplateSlotSpec]
    pace: Literal["slow", "medium", "fast"]
    tone: Literal["calm", "neutral", "energetic"]


# 模板注册表：单一来源（新增模板只需在这里加条目）
TEMPLATES: Dict[TemplatePresetId, TemplateDefSpec] = {
    "ecommerce": {
        "label": "电商转化",
        "pace": "fast",
        "tone": "energetic",
        "slots": [
            {"name": "hook", "role": "hook", "description": "利益/促销/强钩子的一句成品（可带价格或限时），不要写「吸引注意力」等说明"},
            {"name": "problem", "role": "context", "description": "点出痛点或犹豫的一句成品，不要写「指出痛点」或「为什么现在需要」等分析标题"},
            {"name": "solution", "role": "highlight", "description": "核心卖点或功能亮点的一句成品，不要写「给出解决方案」等编导语"},
            {"name": "proof", "role": "highlight", "description": "对比/数据/用户反馈的一句成品，不要写「用证据增强说服」等元句"},
            {"name": "cta", "role": "cta", "description": "下单/领券/戳链接/私信等具体一句；禁止只写「引导行动」类策划概括（可写短口令如「戳下方小黄车」）"},
        ],
    },
    "marketing": {
        "label": "营销号",
        "pace": "fast",
        "tone": "energetic",
        "slots": [
            {"name": "hook", "role": "hook", "description": "开场一句抓眼球的成品句（观点/悬念/反差），不要写「强情绪开场」等说明"},
            {"name": "problem", "role": "context", "description": "点出问题的一句成品句（翻车点/误解），不要写「指出问题」等编导语"},
            {"name": "solution", "role": "highlight", "description": "给出办法的一句成品句（可教一句话技巧），不要写「话术框架」类元描述"},
            {"name": "proof", "role": "highlight", "description": "加强说服的一句成品句（对比/反转/例子），不要写「证据与对照」等标题"},
            {"name": "cta", "role": "cta", "description": "结尾互动/转化的一句成品句（关注、私信、领福利的具体说法），禁止「收束并引导观众」类任务说明"},
        ],
    },
    "tech_review": {
        "label": "科技测评",
        "pace": "medium",
        "tone": "neutral",
        "slots": [
            {"name": "hook", "role": "hook", "description": "结论或典型场景的一句成品（引出评测对象），不要写「信息密度开场」等策划语"},
            {"name": "problem", "role": "context", "description": "真实使用场景或痛点的一句成品，不要写「用户关心什么」等第三人称分析"},
            {"name": "solution", "role": "highlight", "description": "参数/原理/对比维度的一句成品（可含数字），不要写「拆解方案」等标题"},
            {"name": "proof", "role": "highlight", "description": "测试/跑分/对比/体验的一句成品，不要写「验证与证据」等元描述"},
            {"name": "cta", "role": "cta", "description": "是否推荐、适合谁、是否等下一代或关注后续的一句成品，禁止「结论号召」类任务书"},
        ],
    },
    "knowledge": {
        "label": "知识科普",
        "pace": "medium",
        "tone": "neutral",
        "slots": [
            {"name": "hook", "role": "hook", "description": "结论先行/反常识/痛点的一句成品，不要写「强开头」「留在前3秒」等编导指令"},
            {"name": "problem", "role": "context", "description": "背景、常见误区或与观众关系的一句成品，不要写「为什么要听」等元句"},
            {"name": "solution", "role": "highlight", "description": "原理/步骤/关键概念或操作要点的一句成品，不要写「讲清楚核心」等说明"},
            {"name": "proof", "role": "highlight", "description": "案例/数据/小实验/前后对比的一句成品，不要写「加深信服」等标题"},
            {"name": "cta", "role": "cta", "description": "一句话总结或关注/下期/延伸阅读的具体一句，禁止「收尾号召」或罗列任务清单式概括"},
        ],
    },
    "replica_short_video": {
        "label": "复刻·短视频",
        "pace": "fast",
        "tone": "energetic",
        "slots": [
            {"name": "hook", "role": "hook", "description": "开场强钩子成品句"},
            {"name": "context", "role": "context", "description": "背景/场景一句"},
            {"name": "highlight_1", "role": "highlight", "description": "核心亮点一句"},
            {"name": "highlight_2", "role": "highlight", "description": "证据/补充亮点一句"},
            {"name": "cta", "role": "cta", "description": "收口行动一句"},
        ],
    },
    "replica_film_commentary": {
        "label": "复刻·影视解说",
        "pace": "medium",
        "tone": "neutral",
        "slots": [
            {"name": "opening", "role": "hook", "description": "开场设悬念一句"},
            {"name": "background", "role": "context", "description": "背景铺垫一句"},
            {"name": "setup", "role": "context", "description": "人物/事件设定一句"},
            {"name": "conflict", "role": "highlight", "description": "冲突爆发一句"},
            {"name": "turning_point", "role": "highlight", "description": "转折升级一句"},
            {"name": "climax", "role": "highlight", "description": "高潮推进一句"},
            {"name": "reflection", "role": "context", "description": "观点回落一句"},
            {"name": "cta", "role": "cta", "description": "讨论引导/下集悬念一句"},
        ],
    },
    "replica_scene_story": {
        "label": "复刻·场景剧情",
        "pace": "medium",
        "tone": "neutral",
        "slots": [
            {"name": "opening", "role": "hook", "description": "场景引入一句"},
            {"name": "setting", "role": "context", "description": "关系设定一句"},
            {"name": "character", "role": "context", "description": "人物动机一句"},
            {"name": "conflict", "role": "highlight", "description": "矛盾冲突一句"},
            {"name": "progression", "role": "highlight", "description": "情节推进一句"},
            {"name": "resolution", "role": "highlight", "description": "转折或化解一句"},
            {"name": "emotion", "role": "context", "description": "情绪余韵一句"},
            {"name": "cta", "role": "cta", "description": "结尾提问/互动一句"},
        ],
    },
}


def list_templates() -> List[Dict[str, str]]:
    """返回模板列表（供前端渲染按钮/下拉选项）。"""
    # 保持插入顺序以获得稳定 UI
    return [{"id": tid, "label": tdef["label"]} for tid, tdef in TEMPLATES.items()]


def normalize_template_preset(preset: Optional[str]) -> TemplatePresetId | None:
    """校验模板 id；不在注册表内的输入返回 None。"""
    if not preset or not isinstance(preset, str):
        return None
    s = preset.strip()
    # 旧 id 兼容（曾用 piece_production）
    if s == "piece_production":
        s = "knowledge"
    if s == "replica_locked":
        s = "replica_film_commentary"
    if s in TEMPLATES:
        return s
    return None


def get_template_slots(preset: TemplatePresetId) -> List[TemplateSlotSpec]:
    """
    模板槽位（slot）到 Timeline 事件 role 的最小映射：
    - 模板槽位数可以超过后端内置 role 阶段数量，但这里用重复 role 完成 5 槽（MVP）。
    - 事件级 role 由 LLM 生成；编排器再根据 dsl.style.structure 顺序强制选取。
    """
    return TEMPLATES[preset]["slots"]


def get_template_role_sequence(preset: TemplatePresetId) -> List[Literal["hook", "context", "highlight", "cta"]]:
    return [s["role"] for s in get_template_slots(preset)]


def get_template_style_hint(preset: TemplatePresetId) -> Dict[str, object]:
    """
    返回 StrategyStyle 的最小提示（tone/pace/structure）。
    """
    tdef = TEMPLATES[preset]
    return {"pace": tdef["pace"], "tone": tdef["tone"], "structure": get_template_role_sequence(preset)}


def get_long_video_events_profile(content_style: Optional[str]) -> Dict[str, int]:
    """
    auto_edit_v2 长视频分批默认档位（按内容类型）。
    """
    style = normalize_content_style(content_style)
    presets: Dict[str, Dict[str, int]] = {
        "ecommerce": {
            "events_max_clips_per_batch": 28,
            "events_max_chars_per_batch": 20000,
            "events_batch_overlap_clips": 2,
            "events_max_batches": 18,
        },
        "voiceover": {
            "events_max_clips_per_batch": 24,
            "events_max_chars_per_batch": 17000,
            "events_batch_overlap_clips": 3,
            "events_max_batches": 20,
        },
        "commentary": {
            "events_max_clips_per_batch": 20,
            "events_max_chars_per_batch": 15000,
            "events_batch_overlap_clips": 4,
            "events_max_batches": 24,
        },
        "generic": {
            "events_max_clips_per_batch": 25,
            "events_max_chars_per_batch": 18000,
            "events_batch_overlap_clips": 2,
            "events_max_batches": 16,
        },
    }
    return dict(presets.get(style, presets["generic"]))


def get_memory_style_profile(content_style: Optional[str]) -> Dict[str, object]:
    """
    语义快剪（voiceover_semantic）记忆模板档位。
    字段保持通用命名，便于不同业务风格复用。
    """
    style = normalize_content_style(content_style)
    presets: Dict[str, Dict[str, object]] = {
        "generic": {
            "happened_label": "已发生",
            "open_label": "待展开点",
            "state_label": "表达状态",
            "happened_markers": [],
            "open_markers": ["?", "？", "是否", "到底", "后来", "结果", "但是", "却", "突然"],
            "state_markers": ["紧张", "害怕", "愤怒", "伤心", "兴奋", "犹豫", "崩溃", "冷静"],
        },
        "commentary": {
            "happened_label": "剧情进展",
            "open_label": "待回收线索",
            "state_label": "人物状态",
            "happened_markers": ["发现", "进入", "决定", "对抗", "反转"],
            "open_markers": ["真相", "到底", "后来", "为什么", "是否"],
            "state_markers": ["紧张", "害怕", "愤怒", "伤心", "兴奋", "犹豫", "崩溃", "冷静"],
        },
        "ecommerce": {
            "happened_label": "卖点信息",
            "open_label": "待说明疑问",
            "state_label": "购买动机",
            "happened_markers": ["功能", "效果", "材质", "参数", "对比", "优势"],
            "open_markers": ["怎么选", "适合", "区别", "是否", "价格", "活动"],
            "state_markers": ["放心", "省心", "划算", "实用", "省时", "省力"],
        },
        "voiceover": {
            "happened_label": "核心信息",
            "open_label": "待展开点",
            "state_label": "表达状态",
            "happened_markers": ["重点", "总结", "建议", "问题", "方法"],
            "open_markers": ["接下来", "后面", "为什么", "怎么做", "是否"],
            "state_markers": ["强调", "提醒", "对比", "建议", "结论"],
        },
    }
    return dict(presets.get(style, presets["generic"]))

