from __future__ import annotations

import logging
import os
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

# 轮播全列表时：每条素材按整段 clip 展开，不受当前 TTS 段的 clip_trims / duration 影响
_PLAYLIST_MATERIALIZE_SEG = SimpleNamespace(
    clip_trims=None,
    clip_start_sec=None,
    duration_sec=None,
)

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

from .render_opts import (
    build_extra_video_filters,
    build_intermediate_codec_args,
    build_render_codec_args,
    force_video_reencode,
    sanitize_no_stream_copy,
)

logger = logging.getLogger(__name__)


def _materialize_decode_hwaccel_prefix() -> List[str]:
    """
    解码阶段可选硬件加速（帧仍会交给 CPU 做 trim 等滤镜）。

    默认关闭：在部分 Windows 环境下「-hwaccel auto + filter_complex + 多路输出」可能长时间无进度（卡死），
    与软解相比属于不稳定增益。

    环境变量 SMARTCLIP_MATERIALIZE_DECODE_HWACCEL：
      未设置 / 空 → 不加 -hwaccel（推荐）
      auto → -hwaccel auto（需自担风险）
      cuda / d3d11va / qsv 等 → -hwaccel <名称>
      0 / false / off / none → 关闭
    """
    raw = (os.environ.get("SMARTCLIP_MATERIALIZE_DECODE_HWACCEL") or "").strip().lower()
    if raw in ("0", "false", "no", "off", "none", ""):
        return []
    if raw == "auto":
        return ["-hwaccel", "auto"]
    return ["-hwaccel", raw]


def _make_even(x: int, *, min_v: int = 2) -> int:
    x = int(x)
    if x < min_v:
        x = min_v
    return x if (x % 2 == 0) else (x - 1)


def _opts_clip_scale_wh(render_opts: Optional[Dict[str, str]]) -> Tuple[int, int]:
    opts = render_opts or {}
    try:
        sw = int(float(str(opts.get("clip_scale_width") or "").strip() or 0))
    except Exception:
        sw = 0
    try:
        sh = int(float(str(opts.get("clip_scale_height") or "").strip() or 0))
    except Exception:
        sh = 0
    return sw, sh


def _explicit_norm_target_wh(scale_w: int, scale_h: int, src_w: int, src_h: int) -> Tuple[int, int]:
    """与 build_extra_video_filters 中单边 -2 语义一致，输出偶数宽高。"""
    src_w = max(1, int(src_w))
    src_h = max(1, int(src_h))
    if scale_w > 0 and scale_h > 0:
        return _make_even(scale_w), _make_even(scale_h)
    if scale_w > 0:
        th = int(round(src_h * scale_w / src_w))
        return _make_even(scale_w), _make_even(th)
    if scale_h > 0:
        tw = int(round(src_w * scale_h / src_h))
        return _make_even(tw), _make_even(scale_h)
    return src_w, src_h


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


def _trim_list_from_seg(seg, clip_ids: List[str]) -> Optional[List[Tuple[float, float]]]:
    """
    clip_trims 存在时，返回与 clip_ids **同长度/同顺序**的 (start_sec, span_sec) 列表。

    不能用 dict[clip_id]->(...)：会丢顺序/丢重复（同一 clip_id 多段不同入点/时长）。
    若 clip_trims 不存在或长度与 clip_ids 不一致，返回 None 由上层走回退逻辑。
    """
    parts = getattr(seg, "clip_trims", None) or []
    if not parts:
        return None

    out: List[Tuple[float, float]] = []
    for p in parts:
        try:
            st = float(getattr(p, "clip_start_sec", None) or 0.0)
            sp = float(getattr(p, "duration_sec", None) or 0.0)
        except Exception:
            st, sp = 0.0, 0.0
        out.append((max(0.0, st), max(0.0, sp)))

    # clip_ids 在 clip_trims 分支下应与 parts 一一对应；若不一致说明上游数据不一致，返回 None 交由上层处理。
    if len(out) != len(clip_ids):
        return None
    return out


