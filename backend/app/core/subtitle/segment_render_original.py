from __future__ import annotations

import logging
import os
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from app.models.subtitle import TtsVideoAlignConfig
from app.core.subtitle.timeline import _tts_file_duration
from app.utils.ffprobe_utils import probe_duration, probe_keyframes_times, probe_video_dimensions
from app.utils.ffmpeg_utils import run_ffmpeg, write_concat_list
from app.core.subtitle.tts_align import (
    build_atempo_filter_chain,
    resolve_stretch_audio_atempo,
    resolve_stretch_video_pts_factor,
)
from app.core.auto_edit.mix_visual import build_segment_visual_filters
from app.core.subtitle.render_opts import (
    build_extra_video_filters,
    build_render_codec_args,
    force_video_reencode,
    sanitize_no_stream_copy,
)

logger = logging.getLogger(__name__)

_PLAYLIST_MATERIALIZE_SEG = SimpleNamespace(
    clip_trims=None,
    clip_start_sec=None,
    duration_sec=None,
)

from app.core.subtitle.segment_render_common import collect_segment_sources, resolve_desired_dur
from app.core.subtitle.segment_render_materialize import materialize_clip_paths_for_group
from app.core.subtitle.segment_render_helpers import _cap_segment_to_duration

def render_original_segment(
    *,
    seg,
    clip_ids,
    infos,
    tmp,
    seg_idx,
    render_opts,
    keyframe_cache: Optional[Dict[str, List[float]]] = None,
    materialize_cache: Optional[Dict[str, Tuple[str, float]]] = None,
    from_source_video: bool = True,
) -> str:
    seg_out = os.path.join(tmp, f"seg_{seg_idx:03d}.mp4")

    paths_group, source_total_after = materialize_clip_paths_for_group(
        seg=seg,
        clip_ids=clip_ids,
        infos=infos,
        tmp=tmp,
        seg_idx=seg_idx,
        render_opts=render_opts,
        keyframe_cache=keyframe_cache,
        materialize_cache=materialize_cache,
        force_materialize=False,
        from_source_video=from_source_video,
    )

    desired_dur = resolve_desired_dur(seg)
    trim_dur = min(desired_dur, source_total_after) if desired_dur else None
    # 误差内视为“无需再裁剪”，避免单段触发二次重编码。
    if trim_dur is not None and abs(float(trim_dur) - float(source_total_after)) <= 0.03:
        trim_dur = None

    # 快路径：单段且不需要再裁剪 → 直接复用（避免无意义的重编码）
    if len(paths_group) == 1 and not trim_dur:
        return paths_group[0]

    # 快路径：多段且不需要 segment-level trim/滤镜 → 优先 concat demuxer + copy（失败再回退）
    if len(paths_group) > 1 and not trim_dur:
        concat_list = os.path.join(tmp, f"seg_{seg_idx:03d}_concat.txt")
        write_concat_list(paths_group, concat_list)
        try:
            run_ffmpeg(
                [
                    "-fflags",
                    "+genpts",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    concat_list,
                    "-c",
                    "copy",
                    "-avoid_negative_ts",
                    "make_zero",
                    "-movflags",
                    "+faststart",
                    seg_out,
                ],
                desc=f"original seg {(int(seg_idx) + 1)} (concat+copy)",
            )
            return seg_out
        except Exception:
            # fallback: 走原 filter_complex 路径
            pass

    seg_codec_args = build_render_codec_args(sanitize_no_stream_copy(dict(render_opts or {})))

    # 🚀 输入
    cmd = []
    for p in paths_group:
        cmd += ["-i", p]

    filter_parts = []
    concat_inputs = []

    # 👉 每段重建时间轴
    for i in range(len(paths_group)):
        filter_parts.append(f"[{i}:v]setpts=PTS-STARTPTS[v{i}]")
        filter_parts.append(f"[{i}:a]asetpts=PTS-STARTPTS[a{i}]")
        concat_inputs.append(f"[v{i}][a{i}]")

    # 👉 拼接
    filter_parts.append(f"{''.join(concat_inputs)}concat=n={len(paths_group)}:v=1:a=1[vcat][acat]")

    # 👉 精准裁剪（关键）
    if trim_dur:
        filter_parts.append(f"[vcat]trim=0:{trim_dur},setpts=PTS-STARTPTS[vout]")
        filter_parts.append(f"[acat]atrim=0:{trim_dur},asetpts=PTS-STARTPTS[aout]")
    else:
        filter_parts.append("[vcat]setpts=PTS-STARTPTS[vout]")
        filter_parts.append("[acat]asetpts=PTS-STARTPTS[aout]")

    filter_complex = ";".join(filter_parts)

    run_ffmpeg(
        [
            *cmd,
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            *seg_codec_args,
            "-movflags",
            "+faststart",
            seg_out,
        ],
        desc=f"original seg {(int(seg_idx) + 1)}",
    )

    return seg_out

def render_muted_segment(
    *,
    seg,
    clip_ids,
    infos,
    tmp,
    seg_idx,
    render_opts,
    keyframe_cache: Optional[Dict[str, List[float]]] = None,
    materialize_cache: Optional[Dict[str, Tuple[str, float]]] = None,
    from_source_video: bool = True,
) -> str:
    """混剪「仅 BGM」：保留画面，将素材原声置零（后续由 BGM 混音提供听感）。"""
    raw_path = render_original_segment(
        seg=seg,
        clip_ids=clip_ids,
        infos=infos,
        tmp=tmp,
        seg_idx=int(seg_idx) + 10000,
        render_opts=render_opts,
        keyframe_cache=keyframe_cache,
        materialize_cache=materialize_cache,
        from_source_video=from_source_video,
    )
    seg_out = os.path.join(tmp, f"seg_{seg_idx:03d}.mp4")
    dur = float(probe_duration(raw_path, log_on_failure=True) or 0.0)
    desired = resolve_desired_dur(seg)
    if desired is not None and float(desired) > 0.05:
        dur = min(dur, float(desired)) if dur > 0.05 else float(desired)
    if dur <= 0.05:
        dur = 5.0
    codec_args = build_render_codec_args(sanitize_no_stream_copy(dict(render_opts or {})))
    try:
        vi = codec_args.index("-c:v")
        codec_args[vi + 1] = "copy"
    except ValueError:
        codec_args = ["-c:v", "copy", *codec_args]
    run_ffmpeg(
        [
            "-i",
            raw_path,
            "-af",
            "volume=0",
            "-t",
            f"{dur:.3f}",
            *codec_args,
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            seg_out,
        ],
        desc=f"mute seg {(int(seg_idx) + 1)}",
    )
    return seg_out

