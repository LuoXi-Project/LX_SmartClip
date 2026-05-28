"""音频匹配成片：上传配音 → ASR 时间轴 → 按段切片供成片管线使用。"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class AudioMatchSliceItem(BaseModel):
    start_sec: float = Field(..., ge=0.0, description="相对源音频起点（秒）")
    end_sec: float = Field(..., gt=0.0, description="相对源音频终点（秒）")


class AudioMatchSliceRequest(BaseModel):
    source_filename: str = Field(..., min_length=1, description="transcribe 返回的 source_filename")
    slices: List[AudioMatchSliceItem] = Field(..., min_length=1)


class AudioMatchSliceResponse(BaseModel):
    filenames: List[str] = Field(..., description="写入 tts_audio 目录的切片文件名，与 slices 顺序一致")