def _force_no_bframes(codec_args: List[str]) -> List[str]:
    """关闭 B 帧（-bf 0）：段成品后续走 concat copy 拼接，无 B 帧保证段间无跨段参考。

    移除已有 -bf 参数，统一设为 0；不存在则追加。
    """
    out = list(codec_args)
    i = 0
    while i < len(out):
        if out[i] == "-bf":
            if i + 1 < len(out):
                out[i + 1] = "0"
            else:
                out.append("0")
            return out
        i += 1
    out.extend(["-bf", "0"])
    return out


def _force_audio_copy(codec_args: List[str]) -> List[str]:
    """
    仅用于无音频滤镜的中间预处理：将音频设置为 stream copy，避免重复 AAC 编码。
    """
    out = list(codec_args)
    try:
        a_idx = out.index("-c:a")
    except ValueError:
        out += ["-c:a", "copy"]
    else:
        if a_idx + 1 >= len(out):
            out += ["copy"]
        else:
            out[a_idx + 1] = "copy"
    # 音频 copy 场景移除显式码率参数，避免与 copy 冲突/冗余。
    cleaned: List[str] = []
    i = 0
    while i < len(out):
        if out[i] == "-b:a":
            i += 2
            continue
        cleaned.append(out[i])
        i += 1
    return cleaned


def _codec_args_for_filtered_audio(
    codec_args: List[str],
    render_opts: Optional[Dict[str, str]],
) -> List[str]:
    """
    filter_complex 中对音轨做了 atrim 等处理时，输出并非「原始 packet」，不能使用 -c:a copy。
    （否则会报：Filtering and streamcopy cannot be used together.）
    """
    opts = render_opts or {}
    try:
        br = max(32, int(float(str(opts.get("clip_audio_bitrate_kbps") or "128").strip() or 128)))
    except Exception:
        br = 128
    fallback_acodec = (opts.get("clip_acodec") or "aac").strip().lower()
    if fallback_acodec == "copy":
        fallback_acodec = "aac"

    out = list(codec_args)
    try:
        ai = out.index("-c:a")
    except ValueError:
        return out + ["-c:a", fallback_acodec, "-b:a", f"{br}k"]

    cur = (out[ai + 1] or "").strip().lower() if ai + 1 < len(out) else ""
    if cur != "copy":
        return out

    out[ai + 1] = fallback_acodec
    cleaned: List[str] = []
    i = 0
    while i < len(out):
        if out[i] == "-b:a":
            i += 2
            continue
        cleaned.append(out[i])
        i += 1
    cleaned.extend(["-b:a", f"{br}k"])
    return cleaned


def _is_nvenc(codec_args: List[str]) -> bool:
    try:
        v_idx = codec_args.index("-c:v")
    except ValueError:
        return False
    if v_idx + 1 >= len(codec_args):
        return False
    return (codec_args[v_idx + 1] or "").strip().lower() in ("h264_nvenc", "hevc_nvenc")


def _materialize_opts_use_nvenc(trim_opts: Dict[str, str], seg_codec_args: List[str]) -> bool:
    """是否使用 NVENC：优先看 clip_vcodec（与成片配置一致），再兜底解析已生成的 argv。"""
    vc = (trim_opts.get("clip_vcodec") or "").strip().lower()
    if vc in ("h264_nvenc", "hevc_nvenc"):
        return True
    if vc == "":
        # build_render_codec_args 默认 libx264；若 opts 未带 clip_vcodec 仍以 argv 为准
        return _is_nvenc(seg_codec_args)
    return False


def _predict_trim_kind(
    *,
    seg_filter_parts: List[str],
    kfs: List[float],
    src_total: float,
    start: float,
    span: float,
) -> str:
    """
    copy_def / copy_try / encode — 与 materialize 里 stream copy 分支的判定一致（encode 可走批量单解码）。
    """
    end = start + span
    can_try_copy = not seg_filter_parts
    if not can_try_copy:
        return "encode"
    start_aligned = start <= 0.01 or _is_near_keyframe(start, kfs)
    end_aligned = (src_total - end) <= 0.05 or _is_near_keyframe(end, kfs)
    if start_aligned and end_aligned:
        return "copy_def"
    near_enough = _nearest_keyframe_distance(start, kfs) <= 0.20 and _nearest_keyframe_distance(end, kfs) <= 0.20
    if near_enough:
        return "copy_try"
    return "encode"


