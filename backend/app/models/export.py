from typing import List, Optional
from pydantic import BaseModel, Field

class ExportRequest(BaseModel):
    clip_ids: List[str] = Field(..., min_length=1, description="要导出的片段 ID 列表")
    project_name: Optional[str] = Field("smartclip_project", description="工程包名称")
    include_audio: bool = Field(True, description="是否包含 TTS 音频文件")
    tts_filenames: Optional[List[str]] = Field(None, description="TTS 音频文件名列表（与 clip_ids 一一对应）")
