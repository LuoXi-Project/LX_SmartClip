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

from app.core.subtitle.segment_render_materialize import materialize_clip_paths_for_group

def collect_segment_sources(seg, clip_map: dict, seg_idx: int) -> Tuple[List[str], List[dict]]:
    from fastapi import HTTPException

    # 强约束：只要 clip_trims 存在，就“只能使用 clip_trims 指定的素材顺序与出入点”。
    # 绝不能回退到 clip_ids（匹配组）或 clip_id（单素材），否则会混入用户未选中的素材。
    trims = getattr(seg, "clip_trims", None) or []
    if trims:
        clip_ids: List[str] = []
        for ti, t in enumerate(trims, 1):
            cid = str(getattr(t, "clip_id", "") or "").strip()
            if not cid:
                raise HTTPException(400, f"clip_trims 第 {ti} 条缺少 clip_id: seg_{(int(seg_idx) + 1)}")
            clip_ids.append(cid)
    else:
        raw_ids = list(getattr(seg, "clip_ids", None) or [])
        if not raw_ids and getattr(seg, "clip_id", None):
            raw_ids = [seg.clip_id]
        clip_ids = list(dict.fromkeys([cid for cid in raw_ids if cid]))

    if not clip_ids:
        raise HTTPException(400, f"片段缺少 clip_id: seg_{(int(seg_idx) + 1)}")
    infos: List[dict] = []
    for cid in clip_ids:
        info = clip_map.get(cid)
        if not info or not os.path.isfile(info["path"] or ""):
            raise HTTPException(404, f"片段不存在: {cid}")
        infos.append(info)

    if trims:
        try:
            trims_brief = [
                {
                    "clip_id": str(getattr(t, "clip_id", "") or ""),
                    "start": float(getattr(t, "clip_start_sec", 0.0) or 0.0),
                    "dur": float(getattr(t, "duration_sec", 0.0) or 0.0),
                }
                for t in trims
            ]
        except Exception:
            trims_brief = ["<unprintable clip_trims>"]
        logger.info(
            "seg_%d sources=%s (clip_trims=True) trims=%s",
            int(seg_idx) + 1,
            clip_ids,
            trims_brief,
        )
    else:
        logger.info("seg_%d sources=%s (clip_trims=False)", int(seg_idx) + 1, clip_ids)
    return clip_ids, infos

def resolve_desired_dur(seg) -> Optional[float]:
    try:
        v = float(getattr(seg, "duration_sec", None)) if getattr(seg, "duration_sec", None) is not None else None
    except Exception:
        v = None
    if v is not None and v <= 0:
        return None
    return v

def segment_has_tts(seg, tts_audio_dir: str) -> bool:
    name = str(getattr(seg, "tts_filename", "") or "").strip()
    if not name:
        return False
    return os.path.isfile(os.path.join(tts_audio_dir, os.path.basename(name)))

