from __future__ import annotations

from app.core.auto_edit_v2.template_config import get_template_slots, normalize_template_preset

_EVENTS_SYS_PROMPT = """你是一位视频素材事件提名器（event nominator）。
你将收到若干条素材片段的文本信息（包含 clip_id、ASR/VLM 摘要等）。
你的任务是：为每个 clip 提名若干“可用于剪辑编排”的事件 ClipEvent，并给出 role/beat 和局部分数。

硬性要求（必须遵守）：
- 只输出 JSON，不要解释文字，不要 Markdown。
- 输出必须是 ClipEventsBatch 结构：{"batch_id":"...","events":[...]}
- events[*].clip_id 必须从输入中出现的 clip_id 原样拷贝，禁止编造。
- 分数范围 0~1。
- 每个 clip 事件数不要过多（建议 0~6）。
"""

_EVENTS_SCHEMA_HINT = """
输出 JSON 结构示例：
{
  "batch_id": "b_001",
  "events": [
    {
      "event_id": "e1",
      "clip_id": "CLIP_123",
      "time_range": {"start_sec": 3.2, "end_sec": 6.8},
      "text": "一句话概括该事件（可用于字幕/旁白）",
      "source": "asr|vlm|asr+vlm|llm|user",
      "role": "hook|context|highlight|cta|broll|transition",
      "beat": "setup|turn|payoff|montage|explain|demo",
      "scores": {"local_score": 0.86, "relevance": 0.9, "clarity": 0.8, "emotion": 0.3},
      "tags": ["关键词1","关键词2"],
      "evidence": "可选：引用输入中的原句"
    }
  ]
}
"""


def _build_template_sys_append(template_preset: str | None) -> str:
    preset = normalize_template_preset(template_preset)
    if not preset:
        return ""

    slots = get_template_slots(preset)
    # 仅让 LLM 用最贴近“slot->role”的输出；编排器会按 dsl.style.structure 顺序强制挑选。
    lines = []
    for s in slots:
        lines.append(f"- slot={s['name']} -> role={s['role']}：{s['description']}")

    joined = "\n".join(lines)
    return (
        "\n\n模板槽位要求（用于 role 归类；必须遵守）：\n"
        f"{joined}\n"
        "\n硬性要求：\n"
        "- events[*].role 只允许从上述 slot 对应的 role 中选择（不要输出其他 role）。\n"
        "- beat 可以辅助表达“setup/turn/payoff”等节拍，但 role 才是强约束。\n"
    )

