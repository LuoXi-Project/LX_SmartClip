from pydantic import BaseModel


class ClipUpdatePayload(BaseModel):
    asr_text: str | None = None
    vlm_description: str | None = None

