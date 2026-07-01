from pydantic import BaseModel, Field


class ClipUpdatePayload(BaseModel):
    asr_text: str | None = None
    asr_segments: str | None = Field(
        None,
        description="JSON 字符串：list[{start,end,text}]，时间相对片段内音频，与 ASR 管线一致",
    )
    vlm_description: str | None = None
    abstract_summary: str | None = Field(
        None, description="智能标注：旁白适配摘要（抹平旁白-画面表征鸿沟）"
    )
    keywords: str | None = Field(
        None, description="智能标注：JSON 字符串 list[str]，关键词"
    )
    emotion_tags: str | None = Field(
        None, description="智能标注：JSON 字符串 list[str]，情绪标签"
    )
