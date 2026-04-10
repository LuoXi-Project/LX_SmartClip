from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

from app.utils.ffprobe_utils import probe_duration, probe_keyframes_times

from app.utils.ffmpeg_utils import run_ffmpeg, write_concat_list
from .render_opts import (
    build_extra_video_filters,
    build_render_codec_args,
    force_video_reencode,
    sanitize_no_stream_copy,
)

logger = logging.getLogger(__name__)


def _is_near_keyframe(ts: float, keyframes: List[float], *, threshold_sec: float = 0.04) -> bool:
    if not keyframes:
        return False
    t = float(ts)
    for kf in keyframes:
        if abs(t - kf) <= threshold_sec:
            return True
    return False


def _nearest_keyframe_distance(ts: float, keyframes: List[float]) -> float:
    if not keyframes:
        return 1e9
    t = float(ts)
    return min(abs(t - kf) for kf in keyframes)


def _trim_map_from_seg(seg, clip_ids: List[str]) -> Dict[str, Tuple[float, float]]:
    """clip_id -> (start_sec, span_sec)。无 clip_trims 时回退单段 clip_start_sec/duration_sec。"""
    out: Dict[str, Tuple[float, float]] = {}
    parts = getattr(seg, "clip_trims", None) or []
    for p in parts:
        try:
            cid = str(getattr(p, "clip_id", None) or "")
            if not cid:
                continue
            st = float(getattr(p, "clip_start_sec", None) or 0.0)
            sp = float(getattr(p, "duration_sec", None) or 0.0)
            if sp > 0.05:
                out[cid] = (max(0.0, st), sp)
        except Exception:
            continue
    if not out and len(clip_ids) == 1:
        cid = clip_ids[0]
        cs = getattr(seg, "clip_start_sec", None)
        ds = getattr(seg, "duration_sec", None)
        try:
            st = float(cs) if cs is not None else 0.0
            st = max(0.0, st)
        except Exception:
            st = 0.0
        try:
            sp = float(ds) if ds is not None else None
        except Exception:
            sp = None
        if sp is not None and sp > 0.05:
            out[cid] = (st, sp)
    return out


def materialize_clip_paths_for_group(
    *,
    seg,
    clip_ids: List[str],
    infos: List[dict],
    tmp: str,
    seg_idx: int,
    render_opts: Optional[Dict[str, str]],
    keyframe_cache: Optional[Dict[str, List[float]]] = None,
) -> Tuple[List[str], float]:
    """
    按顺序处理 clip 组：必要时逐段 ffmpeg 裁剪，返回 concat 用的路径列表与总视频时长。
    """
    trim_map = _trim_map_from_seg(seg, clip_ids)
    seg_filter_parts = build_extra_video_filters(render_opts)
    seg_vf_args = ["-vf", ",".join(seg_filter_parts)] if seg_filter_parts else []

    kf_cache = keyframe_cache if keyframe_cache is not None else {}
    paths_out: List[str] = []
    total_dur = 0.0
    for j, (cid, info) in enumerate(zip(clip_ids, infos)):
        src_path = info["path"]
        # 以实际文件时长为准：库表 duration 可能偏短，若优先用表会导致出入点 span 被错误截断
        src_total = float(probe_duration(src_path, log_on_failure=True) or 0.0)
        if src_total <= 0.05:
            src_total = float(info.get("dur") or 0.0)
        if src_total <= 0.05:
            src_total = 0.05

        if cid in trim_map:
            start, span = trim_map[cid]
            start = max(0.0, min(start, src_total - 0.05))
            span = min(max(0.05, span), max(0.05, src_total - start))
        else:
            start, span = 0.0, src_total

        need_trim = start > 0.001 or (span + 0.02) < (src_total - start - 0.001)
        if not need_trim:
            paths_out.append(src_path)
            piece_dur = src_total
        else:
            trim_tmp = os.path.join(tmp, f"seg_{seg_idx:03d}_p{j:02d}_trim.mp4")
            end = start + span

            # 只有“纯裁剪”（不带视频滤镜）才可能安全 stream copy。
            can_try_copy = not seg_filter_parts
            did_copy = False
            if can_try_copy:
                if src_path not in kf_cache:
                    kf_cache[src_path] = probe_keyframes_times(src_path, logger_=logger)
                kfs = kf_cache.get(src_path) or []

                start_aligned = start <= 0.01 or _is_near_keyframe(start, kfs)
                end_aligned = (src_total - end) <= 0.05 or _is_near_keyframe(end, kfs)
                near_enough = _nearest_keyframe_distance(start, kfs) <= 0.20 and _nearest_keyframe_distance(end, kfs) <= 0.20

                # 情况1：关键帧对齐（或贴近片尾）→ 直接 copy（快且更可靠）
                if start_aligned and end_aligned:
                    run_ffmpeg(
                        [
                            "-ss",
                            f"{start:.3f}",
                            "-t",
                            f"{span:.3f}",
                            "-i",
                            src_path,
                            "-c",
                            "copy",
                            "-avoid_negative_ts",
                            "make_zero",
                            "-movflags",
                            "+faststart",
                            trim_tmp,
                        ],
                        desc=f"pretrim(copy) clip {cid} seg{seg_idx + 1}",
                    )
                    did_copy = True
                # 情况2：轻微偏移 → 先试 copy，失败/异常再回退重编码
                elif near_enough:
                    try:
                        run_ffmpeg(
                            [
                                "-ss",
                                f"{start:.3f}",
                                "-t",
                                f"{span:.3f}",
                                "-i",
                                src_path,
                                "-c",
                                "copy",
                                "-avoid_negative_ts",
                                "make_zero",
                                "-movflags",
                                "+faststart",
                                trim_tmp,
                            ],
                            desc=f"pretrim(try_copy) clip {cid} seg{seg_idx + 1}",
                        )
                        did_copy = True
                    except Exception:
                        did_copy = False

            if not did_copy:
                # 精确裁剪：回退到重编码（保证切点准确）
                trim_opts = sanitize_no_stream_copy(dict(render_opts or {}))
                seg_codec_args = build_render_codec_args(trim_opts)
                if seg_filter_parts:
                    seg_codec_args = force_video_reencode(seg_codec_args, render_opts=trim_opts)
                run_ffmpeg(
                    [
                        "-i",
                        src_path,
                        "-ss",
                        f"{start:.3f}",
                        "-t",
                        f"{span:.3f}",
                        *seg_vf_args,
                        *seg_codec_args,
                        "-movflags",
                        "+faststart",
                        trim_tmp,
                    ],
                    desc=f"pretrim(encode) clip {cid} seg{seg_idx + 1}",
                )

            paths_out.append(trim_tmp)
            probed = float(probe_duration(trim_tmp, log_on_failure=True) or 0.0)
            piece_dur = probed if probed > 0.05 else span

        total_dur += max(piece_dur, 0.05)

    return paths_out, total_dur


