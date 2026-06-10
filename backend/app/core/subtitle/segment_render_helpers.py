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
) -> None:
    trim_opts = sanitize_no_stream_copy(dict(render_opts or {}))
    seg_codec_args = build_render_codec_args(trim_opts)
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
    """容器时长超出配音上限时二次裁切（兜底，防止视频轨长于音轨）。"""
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

