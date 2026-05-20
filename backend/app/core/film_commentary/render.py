from __future__ import annotations

import logging

from app.api.auto_edit import _prepare_auto_edit_segments_from_plan
from app.api.subtitle import execute_burn_subtitle, generate_srt
from app.models.auto_edit import Plan
from app.models.subtitle import BurnSubtitleRequest, GenerateSRTRequest, SubtitleStyle

logger = logging.getLogger(__name__)


async def render_plan_to_video(
    *,
    plan: Plan,
    project_name: str,
    include_subtitle: bool = True,
) -> tuple[str, str]:
    """将 Plan 烧录为成片，返回 (filename, url)。"""
    style = SubtitleStyle()
    seg_inputs, resolved_style, resolved_name, use_tts_branch = await _prepare_auto_edit_segments_from_plan(
        plan=plan,
        project_name=project_name,
        style=style,
        force_tts_pipeline=True,
        tts_align=None,
    )
    if not use_tts_branch:
        raise RuntimeError("影视解说方案须走 TTS 配音轨")

    if include_subtitle:
        srt_res = await generate_srt(
            GenerateSRTRequest(
                segments=seg_inputs,
                style=resolved_style,
                use_tts_timing=True,
                split_narration_by_sentence=True,
            )
        )
        srt_content = srt_res.srt_content
    else:
        srt_content = ""

    burn_res = await execute_burn_subtitle(
        BurnSubtitleRequest(
            segments=seg_inputs,
            srt_content=srt_content,
            style=resolved_style,
            project_name=resolved_name,
            require_tts_audio=True,
        )
    )
    return burn_res["filename"], burn_res["url"]
