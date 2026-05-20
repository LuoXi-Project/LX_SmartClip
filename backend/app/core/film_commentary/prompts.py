from __future__ import annotations

STYLE_HINTS = {
    "suspense": "悬疑反转、强钩子、短句留白，适合电影解说爆款节奏",
    "humor": "吐槽幽默、网感口语、适度夸张但不偏离剧情",
    "deep": "深度解析、人物动机与主题升华，节奏中等",
    "fast": "极快节奏、信息密度高、每句 8～18 字为主",
}


def summarize_system_prompt(*, mode: str) -> str:
    extra = ""
    if mode == "lightweight":
        extra = "无画面描述时，可结合你对该影视作品的通识知识补全场景与人物行为，但不得编造与台词明显矛盾的情节。"
    return (
        "你是专业影视剧情分析师。根据每个视频切片的台词与画面信息，"
        "输出极简结构化摘要（50～80 字），只保留剧情逻辑，不写时间码。\n"
        f"{extra}\n"
        "严格输出 JSON 数组，每项字段：clip_id, summary, role, mood。\n"
        "role 取：铺垫/冲突/过渡/高潮/结局 之一；mood 为整体氛围一词。"
    )


def summarize_user_prompt(clips_payload: str) -> str:
    return f"请为以下切片生成摘要：\n{clips_payload}"


def screenplay_system_prompt(*, style: str, target_duration_sec: int) -> str:
    hint = STYLE_HINTS.get(style, STYLE_HINTS["suspense"])
    est_sentences = max(12, min(80, target_duration_sec // 5))
    return (
        "你是自媒体影视解说编剧。根据全片剧情摘要，先构建六段式故事线，再写分句解说文案。\n"
        f"风格要求：{hint}\n"
        f"目标成片约 {target_duration_sec} 秒，解说分句约 {est_sentences} 句（可上下浮动 20%）。\n"
        "硬性规则：\n"
        "1) 分句文案不得包含任何时间戳或「第X分钟」；\n"
        "2) 每句独立成段，口语化、适合配音；\n"
        "3) 严格 JSON 输出，结构见用户消息。"
    )


def screenplay_user_prompt(*, summaries_text: str, video_name: str) -> str:
    return (
        f"片名/素材名：{video_name or '未知'}\n\n"
        "【剧情摘要（按时间顺序）】\n"
        f"{summaries_text}\n\n"
        "请输出 JSON：\n"
        "{\n"
        '  "storyline": {\n'
        '    "hook": "开篇钩子",\n'
        '    "setup": "人物铺垫",\n'
        '    "conflict": "冲突触发",\n'
        '    "escalation": "剧情升级",\n'
        '    "climax": "高潮反转",\n'
        '    "ending": "结局点评"\n'
        "  },\n"
        '  "sentences": [\n'
        '    {"index": 1, "text": "...", "tag": "hook|setup|..."}\n'
        "  ]\n"
        "}"
    )
