from __future__ import annotations

from app.core.auto_edit_v2.template_config import get_template_slots, normalize_template_preset

_EVENTS_SYS_PROMPT = """你是一位视频素材事件提名器（event nominator）。
你将收到若干条素材片段的文本信息（包含 clip_id、ASR/VLM 摘要等）。
你的任务是：为每个 clip 提名若干“可用于剪辑编排”的事件 ClipEvent，并给出 role/beat 和局部分数。

events[*].text 的写法（极其重要）：
- 必须是观众在画面上直接阅读、或配音员直接念出的一句「成品口播/字幕正文」。
- 禁止写成编导说明、分镜提示、拍摄/剪辑任务书。禁止以「本段」「此处」「结束演示」「引导观众」「展示如何」「用于」等第三人称策划口吻概括任务。
- 错误示例：「结束演示，引导观众私信获取软件与密钥。」（这是任务说明，不是给观众看的句子）
- 正确示例：「想要软件和密钥的朋友，私信我「工具」两个字就行。」（观众能直接看懂、可上屏）
- 若素材是演示/教程，text 仍要写观众视角的一句话（可基于 ASR 改写），不要写「演示结束」类元信息。

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
      "text": "一句可直接上屏的口播/字幕正文（禁止编导说明体）",
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
        "- 模板模式下：各 slot 对应的 text 仍是「成品一句」，只体现该段要讲给观众的内容；"
        "不要复述 slot 名称、不要写「本段负责 hook/cta」或「收束并引导」这类策划用语。\n"
    )

