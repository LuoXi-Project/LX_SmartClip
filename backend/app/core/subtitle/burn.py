"""字幕烧录门面：对外提供稳定 API。

说明：
- 旧实现曾集中在 `burn.py`，单文件过大且难维护。
- 当前将实现拆分到多个模块，此文件作为唯一对外入口，便于企业级维护/测试/演进。
"""

import logging
import os
import tempfile
from typing import TYPE_CHECKING, Dict, List, Optional

from app.utils.ffprobe_utils import probe_duration
from app.utils.paths import get_render_tmp_base_dir

from .ass_builder import build_ass  # noqa: F401 - re-export for backwards compatibility
from .composer import compose_final_video, compose_final_video_moviepy
from .render_opts import final_render_opts_from_export, sanitize_no_stream_copy, truthy_export_gpu
from .segment_render import (
    collect_segment_sources,
    render_original_segment,
    render_tts_segment,
    segment_has_tts,
)

if TYPE_CHECKING:
    from app.models.subtitle import SubtitleStyle, TtsVideoAlignConfig

logger = logging.getLogger(__name__)


def burn_to_mp4(
    segments,
    srt_entries: list,
    clip_map: dict,
    style: "SubtitleStyle",
    project_name: str,
    tts_audio_dir: str,
    fonts_dir: str,
    render_opts: Optional[Dict[str, str]] = None,
    export_render_opts: Optional[Dict[str, str]] = None,
    render_mode: str = "auto",
    export_backend: str = "moviepy",  # ffmpeg | moviepy
    normalize_audio: bool = False,
    output_dir: str = None,
    materialize_from_source: bool = True,
    tts_align: Optional["TtsVideoAlignConfig"] = None,
) -> tuple:
    from fastapi import HTTPException

    if not segments:
        raise HTTPException(400, "segments不能为空")

    prefer_gpu = truthy_export_gpu((export_render_opts or {}).get("export_gpu"))
    final_render_opts = sanitize_no_stream_copy(
        final_render_opts_from_export(export_render_opts, render_opts)
    )
    # 从原片裁剪时用 export_* 合并结果；仅用预处理 clip 时用 clip_*（避免低质切片参数污染成片）
    segment_render_opts = final_render_opts if materialize_from_source else (render_opts or {})

    mode = (render_mode or "auto").strip().lower()
    if mode not in ("auto", "original", "tts"):
        mode = "auto"
    if mode == "auto":
        mode = (
            "tts"
            if any(segment_has_tts(seg, tts_audio_dir) for seg in segments)
            else "original"
        )
    logger.info(
        "burn_to_mp4 mode=%s segments=%d subtitles=%d",
        mode,
        len(segments),
        len(srt_entries),
    )

    tmp_base_dir = get_render_tmp_base_dir()
    with tempfile.TemporaryDirectory(dir=tmp_base_dir, prefix="burn_") as tmp:
        logger.info("临时渲染目录: %s", tmp)

        keyframe_cache: Dict[str, List[float]] = {}
        seg_paths: List[str] = []

        for i, seg in enumerate(segments):
            clip_ids, infos = collect_segment_sources(seg, clip_map, i)
            if mode == "tts":
                seg_out = render_tts_segment(
                    seg=seg,
                    clip_ids=clip_ids,
                    infos=infos,
                    tmp=tmp,
                    seg_idx=i,
                    tts_audio_dir=tts_audio_dir,
                    render_opts=segment_render_opts,
                    keyframe_cache=keyframe_cache,
                    from_source_video=materialize_from_source,
                    tts_align=tts_align,
                )
            else:
                seg_out = render_original_segment(
                    seg=seg,
                    clip_ids=clip_ids,
                    infos=infos,
                    tmp=tmp,
                    seg_idx=i,
                    render_opts=segment_render_opts,
                    keyframe_cache=keyframe_cache,
                    from_source_video=materialize_from_source,
                )
            seg_paths.append(seg_out)

        for i, p in enumerate(seg_paths, 1):
            d = float(probe_duration(p, log_on_failure=True) or 0.0)
            logger.info("mode=%s seg=%d final_seg_dur=%.3f path=%s", mode, i, d, p)

        backend = (export_backend or "moviepy").strip().lower()
        if backend not in ("ffmpeg", "moviepy"):
            backend = "moviepy"

        if backend == "moviepy":
            out_path = compose_final_video_moviepy(
                seg_paths=seg_paths,
                srt_entries=srt_entries,
                style=style,
                fonts_dir=fonts_dir,
                tmp=tmp,
                project_name=project_name,
                final_render_opts=final_render_opts,
                normalize_audio=normalize_audio,
                prefer_gpu=prefer_gpu,
            )
        else:
            out_path = compose_final_video(
                seg_paths=seg_paths,
                srt_entries=srt_entries,
                style=style,
                fonts_dir=fonts_dir,
                tmp=tmp,
                project_name=project_name,
                final_render_opts=final_render_opts,
                normalize_audio=normalize_audio,
                prefer_gpu=prefer_gpu,
            )
        logger.info("导出 MP4 完成: %s", out_path)

        with open(out_path, "rb") as f:
            data = f.read()

        saved_path = None
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            saved_path = os.path.join(output_dir, f"{project_name}.mp4")
            with open(saved_path, "wb") as f:
                f.write(data)
            logger.info("持久化保存: %s", saved_path)

    return data, saved_path

