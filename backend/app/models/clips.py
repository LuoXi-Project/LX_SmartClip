from pydantic import BaseModel, Field


class ClipUpdatePayload(BaseModel):
    asr_text: str | None = None
    asr_segments: str | None = Field(
        None,
        description="JSON 字符串：list[{start,end,text}]，时间相对片段内音频，与 ASR 管线一致",
    )
    vlm_description: str | None = None
