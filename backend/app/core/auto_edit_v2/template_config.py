from __future__ import annotations

from typing import Dict, List, Literal, Optional, TypedDict

TemplatePresetId = Literal["ecommerce", "marketing", "tech_review"]


class TemplateSlotSpec(TypedDict):
    name: str
    role: Literal["hook", "context", "highlight", "cta"]
    description: str


def normalize_template_preset(preset: Optional[str]) -> TemplatePresetId | None:
    if not preset or not isinstance(preset, str):
        return None
    s = preset.strip()
    if s in ("ecommerce", "marketing", "tech_review"):
        return s  # type: ignore[return-value]
    return None


def get_template_slots(preset: TemplatePresetId) -> List[TemplateSlotSpec]:
    """
    模板槽位（slot）到 Timeline 事件 role 的最小映射：
    - 模板槽位数可以超过后端内置 role 阶段数量，但这里用重复 role 完成 5 槽（MVP）。
    - 事件级 role 由 LLM 生成；编排器再根据 dsl.style.structure 顺序强制选取。
    """
    if preset == "ecommerce":
        return [
            {"name": "hook", "role": "hook", "description": "吸引注意力：强调利益点/促销/强开头"},
            {"name": "problem", "role": "context", "description": "指出痛点/犹豫点：为什么现在需要它"},
            {"name": "solution", "role": "highlight", "description": "给出解决方案：核心卖点/功能亮点"},
            {"name": "proof", "role": "highlight", "description": "用证据增强说服：对比/数据/用户反馈"},
            {"name": "cta", "role": "cta", "description": "引导行动：立即购买/关注链接/下一步"},
        ]

    if preset == "marketing":
        return [
            {"name": "hook", "role": "hook", "description": "强情绪开场：抛观点/制造悬念/反差"},
            {"name": "problem", "role": "context", "description": "指出问题：为什么会翻车/误解在哪里"},
            {"name": "solution", "role": "highlight", "description": "解决方案：给出方法/话术框架/替代策略"},
            {"name": "proof", "role": "highlight", "description": "证据与对照：前后效果/示例片段/反转"},
            {"name": "cta", "role": "cta", "description": "收束并引导：关注/收藏/评论互动"},
        ]

    # tech_review
    return [
        {"name": "hook", "role": "hook", "description": "信息密度开场：用结论/场景引出评测"},
        {"name": "problem", "role": "context", "description": "痛点与使用场景：用户关心什么/遇到什么"},
        {"name": "solution", "role": "highlight", "description": "拆解方案：关键参数/工作原理/对比维度"},
        {"name": "proof", "role": "highlight", "description": "验证与证据：测试结果/对比结论/体验总结"},
        {"name": "cta", "role": "cta", "description": "结论号召：建议入手/等待/关注后续"},
    ]


def get_template_role_sequence(preset: TemplatePresetId) -> List[Literal["hook", "context", "highlight", "cta"]]:
    return [s["role"] for s in get_template_slots(preset)]


def get_template_style_hint(preset: TemplatePresetId) -> Dict[str, object]:
    """
    返回 StrategyStyle 的最小提示（tone/pace/structure）。
    """
    if preset == "ecommerce":
        return {"pace": "fast", "tone": "energetic", "structure": get_template_role_sequence(preset)}
    if preset == "marketing":
        return {"pace": "fast", "tone": "energetic", "structure": get_template_role_sequence(preset)}
    # tech_review
    return {"pace": "medium", "tone": "neutral", "structure": get_template_role_sequence(preset)}

