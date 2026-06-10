"""字幕片段渲染：materialize / original / tts 分支（聚合导出）。"""
from app.core.subtitle.segment_render_common import (
    collect_segment_sources,
    resolve_desired_dur,
    segment_has_tts,
)
from app.core.subtitle.segment_render_materialize import materialize_clip_paths_for_group
from app.core.subtitle.segment_render_original import render_muted_segment, render_original_segment
from app.core.subtitle.segment_render_tts import render_tts_segment

__all__ = [
    "collect_segment_sources",
    "materialize_clip_paths_for_group",
    "render_muted_segment",
    "render_original_segment",
    "render_tts_segment",
    "resolve_desired_dur",
    "segment_has_tts",
]
