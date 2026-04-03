"""subtitle.py — 字幕相关的数据模型（Pydantic schemas）。"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class SubtitleSegmentInput(BaseModel):
    copy_text: str
    clip_id: str
    clip_ids: Optional[List[str]] = None
    tts_filename: Optional[str] = None
    # 用于“原声导出”精确裁剪：表示从该 clip 内部的起点（秒）开始截取。
    # 仅建议在当前实现支持的场景使用（例如 quick-cut 单 clip）。
    clip_start_sec: Optional[float] = None
    # 可控时长：当用户在前端手动调整段落时长时使用（单位秒）。
    # 注：对 TTS 段落如强制缩短会截断音频；对非 TTS 段落会裁剪视频输出以对齐字幕时间轴。
    duration_sec: Optional[float] = None


class SubtitleStyle(BaseModel):
    font_name: str = "Arial"
    font_size: int = 24
    font_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_width: float = 2.0
    shadow: float = 1.0
    bold: bool = False
    italic: bool = False
    position: str = "bottom"  # bottom | center | top
    margin_v: int = 20
    pos_x_pct: float = 50.0
    pos_y_pct: float = 90.0
    background: bool = False
    max_chars_per_line: int = 20


class GenerateSRTRequest(BaseModel):
    segments: List[SubtitleSegmentInput]
    style: Optional[SubtitleStyle] = None
    use_tts_timing: bool = True


class SRTEntry(BaseModel):
    index: int
    start: float
    end: float
    text: str
    clip_id: str


class GenerateSRTResponse(BaseModel):
    srt_content: str
    entries: List[SRTEntry]
    total_duration: float
    timing_source: str


class BurnSubtitleResponse(BaseModel):
    filename: str
    url: str


class BurnSubtitleRequest(BaseModel):
    segments: List[SubtitleSegmentInput]
    srt_content: str
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    project_name: Optional[str] = "smartclip_subtitled"


class ExportOriginalRequest(BaseModel):
    """
    原声导出：
    - 不使用 TTS（忽略 tts_filename）
    - 段落（segments 内每一段）的总时长 = 该段选中 clip 组的时长之和
    - 可选：按“句子/换行”切分文案，并在该段总时长内等分
    - 可选：对最终音频做归一化/限幅
    """

    segments: List[SubtitleSegmentInput]
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    project_name: Optional[str] = "smartclip_original"
    include_subtitle: bool = True
    normalize_audio: bool = True

