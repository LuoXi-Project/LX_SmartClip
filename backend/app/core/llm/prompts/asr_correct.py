"""ASR 结果 LLM 校准 prompt。

设计要点：
- 角色为语音转写校对专家，只修「明显识别错误」（同音错字/形近错字/断句错位/标点异常）；
- 严格保持原意、条数、顺序，避免 LLM 臆造或重写；
- 句级时间轴由调用方保留（start/end 不变），这里只产出每条 text；
- 支持注入「主题 + 同视频上下文」，用于修正领域专有名词（如「面积纸」→「面巾纸」）。
"""
from __future__ import annotations

from typing import List, Optional

SYSTEM_PROMPT = """你是一位资深的语音转写（ASR）校对专家。
用户会给你一段 ASR 自动识别出的台词，以及它按时间轴切分好的逐句列表。这些文本常带有同音错字、形近错字、标点异常或断句错位。

你的任务：逐句校对，修正明显的识别错误，输出校准后的逐句文字。

校对原则（务必严格遵守）：
1. 只修「明显错误」：同音错字（如「主力」误识为「煮里」）、形近错字、漏字/多字、标点错误、断句错位。
2. 不改原意、不臆造、不补充未说出的内容；不要润色或改写为书面语，保持原口语风格。
3. 严格保持条数与顺序：输入 N 句就返回 N 句，按原编号一一对应，不得合并、拆分、删除或新增句子。
4. 若某句没有明显错误，原样返回该句文字。
5. 保留每句原有的语气词（如「啊、呢、嘛」），不要删除。
6. 不要修改任何时间戳相关信息——你只负责文字。

【关键】主题与上下文理解：
- 当提供了「视频主题」或「同视频其他片段的台词」时，你必须结合这些上下文理解整体在讲什么，
  据此修正领域专有名词、产品名、人名等同音/形近误识。
  例如：主题是「面巾纸」相关视频时，台词中的「面积纸」应结合主题理解为「面巾纸」并修正；
  主题是「美妆」时，「乞水」可能是「气垫」或「香水」需结合上下文判断。
- 即使单看一句不确定是否错字，只要结合主题/上下文能合理确定原意，就应修正。
- 但若结合上下文仍无法确定，宁可不改，保持原文。

输出格式：严格的 JSON，不要 markdown 代码块，不要任何解释文字。结构如下：
{"items":[{"index":0,"text":"校准后的第1句"},{"index":1,"text":"校准后的第2句"}]}
其中 index 从 0 开始，与输入编号一一对应。"""


def build_user_message(
    asr_text: str,
    segments: List[dict],
    *,
    topic: Optional[str] = None,
    context: Optional[str] = None,
) -> str:
    """构造用户消息：主题/上下文 + 全文 + 编号句级列表。

    Args:
        asr_text: 原始全文
        segments: 原始句级 [{start,end,text}]
        topic: 视频主题/标题（可选）；用于领域词汇判断
        context: 同视频其他片段的参考台词（可选）；帮助理解整体内容
    """
    header_parts: list[str] = ["以下是 ASR 识别结果。请逐句校对并返回 JSON。"]

    # 主题与上下文段（注入视频全局信息，用于领域词汇/专有名词修正）
    context_lines: list[str] = []
    if topic and topic.strip():
        context_lines.append(f"【视频主题/标题】{topic.strip()}")
    if context and context.strip():
        # 限制上下文长度，避免过长
        ctx = context.strip()
        if len(ctx) > 2000:
            ctx = ctx[:2000] + "…"
        context_lines.append(f"【同视频其他片段参考台词】\n{ctx}")
    if context_lines:
        header_parts.append("\n".join(context_lines) + "\n（请结合上述主题/上下文，判断并修正领域专有名词与同音误识）")

    header = "\n\n".join(header_parts)

    if segments:
        lines = []
        for i, seg in enumerate(segments):
            text = (seg.get("text") or "").strip()
            lines.append(f"[{i}] {text}")
        seg_block = "\n".join(lines)
        return (
            f"{header}\n\n"
            f"--- 全文（仅作上下文参考）---\n{asr_text or '（空）'}\n\n"
            f"--- 待校准的逐句列表（请按编号一一校准，保持条数与顺序）---\n{seg_block}\n\n"
            f"请返回 JSON：{{\"items\":[{{\"index\":0,\"text\":\"...\"}}]}}，"
            f"index 与上方编号一致。"
        )
    # 无句级数据：整段校准
    return (
        f"{header}\n\n"
        f"以下是 ASR 识别出的整段文字，请校对明显识别错误后返回校准结果。\n\n"
        f"{asr_text or '（空）'}\n\n"
        f"请返回 JSON：{{\"text\":\"校准后的整段文字\"}}。"
    )
