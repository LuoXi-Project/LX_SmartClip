from __future__ import annotations

from typing import Dict, List, Literal, Optional, TypedDict

TemplatePresetId = str


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
            {"name": "hook", "role": "hook", "description": "吸引注意力：强调利益点/促销/强开头"},
            {"name": "problem", "role": "context", "description": "指出痛点/犹豫点：为什么现在需要它"},
            {"name": "solution", "role": "highlight", "description": "给出解决方案：核心卖点/功能亮点"},
            {"name": "proof", "role": "highlight", "description": "用证据增强说服：对比/数据/用户反馈"},
            {"name": "cta", "role": "cta", "description": "引导行动：立即购买/关注链接/下一步"},
        ],
    },
    "marketing": {
        "label": "营销号",
        "pace": "fast",
        "tone": "energetic",
        "slots": [
            {"name": "hook", "role": "hook", "description": "强情绪开场：抛观点/制造悬念/反差"},
            {"name": "problem", "role": "context", "description": "指出问题：为什么会翻车/误解在哪里"},
            {"name": "solution", "role": "highlight", "description": "解决方案：给出方法/话术框架/替代策略"},
            {"name": "proof", "role": "highlight", "description": "证据与对照：前后效果/示例片段/反转"},
            {"name": "cta", "role": "cta", "description": "收束并引导：关注/收藏/评论互动"},
        ],
    },
    "tech_review": {
        "label": "科技测评",
        "pace": "medium",
        "tone": "neutral",
        "slots": [
            {"name": "hook", "role": "hook", "description": "信息密度开场：用结论/场景引出评测"},
            {"name": "problem", "role": "context", "description": "痛点与使用场景：用户关心什么/遇到什么"},
            {"name": "solution", "role": "highlight", "description": "拆解方案：关键参数/工作原理/对比维度"},
            {"name": "proof", "role": "highlight", "description": "验证与证据：测试结果/对比结论/体验总结"},
            {"name": "cta", "role": "cta", "description": "结论号召：建议入手/等待/关注后续"},
        ],
    },
    "knowledge": {
        "label": "知识科普",
        "pace": "medium",
        "tone": "neutral",
        "slots": [
            {"name": "hook", "role": "hook", "description": "强开头：结论先行/反常识/痛点，把观众留在前 3 秒"},
            {"name": "problem", "role": "context", "description": "为什么要听：背景、常见误区、这件事和观众的关系"},
            {"name": "solution", "role": "highlight", "description": "讲清楚核心：原理、步骤、关键概念或操作要点"},
            {"name": "proof", "role": "highlight", "description": "加深信服：案例、数据、小实验、前后对比或示意图"},
            {"name": "cta", "role": "cta", "description": "收尾号召：一句话总结、关注收藏、下期预告或延伸阅读"},
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