def _materialize_one_encode(
    *,
    src_path: str,
    start: float,
    span: float,
    need_trim: bool,
    trim_tmp: str,
    cid: str,
    seg_idx: int,
    tmp_name: str,
    seg_filter_parts: List[str],
    seg_vf_args: List[str],
    tw: int,
    th: int,
    render_opts: Optional[Dict[str, str]],
    intermediate: bool = False,
) -> None:
    trim_opts = sanitize_no_stream_copy(dict(render_opts or {}))
    # 中间产物（force_materialize，必被后续重编码）用最快 preset；最终质量由后续编码保证。
    seg_codec_args = (
        build_intermediate_codec_args(trim_opts)
        if intermediate
        else build_render_codec_args(trim_opts)
    )
    if seg_filter_parts:
        seg_codec_args = force_video_reencode(seg_codec_args, render_opts=trim_opts)
    seg_codec_args = _force_audio_copy(seg_codec_args)
    logger.info(f"FFmpeg pre{tmp_name}(encode) 剪辑片段 {cid} 第 {(int(seg_idx) + 1)} 段 参数: {seg_codec_args}")
    if seg_filter_parts and _is_nvenc(seg_codec_args):
        cuda_filters = []
        for f in seg_filter_parts:
            if (f or "").strip().lower().startswith("scale="):
                cuda_filters.append(f"scale_cuda={tw}:{th}")
            else:
                cuda_filters.append(f)
        cuda_vf_args = ["-vf", ",".join(cuda_filters)]
        try:
            run_ffmpeg(
                [
                    "-hwaccel",
                    "cuda",
                    "-hwaccel_output_format",
                    "cuda",
                    "-i",
                    src_path,
                    *([] if not need_trim else ["-ss", f"{start:.3f}", "-t", f"{span:.3f}"]),
                    *cuda_vf_args,
                    *seg_codec_args,
                    "-movflags",
                    "+faststart",
                    trim_tmp,
                ],
                desc=f"pre{tmp_name}(encode,cuda) clip {cid} seg{(int(seg_idx) + 1)}",
            )
        except Exception:
            run_ffmpeg(
                [
                    *_materialize_decode_hwaccel_prefix(),
                    "-i",
                    src_path,
                    *([] if not need_trim else ["-ss", f"{start:.3f}", "-t", f"{span:.3f}"]),
                    *seg_vf_args,
                    *seg_codec_args,
                    "-movflags",
                    "+faststart",
                    trim_tmp,
                ],
                desc=f"pre{tmp_name}(encode) clip {cid} seg{(int(seg_idx) + 1)}",
            )
    else:
        run_ffmpeg(
            [
                *_materialize_decode_hwaccel_prefix(),
                "-i",
                src_path,
                *([] if not need_trim else ["-ss", f"{start:.3f}", "-t", f"{span:.3f}"]),
                *seg_vf_args,
                *seg_codec_args,
                "-movflags",
                "+faststart",
                trim_tmp,
            ],
            desc=f"pre{tmp_name}(encode) clip {cid} seg{(int(seg_idx) + 1)}",
        )
    logger.info(f"FFmpeg pre{tmp_name}(encode) 剪辑片段 {cid} 第 {(int(seg_idx) + 1)} 段 完成")


