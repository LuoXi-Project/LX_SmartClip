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

from app.core.subtitle.segment_render_helpers import (
    _PLAYLIST_MATERIALIZE_SEG,
    _materialize_decode_hwaccel_prefix,
    _materialize_encode_batch_trim_filter,
    _materialize_one_encode,
    _materialize_opts_use_nvenc,
    _predict_trim_kind,
    _trim_list_from_seg,
)

def materialize_clip_paths_for_group(
    *,
    seg,
    clip_ids: List[str],
    infos: List[dict],
    tmp: str,
    seg_idx: int,
    render_opts: Optional[Dict[str, str]],
    keyframe_cache: Optional[Dict[str, List[float]]] = None,
    materialize_cache: Optional[Dict[str, Tuple[str, float]]] = None,
    force_materialize: bool = False,
    from_source_video: bool = True,
) -> Tuple[List[str], float]:
    """
    按顺序处理 clip 组：必要时逐段 ffmpeg 裁剪，返回 concat 用的路径列表与总视频时长。

    from_source_video=True 且 clip_map 提供 src_video_path/src_start/src_end 时，
    在「切片文件时间轴」上解析出的入点会映射到整片素材上的绝对时间，从原片裁剪（成片画质不受预处理 clip 影响）。
    """
    trim_list = _trim_list_from_seg(seg, clip_ids)
    # clip_scale_* 全 0：以组内第一段素材分辨率为 concat 基准（不默认改 1080p）。
    # 任一 >0：按成片导出缩放统一到计算出的 tw×th；scale= 只在此处生效，避免与 extra 重复。
    scale_w, scale_h = _opts_clip_scale_wh(render_opts)
    extra_filters = build_extra_video_filters(render_opts)
    extra_filters = [f for f in extra_filters if not (f or "").strip().lower().startswith("scale=")]

    kf_cache = keyframe_cache if keyframe_cache is not None else {}
    mat_cache = materialize_cache if materialize_cache is not None else {}
    paths_out: List[str] = []
    total_dur = 0.0
    group_ref_wh: Optional[Tuple[int, int]] = None

    # 阶段 1：只计算参数与 trim 策略；阶段 2：合并「同源 + 需重编码」为单次解码多输出（trim/atrim + 滤镜）。
    max_encode_batch = 12
    rows: List[Dict[str, Any]] = []

    for j, (cid, info) in enumerate(zip(clip_ids, infos)):
        clip_disk_path = info["path"]
        clip_probe_total = float(probe_duration(clip_disk_path, log_on_failure=True) or 0.0)
        if clip_probe_total <= 0.05:
            clip_probe_total = float(info.get("dur") or 0.0)
        if clip_probe_total <= 0.05:
            clip_probe_total = 0.05

        if trim_list is not None:
            clip_rel_start, clip_rel_span = trim_list[j]
            if clip_rel_span <= 0.05:
                clip_rel_start, clip_rel_span = 0.0, clip_probe_total
            clip_rel_start = max(0.0, min(clip_rel_start, clip_probe_total - 0.05))
            clip_rel_span = min(max(0.05, clip_rel_span), max(0.05, clip_probe_total - clip_rel_start))
        else:
            rel_cs = getattr(seg, "clip_start_sec", None)
            try:
                clip_rel_start = float(rel_cs) if rel_cs is not None else 0.0
            except Exception:
                clip_rel_start = 0.0
            clip_rel_start = max(0.0, min(clip_rel_start, clip_probe_total - 0.05))
            dur_want = resolve_desired_dur(seg)
            if dur_want is not None and float(dur_want) > 0:
                clip_rel_span = min(float(dur_want), max(0.05, clip_probe_total - clip_rel_start))
            else:
                clip_rel_span = max(0.05, clip_probe_total - clip_rel_start)

        src_video = str(info.get("src_video_path") or "").strip()
        use_src = bool(from_source_video and src_video and os.path.isfile(src_video))
        if use_src:
            src_path = src_video
            src_total = float(probe_duration(src_path, log_on_failure=True) or 0.0)
            if src_total <= 0.05:
                use_src = False

        if use_src:
            clip_abs_start = float(info.get("src_start") or 0.0)
            clip_abs_end = float(info.get("src_end") or 0.0)
            if clip_abs_end <= clip_abs_start + 0.02:
                clip_abs_end = clip_abs_start + clip_probe_total
            abs_start = clip_abs_start + clip_rel_start
            abs_start = max(0.0, min(abs_start, src_total - 0.05, clip_abs_end - 0.05))
            max_span = min(
                clip_rel_span,
                max(0.05, clip_abs_end - abs_start),
                max(0.05, src_total - abs_start),
            )
            start, span = abs_start, max(0.05, max_span)
        else:
            src_path = clip_disk_path
            src_total = clip_probe_total
            start, span = clip_rel_start, clip_rel_span

        need_trim = start > 0.001 or (span + 0.02) < (src_total - start - 0.001)
        w, h = probe_video_dimensions(src_path, default=(1920, 1080), logger_=logger)
        if scale_w <= 0 and scale_h <= 0:
            if group_ref_wh is None:
                group_ref_wh = (w, h)
            tw, th = group_ref_wh
        else:
            tw, th = _explicit_norm_target_wh(scale_w, scale_h, w, h)
        need_norm = (w, h) != (tw, th)
        norm_vf = (
            [f"scale={tw}:{th}:flags=lanczos", "setsar=1"] if need_norm else []
        )
        visual_vf = build_segment_visual_filters(getattr(seg, "visual_effect", None))
        seg_filter_parts = [*norm_vf, *extra_filters, *visual_vf]
        seg_vf_args = ["-vf", ",".join(seg_filter_parts)] if seg_filter_parts else []

        if (not force_materialize) and (not need_trim) and (not need_norm):
            rows.append({"kind": "pass", "src_path": src_path, "piece_dur": src_total})
            continue

        tmp_name = "trim" if need_trim else "norm"
        vf_key = ",".join(seg_filter_parts)
        src_flag = "src1" if use_src else "src0"
        cache_key = f"{src_path}|{tmp_name}|{start:.3f}|{span:.3f}|vf={vf_key}|{src_flag}"
        cached = mat_cache.get(cache_key)
        if cached and os.path.isfile(cached[0]):
            piece_dur = cached[1] if cached[1] > 0.05 else (span if need_trim else src_total)
            rows.append({"kind": "cache", "path": cached[0], "piece_dur": float(piece_dur)})
            continue

        trim_tmp = os.path.join(tmp, f"seg_{seg_idx:03d}_p{j:02d}_{tmp_name}.mp4")
        end = start + span
        can_try_copy = not seg_filter_parts
        trim_kind = "encode"
        if can_try_copy:
            if src_path not in kf_cache:
                kf_cache[src_path] = probe_keyframes_times(src_path, logger_=logger)
            kfs = kf_cache.get(src_path) or []
            trim_kind = _predict_trim_kind(
                seg_filter_parts=seg_filter_parts,
                kfs=kfs,
                src_total=src_total,
                start=start,
                span=span,
            )

        rows.append(
            {
                "kind": "work",
                "trim_kind": trim_kind,
                "j": j,
                "cid": cid,
                "src_path": src_path,
                "use_src": use_src,
                "start": start,
                "span": span,
                "end": end,
                "need_trim": need_trim,
                "need_norm": need_norm,
                "tmp_name": tmp_name,
                "cache_key": cache_key,
                "trim_tmp": trim_tmp,
                "seg_filter_parts": list(seg_filter_parts),
                "seg_vf_args": list(seg_vf_args),
                "tw": tw,
                "th": th,
                "src_total": src_total,
            }
        )

    ri = 0
    while ri < len(rows):
        r = rows[ri]
        if r["kind"] == "pass":
            paths_out.append(str(r["src_path"]))
            total_dur += max(float(r["piece_dur"]), 0.05)
            ri += 1
            continue
        if r["kind"] == "cache":
            paths_out.append(str(r["path"]))
            total_dur += max(float(r["piece_dur"]), 0.05)
            ri += 1
            continue

        tk = str(r.get("trim_kind") or "encode")
        if tk == "copy_def":
            run_ffmpeg(
                [
                    "-ss",
                    f"{float(r['start']):.3f}",
                    "-t",
                    f"{float(r['span']):.3f}",
                    "-i",
                    str(r["src_path"]),
                    "-c",
                    "copy",
                    "-avoid_negative_ts",
                    "make_zero",
                    "-movflags",
                    "+faststart",
                    str(r["trim_tmp"]),
                ],
                desc=f"pretrim(copy) clip {r['cid']} seg{(int(seg_idx) + 1)}",
            )
            need_trim = bool(r["need_trim"])
            span = float(r["span"])
            src_total = float(r["src_total"])
            if need_trim:
                piece_dur = float(span)
            else:
                probed = float(probe_duration(str(r["trim_tmp"]), log_on_failure=True) or 0.0)
                piece_dur = probed if probed > 0.05 else src_total
            mat_cache[str(r["cache_key"])] = (str(r["trim_tmp"]), piece_dur)
            paths_out.append(str(r["trim_tmp"]))
            total_dur += max(piece_dur, 0.05)
            ri += 1
            continue

        if tk == "copy_try":
            did_copy = False
            try:
                run_ffmpeg(
                    [
                        "-ss",
                        f"{float(r['start']):.3f}",
                        "-t",
                        f"{float(r['span']):.3f}",
                        "-i",
                        str(r["src_path"]),
                        "-c",
                        "copy",
                        "-avoid_negative_ts",
                        "make_zero",
                        "-movflags",
                        "+faststart",
                        str(r["trim_tmp"]),
                    ],
                    desc=f"pretrim(try_copy) clip {r['cid']} seg{(int(seg_idx) + 1)}",
                )
                did_copy = True
            except Exception:
                did_copy = False
            if not did_copy:
                _materialize_one_encode(
                    src_path=str(r["src_path"]),
                    start=float(r["start"]),
                    span=float(r["span"]),
                    need_trim=bool(r["need_trim"]),
                    trim_tmp=str(r["trim_tmp"]),
                    cid=str(r["cid"]),
                    seg_idx=seg_idx,
                    tmp_name=str(r["tmp_name"]),
                    seg_filter_parts=list(r["seg_filter_parts"]),
                    seg_vf_args=list(r["seg_vf_args"]),
                    tw=int(r["tw"]),
                    th=int(r["th"]),
                    render_opts=render_opts,
                )
            need_trim = bool(r["need_trim"])
            span = float(r["span"])
            src_total = float(r["src_total"])
            if need_trim:
                piece_dur = float(span)
            else:
                probed = float(probe_duration(str(r["trim_tmp"]), log_on_failure=True) or 0.0)
                piece_dur = probed if probed > 0.05 else src_total
            mat_cache[str(r["cache_key"])] = (str(r["trim_tmp"]), piece_dur)
            paths_out.append(str(r["trim_tmp"]))
            total_dur += max(piece_dur, 0.05)
            ri += 1
            continue

        # encode：尝试与后续连续同源、同滤镜的 encode 行合并为一次进程
        batch: List[Dict[str, Any]] = [r]
        bi = ri + 1
        while bi < len(rows) and len(batch) < max_encode_batch:
            r2 = rows[bi]
            if str(r2.get("kind")) != "work" or str(r2.get("trim_kind")) != "encode":
                break
            if str(r2["src_path"]) != str(r["src_path"]):
                logger.info(
                    "pretrim(encode,batch) 合并结束：下一素材与当前批 src 不同（多为某 clip 仍用预处理文件而非整片）",
                )
                break
            if list(r2["seg_filter_parts"]) != list(r["seg_filter_parts"]):
                logger.info(
                    "pretrim(encode,batch) 合并结束：视频滤镜链与当前批不一致（分辨率/组内基准不一致等）",
                )
                break
            batch.append(r2)
            bi += 1

        trim_opts = sanitize_no_stream_copy(dict(render_opts or {}))
        seg_codec_args0 = build_render_codec_args(trim_opts)
        sfp0 = list(r["seg_filter_parts"])
        if sfp0:
            seg_codec_args0 = force_video_reencode(seg_codec_args0, render_opts=trim_opts)
        nvenc = _materialize_opts_use_nvenc(trim_opts, seg_codec_args0)
        # 单进程多路 NVENC（filter_complex 多 -map）在部分环境极慢或假死；默认改为逐段编码。
        # 若需实验批量可设 SMARTCLIP_ALLOW_NVENC_ENCODE_BATCH=1
        nvenc_batch_ok = (os.environ.get("SMARTCLIP_ALLOW_NVENC_ENCODE_BATCH") or "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        # 同源批量默认关闭：多路 filter 输出在 NVENC/弱机上极易变慢或假死；需要时再开启。
        # libx264 等：SMARTCLIP_MATERIALIZE_ENCODE_BATCH=1
        # NVENC 多路：另需 SMARTCLIP_ALLOW_NVENC_ENCODE_BATCH=1（不推荐）
        batch_opt_in = (os.environ.get("SMARTCLIP_MATERIALIZE_ENCODE_BATCH") or "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        allow_batch = batch_opt_in and len(batch) >= 2 and (not nvenc or nvenc_batch_ok)
        # 批量路径：音轨经 atrim，禁止 -c:a copy；逐段 encode 仍可用 copy（仅 -ss/-t + -vf）
        seg_codec_args_batch = _codec_args_for_filtered_audio(seg_codec_args0, trim_opts)

        if allow_batch:
            try:
                seek_base = max(0.0, min(float(x["start"]) for x in batch) - 0.5)
                read_end = max(float(x["start"]) + float(x["span"]) for x in batch)
                input_read_sec = max(0.5, read_end - seek_base + 0.25)
                items = [
                    {"start": float(x["start"]), "span": float(x["span"]), "trim_tmp": str(x["trim_tmp"]), "cid": str(x["cid"])}
                    for x in batch
                ]
                logger.info(
                    "FFmpeg pretrim(encode,batch) 段#%s 同源输出=%d 路 seek_base=%.3f read=%.3f",
                    int(seg_idx) + 1,
                    len(batch),
                    seek_base,
                    input_read_sec,
                )
                _materialize_encode_batch_trim_filter(
                    src_path=str(r["src_path"]),
                    items=items,
                    seek_base=seek_base,
                    input_read_sec=input_read_sec,
                    seg_filter_parts=sfp0,
                    seg_codec_args=seg_codec_args_batch,
                    seg_idx=seg_idx,
                )
                for x in batch:
                    need_trim = bool(x["need_trim"])
                    span = float(x["span"])
                    src_total = float(x["src_total"])
                    if need_trim:
                        piece_dur = float(span)
                    else:
                        probed = float(probe_duration(str(x["trim_tmp"]), log_on_failure=True) or 0.0)
                        piece_dur = probed if probed > 0.05 else src_total
                    mat_cache[str(x["cache_key"])] = (str(x["trim_tmp"]), piece_dur)
                    paths_out.append(str(x["trim_tmp"]))
                    total_dur += max(piece_dur, 0.05)
                ri = bi
                continue
            except Exception as ex:
                logger.warning("pretrim(encode,batch) 失败，回退逐段编码: %s", ex)

        for x in batch:
            _materialize_one_encode(
                src_path=str(x["src_path"]),
                start=float(x["start"]),
                span=float(x["span"]),
                need_trim=bool(x["need_trim"]),
                trim_tmp=str(x["trim_tmp"]),
                cid=str(x["cid"]),
                seg_idx=seg_idx,
                tmp_name=str(x["tmp_name"]),
                seg_filter_parts=list(x["seg_filter_parts"]),
                seg_vf_args=list(x["seg_vf_args"]),
                tw=int(x["tw"]),
                th=int(x["th"]),
                render_opts=render_opts,
            )
            need_trim = bool(x["need_trim"])
            span = float(x["span"])
            src_total = float(x["src_total"])
            if need_trim:
                piece_dur = float(span)
            else:
                probed = float(probe_duration(str(x["trim_tmp"]), log_on_failure=True) or 0.0)
                piece_dur = probed if probed > 0.05 else src_total
            mat_cache[str(x["cache_key"])] = (str(x["trim_tmp"]), piece_dur)
            paths_out.append(str(x["trim_tmp"]))
            total_dur += max(piece_dur, 0.05)
        ri = bi

    return paths_out, total_dur