def collect_segment_sources(seg, clip_map: dict, seg_idx: int) -> Tuple[List[str], List[dict]]:
    from fastapi import HTTPException

    raw_ids = list(getattr(seg, "clip_ids", None) or [])
    if not raw_ids and getattr(seg, "clip_id", None):
        raw_ids = [seg.clip_id]
    clip_ids = list(dict.fromkeys([cid for cid in raw_ids if cid]))
    if not clip_ids:
        raise HTTPException(400, f"片段缺少 clip_id: seg_{seg_idx + 1}")
    infos: List[dict] = []
    for cid in clip_ids:
        info = clip_map.get(cid)
        if not info or not os.path.isfile(info["path"] or ""):
            raise HTTPException(404, f"片段不存在: {cid}")
        infos.append(info)
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


def render_original_segment(
    *,
    seg,
    clip_ids,
    infos,
    tmp,
    seg_idx,
    render_opts,
    keyframe_cache: Optional[Dict[str, List[float]]] = None,
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
    )

    desired_dur = resolve_desired_dur(seg)
    trim_dur = min(desired_dur, source_total_after) if desired_dur else None

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
                desc=f"original seg {seg_idx+1} (concat+copy)",
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
        desc=f"original seg {seg_idx+1}",
    )

    return seg_out


def render_tts_segment(
    *,
    seg,
    clip_ids,
    infos,
    tmp,
    seg_idx,
    tts_audio_dir,
    render_opts,
    keyframe_cache: Optional[Dict[str, List[float]]] = None,
) -> str:
    from fastapi import HTTPException

    name = str(getattr(seg, "tts_filename", "") or "").strip()
    if not name:
        raise HTTPException(400, f"TTS 文件名为空: seg_{seg_idx + 1}，请先合成配音")

    tts_path = os.path.join(tts_audio_dir, os.path.basename(name))
    if not os.path.isfile(tts_path):
        raise HTTPException(400, f"TTS 音频不存在: seg_{seg_idx + 1}")

    seg_out = os.path.join(tmp, f"seg_{seg_idx:03d}.mp4")

    paths_group, _ = materialize_clip_paths_for_group(
        seg=seg,
        clip_ids=clip_ids,
        infos=infos,
        tmp=tmp,
        seg_idx=seg_idx,
        render_opts=render_opts,
        keyframe_cache=keyframe_cache,
    )

    audio_dur = float(probe_duration(tts_path) or 0.0)
    if audio_dur <= 0:
        raise HTTPException(400, "TTS 音频无效")

    seg_codec_args = force_video_reencode(build_render_codec_args(render_opts), render_opts=render_opts)

    cmd = []
    for p in paths_group:
        cmd += ["-i", p]
    cmd += ["-i", tts_path]

    filter_parts = []
    concat_inputs = []

    # 👉 视频拼接（无音频）
    for i in range(len(paths_group)):
        filter_parts.append(f"[{i}:v]setpts=PTS-STARTPTS[v{i}]")
        concat_inputs.append(f"[v{i}]")

    filter_parts.append(f"{''.join(concat_inputs)}concat=n={len(paths_group)}:v=1:a=0[vcat]")

    # 👉 无限循环 + 精准裁剪（替代 stream_loop）
    filter_parts.append(
        f"[vcat]loop=loop=-1:size=999999:start=0," f"trim=0:{audio_dur},setpts=PTS-STARTPTS[vout]"
    )

    # 👉 音频裁剪
    filter_parts.append(f"[{len(paths_group)}:a]atrim=0:{audio_dur},asetpts=PTS-STARTPTS[aout]")

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
        desc=f"tts seg {seg_idx+1}",
    )

    return seg_out

