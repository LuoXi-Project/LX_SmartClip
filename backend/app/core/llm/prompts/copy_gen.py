from __future__ import annotations

from app.models.copy_gen import CopyGenRequest

SYSTEM_PROMPT = """你是一位专业的视频文案创作师。
用户会给你提供一段或多段视频的 ASR 语音识别台词和 VLM 画面描述内容，
以及用户的创作诉求（如主题、风格、目的）。

你的任务：
1. 深度理解视频内容（台词 + 画面）。
2. 根据用户诉求，撰写吸引人的视频文案。
3. 将文案按段落拆分，每段对应一个视频片段或一个叙事节拍。
4. 每段之间用空行分隔，不要有编号或序号前缀。
5. 文案要自然流畅、有感染力，符合短视频风格。
6. 只输出文案内容，不要输出任何解释或元信息。"""


def build_user_message(context: str, req: CopyGenRequest) -> str:
    style_hint = f"\n风格要求：{req.style}" if req.style else ""
    return (
        f"以下是视频的识别内容：\n{context}\n\n"
        f"---\n"
        f"用户诉求：{req.user_prompt}{style_hint}\n"
        f"请将文案拆分为约 {req.max_segments} 段（每段空行分隔），每段对应一个叙事节拍。"
    )