def _materialize_encode_batch_trim_filter(
    *,
    src_path: str,
    items: List[Dict[str, Any]],
    seek_base: float,
    input_read_sec: float,
    seg_filter_parts: List[str],
    seg_codec_args: List[str],
    seg_idx: int,
) -> None:
    """
    同一源文件、同一套视频滤镜、多段需重编码：一次解码 + trim/atrim 多输出。
    items 每项含: start, span, trim_tmp, cid
    """
    n = len(items)
    v_split = f"[0:v]split={n}" + "".join(f"[vin{i}]" for i in range(n))
    a_split = f"[0:a]asplit={n}" + "".join(f"[ain{i}]" for i in range(n))
    parts = [v_split, a_split]
    vf_tail = ""
    if seg_filter_parts:
        vf_tail = "," + ",".join(seg_filter_parts)
    for i, it in enumerate(items):
        start = float(it["start"])
        span = float(it["span"])
        end = start + span
        rs = max(0.0, start - seek_base)
        re = max(rs + 0.05, end - seek_base)
        parts.append(f"[vin{i}]trim=start={rs:.3f}:end={re:.3f},setpts=PTS-STARTPTS{vf_tail}[vout{i}]")
        parts.append(f"[ain{i}]atrim=start={rs:.3f}:end={re:.3f},asetpts=PTS-STARTPTS[aout{i}]")
    fc = ";".join(parts)
    cmd: List[str] = [
        *_materialize_decode_hwaccel_prefix(),
        "-ss",
        f"{seek_base:.3f}",
        "-i",
        src_path,
        "-t",
        f"{input_read_sec:.3f}",
        "-filter_complex",
        fc,
    ]
    for i, it in enumerate(items):
        cmd += [
            "-map",
            f"[vout{i}]",
            "-map",
            f"[aout{i}]",
            *seg_codec_args,
            "-avoid_negative_ts",
            "make_zero",
            "-movflags",
            "+faststart",
            str(it["trim_tmp"]),
        ]
    cid_brief = "+".join(str(x.get("cid") or "")[:8] for x in items)
    run_ffmpeg(cmd, desc=f"pretrim(encode,batch n={n}) seg{(int(seg_idx) + 1)} clips={cid_brief}")
    logger.info("FFmpeg pretrim(encode,batch) 完成 seg=%s 输出=%d 路", int(seg_idx) + 1, n)


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
        # 中间材质化归一化：bicubic 为 FFmpeg 默认缩放，与 lanczos 对实拍素材肉眼无差且更快；
        # 最终成片缩放（render_opts.build_extra_video_filters）仍保留 lanczos。
        norm_vf = (
            [f"scale={tw}:{th}:flags=bicubic", "setsar=1"] if need_norm else []
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
                    intermediate=force_materialize,
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
        # force_materialize 的中间产物必被后续重编码：用最快 preset，仅提速不改画质目标。
        seg_codec_args0 = (
            build_intermediate_codec_args(trim_opts)
            if force_materialize
            else build_render_codec_args(trim_opts)
        )
        sfp0 = list(r["seg_filter_parts"])
        if sfp0:
            seg_codec_args0 = force_video_reencode(seg_codec_args0, render_opts=trim_opts)
        nvenc = _materialize_opts_use_nvenc(trim_opts, seg_codec_args0)

        def _env_flag(name: str) -> Optional[bool]:
            """三态解析：1/true/yes → True；0/false/no → False；空 → None（用默认）。"""
            raw = (os.environ.get(name) or "").strip().lower()
            if raw in ("1", "true", "yes", "on"):
                return True
            if raw in ("0", "false", "no", "off"):
                return False
            return None

        # 单进程多路 NVENC（filter_complex 多 -map）在部分环境极慢或假死。
        nvenc_batch_ok = _env_flag("SMARTCLIP_ALLOW_NVENC_ENCODE_BATCH")
        # 软编（libx264/libx265 等）批量已验证稳定，默认开启；可设 0 关闭。
        # NVENC 多路仍保守：默认关闭，仅当 SMARTCLIP_ALLOW_NVENC_ENCODE_BATCH=1 时才启用。
        soft_batch = _env_flag("SMARTCLIP_MATERIALIZE_ENCODE_BATCH")
        if nvenc:
            allow_nvenc_batch = bool(nvenc_batch_ok) if nvenc_batch_ok is not None else False
            allow_batch = allow_nvenc_batch and len(batch) >= 2
        else:
            allow_batch = (soft_batch if soft_batch is not None else True) and len(batch) >= 2
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
                intermediate=force_materialize,
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


def _vf_trim_to_duration(dur: float) -> str:
    """FFmpeg trim 滤镜须用 start/end，``trim=0:3`` 无效会导致画面全长溢出。"""
    d = max(0.05, float(dur))
    return f"trim=start=0:end={d:.3f},setpts=PTS-STARTPTS"


def _af_trim_to_duration(dur: float) -> str:
    d = max(0.05, float(dur))
    return f"atrim=start=0:end={d:.3f},asetpts=PTS-STARTPTS"


def _cap_segment_to_duration(
    seg_path: str,
    cap_sec: float,
    tmp: str,
    label: str,
    codec_args: List[str],
) -> str:
    """容器时长超出配音上限时二次裁切（兜底，防止视频轨长于音轨）。

    优先 stream copy（-c copy -t）：仅截断容器时长，不重编码、画质位级不变；
    仅当 copy 失败（容器不支持精确截断等罕见情况）才回退到按 codec_args 重编码。
    """
    probed = float(probe_duration(seg_path, log_on_failure=True) or 0.0)
    cap = max(0.05, float(cap_sec))
    if probed <= cap + 0.08:
        return seg_path
    capped = os.path.join(tmp, f"{label}_cap.mp4")
    logger.warning(
        "段 %s 容器时长 %.3fs > 配音上限 %.3fs，二次裁切",
        label,
        probed,
        cap,
    )
    try:
        run_ffmpeg(
            [
                "-i",
                seg_path,
                "-t",
                f"{cap:.3f}",
                "-c",
                "copy",
                "-avoid_negative_ts",
                "make_zero",
                "-movflags",
                "+faststart",
                capped,
            ],
            desc=f"cap segment {label} (copy)",
        )
        return capped
    except Exception as e:
        logger.warning("段 %s copy 裁切失败，回退重编码: %s", label, e)
    run_ffmpeg(
        [
            "-i",
            seg_path,
            "-t",
            f"{cap:.3f}",
            *codec_args,
            "-movflags",
            "+faststart",
            capped,
        ],
        desc=f"cap segment {label}",
    )
    return capped


def _expand_paths_playlist_cycle(
    path_durs: List[Tuple[str, float]],
    *,
    audio_dur: float,
    max_pieces: int = 800,
) -> Tuple[List[str], float]:
    """按完整播放列表顺序轮播：每一轮播完列表中全部素材后，再进入下一轮。"""
    if not path_durs:
        return [], 0.0
    out: List[str] = []
    acc = 0.0
    eps = 0.02
    rounds = 0
    while acc < audio_dur - eps and len(out) < max_pieces and rounds < 120:
        for p, d in path_durs:
            out.append(p)
            acc += max(float(d), 0.05)
            if acc >= audio_dur - eps or len(out) >= max_pieces:
                break
        rounds += 1
    return out, acc


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
    materialize_cache: Optional[Dict[str, Tuple[str, float]]] = None,
    from_source_video: bool = True,
    tts_align: Optional[TtsVideoAlignConfig] = None,
    clip_map: Optional[dict] = None,
) -> str:
    from fastapi import HTTPException

    def _force_audio_reencode(codec_args: List[str], *, acodec: str = "aac", abitrate_kbps: int = 128) -> List[str]:
        """
        filter_complex 输出的音频不能 stream copy（-c:a copy）。
        这里强制将音频编码器改为可用的实际编码器（默认 aac）。
        """
        out = list(codec_args)
        try:
            a_idx = out.index("-c:a")
        except ValueError:
            out += ["-c:a", acodec, "-b:a", f"{abitrate_kbps}k"]
            return out
        if a_idx + 1 >= len(out):
            out += [acodec]
        else:
            out[a_idx + 1] = acodec
        # 确保有 -b:a（若后续已存在则不重复添加）
        if "-b:a" not in out:
            out += ["-b:a", f"{abitrate_kbps}k"]
        return out

    name = str(getattr(seg, "tts_filename", "") or "").strip()
    if not name:
        raise HTTPException(400, f"TTS 文件名为空: seg_{(int(seg_idx) + 1)}，请先合成配音")

    tts_path = os.path.join(tts_audio_dir, os.path.basename(name))
    if not os.path.isfile(tts_path):
        raise HTTPException(400, f"TTS 音频不存在: seg_{(int(seg_idx) + 1)}")

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
        # TTS 模式后续用 concat demuxer 拼接，必须确保每段输入规格尽量一致，否则容易生成“容器时长很长但后半段读不到帧”的坏文件。
        force_materialize=True,
        from_source_video=from_source_video,
    )

    if not paths_group:
        raise HTTPException(400, f"分段 seg_{(int(seg_idx) + 1)} 没有可用视频素材")

    audio_dur = float(_tts_file_duration(tts_path) or 0.0)
    if audio_dur <= 0:
        raise HTTPException(400, f"TTS 音频无效: seg_{(int(seg_idx) + 1)}")

    # 如果视频总时长短于配音时长：重复追加第一个素材直到覆盖，然后再 trim 精准裁剪。
    # 这样实现“复制拼接”，不需要 loop/tpad。
    # 这里必须“强保证”视频 >= 音频，否则 ffmpeg 会以 shortest 截断音频导致字幕后半段错位。
    # 早期实现按首段时长估算可能因 probe 失败而不补足；这里改为按“整组素材”重复补齐，更稳。
    base_video_dur = float(source_total_after or 0.0)
    if base_video_dur <= 0.05:
        # 兜底：逐个 probe（可能较慢，但尽量正确）
        durs = [float(probe_duration(p) or 0.0) for p in paths_group]
        base_video_dur = sum(max(0.0, d) for d in durs)

    if base_video_dur <= 0.05:
        raise HTTPException(400, f"分段 seg_{(int(seg_idx) + 1)} 视频时长无效，无法对齐 TTS")

    if tts_align is None:
        policy = "loop_video_to_cover"
        cfg = TtsVideoAlignConfig()
    else:
        cfg = tts_align
        policy = str(cfg.policy or "loop_video_to_cover")
    eps = 0.02
    video_shorter = base_video_dur + eps < audio_dur

    need_pad_sec = 0.0
    paths_group = list(paths_group)

    if video_shorter and policy == "loop_video_to_cover":
        path_durs: List[Tuple[str, float]] = []
        for p in paths_group:
            d = float(probe_duration(p, log_on_failure=True) or 0.0)
            path_durs.append((p, d if d > 0.05 else 0.5))
        paths_group, covered = _expand_paths_playlist_cycle(path_durs, audio_dur=audio_dur)
        need_pad_sec = max(0.0, audio_dur - covered)
        logger.info(
            "seg_%d loop_video_to_cover: group=%d clips, pieces=%d, covered=%.2fs audio=%.2fs",
            int(seg_idx) + 1,
            len(path_durs),
            len(paths_group),
            covered,
            audio_dur,
        )
    elif video_shorter and policy == "loop_playlist_to_cover":
        playlist_ids: List[str] = []
        if tts_align is not None:
            playlist_ids = list(getattr(tts_align, "playlist_clip_ids", None) or [])
        if not playlist_ids:
            playlist_ids = list(clip_ids)

        pl_ids: List[str] = []
        pl_infos: List[dict] = []
        if clip_map:
            for cid in playlist_ids:
                info = clip_map.get(cid)
                if info and os.path.isfile(info.get("path") or ""):
                    pl_ids.append(cid)
                    pl_infos.append(info)
        else:
            by_cid = {clip_ids[i]: infos[i] for i in range(min(len(clip_ids), len(infos)))}
            for cid in playlist_ids:
                if cid in by_cid:
                    pl_ids.append(cid)
                    pl_infos.append(by_cid[cid])

        if not pl_infos:
            pl_ids = list(clip_ids)
            pl_infos = list(infos)

        pl_paths, _pl_total = materialize_clip_paths_for_group(
            seg=_PLAYLIST_MATERIALIZE_SEG,
            clip_ids=pl_ids,
            infos=pl_infos,
            tmp=tmp,
            seg_idx=int(seg_idx) + 50000,
            render_opts=render_opts,
            keyframe_cache=keyframe_cache,
            materialize_cache=materialize_cache,
            force_materialize=True,
            from_source_video=from_source_video,
        )
        path_durs: List[Tuple[str, float]] = []
        for p in pl_paths:
            d = float(probe_duration(p, log_on_failure=True) or 0.0)
            path_durs.append((p, d if d > 0.05 else 0.5))
        if not path_durs:
            path_durs = [(p, float(probe_duration(p) or 0.5)) for p in paths_group]
        paths_group, covered = _expand_paths_playlist_cycle(path_durs, audio_dur=audio_dur)
        need_pad_sec = max(0.0, audio_dur - covered)
        logger.info(
            "seg_%d loop_playlist: playlist=%d clips, pieces=%d, covered=%.2fs audio=%.2fs",
            int(seg_idx) + 1,
            len(path_durs),
            len(paths_group),
            covered,
            audio_dur,
        )
    elif video_shorter and policy in ("freeze_last_frame", "preserve_video_duration"):
        need_pad_sec = max(0.0, audio_dur - base_video_dur)
    elif not video_shorter and policy != "preserve_video_duration":
        need_pad_sec = max(0.0, audio_dur - base_video_dur)

    # concat 要求所有输入视频参数一致（分辨率/SAR 等），否则会报
    # "Input link parameters ... do not match ..."。
    seg_codec_args = force_video_reencode(build_render_codec_args(render_opts), render_opts=render_opts)
    seg_codec_args = _force_audio_reencode(seg_codec_args, acodec="aac", abitrate_kbps=128)
    # 关闭 B 帧：TTS 段成品后续走 concat copy 拼接，无 B 帧可保证段间无跨段参考，
    # 配合统一画布/参数实现安全 copy（避免之前 concat copy 卡死的三次教训）。
    seg_codec_args = _force_no_bframes(seg_codec_args)

    concat_list = os.path.join(tmp, f"seg_{seg_idx:03d}_vconcat.txt")
    write_concat_list(paths_group, concat_list)

    use_stretch_fc = (
        tts_align is not None
        and policy in ("stretch_audio", "stretch_video")
        and abs(audio_dur - base_video_dur) > eps
    )

    def _run_stretch_fc(*, output_dur: float, v_filters: str, a_filters: str) -> None:
        fc = f"[0:v]{v_filters}[vout];[1:a]{a_filters}[aout]"
        logger.info(
            "FFmpeg tts(seg stretch_fc) 段#%s policy=%s output_dur=%.3f fc=%s",
            int(seg_idx) + 1,
            policy,
            output_dur,
            fc,
        )
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
                "-i",
                tts_path,
                "-filter_complex",
                fc,
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                "-t",
                f"{output_dur:.3f}",
                *seg_codec_args,
                "-movflags",
                "+faststart",
                seg_out,
            ],
            desc=f"tts seg {(int(seg_idx) + 1)} (stretch_fc)",
        )

    try:
        if use_stretch_fc:
            if policy == "stretch_audio":
                atempo_eff, out_audio = resolve_stretch_audio_atempo(
                    tts_sec=audio_dur, video_sec=base_video_dur, cfg=cfg
                )
                out_dur = max(base_video_dur, out_audio)
                a_chain = build_atempo_filter_chain(atempo_eff)
                v_body = "setpts=PTS-STARTPTS"
                if base_video_dur + eps < out_audio:
                    v_body += f",tpad=stop_mode=clone:stop_duration={out_audio - base_video_dur:.3f}"
                elif base_video_dur > out_dur + eps:
                    v_body += f",{_vf_trim_to_duration(out_dur)}"
                v_body += ",setsar=1"
                a_body = f"{a_chain},asetpts=PTS-STARTPTS"
                _run_stretch_fc(output_dur=out_dur, v_filters=v_body, a_filters=a_body)
            else:  # stretch_video
                fac, out_v = resolve_stretch_video_pts_factor(
                    tts_sec=audio_dur, video_sec=base_video_dur, cfg=cfg
                )
                v_body = f"setpts=PTS-STARTPTS,setpts=PTS*{fac:.6f}"
                if audio_dur + eps < out_v:
                    v_body += f",{_vf_trim_to_duration(audio_dur)}"
                elif audio_dur > out_v + eps:
                    v_body += f",tpad=stop_mode=clone:stop_duration={audio_dur - out_v:.3f}"
                v_body += ",setsar=1"
                a_body = "asetpts=PTS-STARTPTS"
                _run_stretch_fc(output_dur=audio_dur, v_filters=v_body, a_filters=a_body)
        elif policy == "preserve_video_duration" and audio_dur + eps < base_video_dur:
            pad_sec = max(0.0, base_video_dur - audio_dur)
            logger.info(
                "FFmpeg tts(seg preserve_video) 段#%s 画面=%.2fs 配音=%.2fs 补静音=%.2fs",
                int(seg_idx) + 1,
                base_video_dur,
                audio_dur,
                pad_sec,
            )
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
                    "-i",
                    tts_path,
                    "-filter_complex",
                    f"[0:v]setpts=PTS-STARTPTS,setsar=1[v];[1:a]apad=pad_dur={pad_sec:.3f}[a]",
                    "-map",
                    "[v]",
                    "-map",
                    "[a]",
                    "-t",
                    f"{base_video_dur:.3f}",
                    *seg_codec_args,
                    "-movflags",
                    "+faststart",
                    seg_out,
                ],
                desc=f"tts seg {(int(seg_idx) + 1)} (preserve_video_duration)",
            )
        else:
            out_dur = audio_dur
            if policy == "preserve_video_duration":
                out_dur = max(audio_dur, base_video_dur)
            # 成片以配音（原声切片/TTS）为硬上限：画面只能在 [0, out_dur] 内，禁止溢出段落音轨。
            v_parts: List[str] = []
            if need_pad_sec > 0.02:
                v_parts.append(f"tpad=stop_mode=clone:stop_duration={need_pad_sec:.3f}")
            if policy != "preserve_video_duration":
                v_parts.append(_vf_trim_to_duration(out_dur))
            else:
                v_parts.append("setpts=PTS-STARTPTS")
            v_parts.append("setsar=1")
            v_chain = ",".join(v_parts)
            if policy == "preserve_video_duration" and out_dur > audio_dur + eps:
                pad_a = out_dur - audio_dur
                a_chain = f"apad=pad_dur={pad_a:.3f},{_af_trim_to_duration(out_dur)}"
            else:
                a_chain = _af_trim_to_duration(min(audio_dur, out_dur))
            logger.info(
                "FFmpeg tts(seg concat+trim) 段#%s out_dur=%.3f audio=%.3f base_video=%.3f policy=%s",
                int(seg_idx) + 1,
                out_dur,
                audio_dur,
                base_video_dur,
                policy,
            )
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
                    "-i",
                    tts_path,
                    "-filter_complex",
                    f"[0:v]{v_chain}[vout];[1:a]{a_chain}[aout]",
                    "-map",
                    "[vout]",
                    "-map",
                    "[aout]",
                    "-shortest",
                    "-t",
                    f"{out_dur:.3f}",
                    *seg_codec_args,
                    "-movflags",
                    "+faststart",
                    seg_out,
                ],
                desc=f"tts seg {(int(seg_idx) + 1)} (concat+trim)",
            )
    except Exception:
        # fallback：仍走 filter_complex concat，但不再做多路 scale/pad（尺寸/SAR 已在 materialize 统一）
        cmd = []
        for p in paths_group:
            cmd += ["-i", p]
        cmd += ["-i", tts_path]

        filter_parts = []
        concat_inputs = []
        for i in range(len(paths_group)):
            filter_parts.append(f"[{i}:v]setsar=1,setpts=PTS-STARTPTS[v{i}]")
            concat_inputs.append(f"[v{i}]")
        filter_parts.append(f"{''.join(concat_inputs)}concat=n={len(paths_group)}:v=1:a=0[vcat]")
        filter_parts.append(f"[vcat]{_vf_trim_to_duration(audio_dur)},setsar=1[vout]")
        filter_parts.append(f"[{len(paths_group)}:a]{_af_trim_to_duration(audio_dur)}[aout]")
        filter_complex = ";".join(filter_parts)

        logger.info(f"FFmpeg tts(seg fallback filter_complex) 段#{(int(seg_idx) + 1)} 参数: {seg_codec_args}")
        run_ffmpeg(
            [
                *cmd,
                "-filter_complex",
                filter_complex,
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                "-shortest",
                "-t",
                f"{audio_dur:.3f}",
                *seg_codec_args,
                "-movflags",
                "+faststart",
                seg_out,
            ],
            desc=f"tts seg {(int(seg_idx) + 1)} (fallback filter_complex)",
        )

    logger.info(f"FFmpeg tts 剪辑片段 {(int(seg_idx) + 1)} 完成")

    cap_dur = audio_dur if policy != "preserve_video_duration" else max(audio_dur, base_video_dur)
    return _cap_segment_to_duration(
        seg_out,
        cap_dur,
        tmp,
        f"seg_{int(seg_idx):03d}",
        seg_codec_args,
    )

