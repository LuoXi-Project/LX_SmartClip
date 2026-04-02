from typing import Optional
from pydantic import BaseModel, Field

# ──────────────────────────── 请求 / 响应模型 ──────────────────────────── #

class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="待合成文本")
    voice: Optional[str] = Field(None, description="语音角色（可选，不填用配置默认值）")
    rate: Optional[str] = Field(None, description="语速，如 +0%/-20%（可选）")
    volume: Optional[str] = Field(None, description="音量，如 +0%/+10%（可选）")


class SynthesizeResponse(BaseModel):
    filename: str
    url: str
    voice: str
    rate: str
    volume: str
    text_length: int


class VoiceInfo(BaseModel):
    name: str
    locale: str
    gender: str
    friendly_name: str

