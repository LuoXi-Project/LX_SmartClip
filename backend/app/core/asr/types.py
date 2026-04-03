"""ASR 结构化输出：带时间轴的片段（用于静音快剪、句级对齐等）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List


@dataclass(frozen=True)
class ASRSegment:
    """单条时间对齐文本（与 Whisper/OpenAPI 段粒度一致，通常接近短语/短句）。"""

    start: float  # 相对当前音频文件起点，秒
    end: float
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "text": self.text}


@dataclass(frozen=True)
class ASRTranscript:
    """完整转写 + 时间轴片段。"""

    text: str
    segments: tuple[ASRSegment, ...] = field(default_factory=tuple)

    def segments_as_dicts(self) -> List[dict[str, Any]]:
        return [s.to_dict() for s in self.segments]
