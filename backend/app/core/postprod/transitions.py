"""段间转场：xfade / acrossfade / micro-fade。"""
from __future__ import annotations

import logging
import os
from typing import List, Literal, Optional, Sequence

from app.models.production import ProductionProfile, TransitionPolicy
from app.utils.ffprobe_utils import probe_audio_sample_rate, probe_duration, probe_video_dimensions
from app.utils.ffmpeg_utils import run_ffmpeg

logger = logging.getLogger(__name__)

SegmentTransitionKind = Literal["hard_cut", "cross_dissolve", "fade_in", "fade_out"]


def _effective_policy(profile: ProductionProfile) -> TransitionPolicy:
    tp = profile.transition
    pol = tp.policy
    if pol == "auto":
        if profile.preset_id in ("ecommerce", "knowledge", "cinematic"):
            pol = "soft"
        else:
            pol = "hard_cut"
    tp = tp.model_copy(update={"policy": pol})
    return tp


def resolve_segment_transitions(
    n_segments: int,
    profile: ProductionProfile,
    plan_transitions: Optional[Sequence[Optional[SegmentTransitionKind]]] = None,
) -> List[SegmentTransitionKind]:
    """
    返回长度 n 的列表：第 i 项表示进入第 i 段的转场（i=0 可为 fade_in）。
    """
    if n_segments <= 0:
        return []
    tp = _effective_policy(profile)
    out: List[SegmentTransitionKind] = ["hard_cut"] * n_segments
    plan_transitions = list(plan_transitions or [])
    for i in range(n_segments):
        raw = plan_transitions[i] if i < len(plan_transitions) else None
        if raw in ("cross_dissolve", "fade_in", "fade_out", "hard_cut"):
            out[i] = raw  # type: ignore[assignment]
    # profile 默认：soft → 段间 dissolve（首段 fade_in 若 bookend 开启）
    if tp.policy == "soft":
        for i in range(1, n_segments):
            if out[i] == "hard_cut":
                out[i] = "cross_dissolve"
        if tp.bookend_fade_in_sec > 0 and out[0] == "hard_cut":
            out[0] = "fade_in"
        if tp.bookend_fade_out_sec > 0 and n_segments > 0:
            out[-1] = "fade_out" if out[-1] == "hard_cut" else out[-1]
    return out


def _seg_durations(paths: Sequence[str]) -> List[float]:
    ds: List[float] = []
    for p in paths:
        d = float(probe_duration(p) or 0.0)
        if d <= 0:
            raise RuntimeError(f"无法探测分段时长: {p}")
        ds.append(d)
    return ds


def _video_prep_filter(input_idx: int, w: int, h: int, target_w: int, target_h: int) -> str:
    """与 composer 慢路径一致：scale+pad 到统一画布，xfade 要求宽高完全相同。"""
    base = f"[{input_idx}:v]"
    if w == target_w and h == target_h:
        return f"{base}setsar=1,setpts=PTS-STARTPTS"
    return (
        f"{base}scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
        f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,setpts=PTS-STARTPTS"
    )


def _audio_prep_filter(input_idx: int, sample_rate: int) -> str:
    """统一为 48kHz stereo，避免 acrossfade 因声道/采样率不一致失败。"""
    base = f"[{input_idx}:a]"
    if sample_rate == 48000:
        return f"{base}asetpts=PTS-STARTPTS"
    return (
        f"{base}aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"asetpts=PTS-STARTPTS"
    )


def _resolve_target_canvas(paths: Sequence[str]) -> tuple[int, int]:
    """取各段宽高的最大值作为 xfade 画布，避免长画面被压进短画布。"""
    max_w, max_h = 0, 0
    for p in paths:
        w, h = probe_video_dimensions(p, default=(1920, 1080), logger_=logger)
        max_w = max(max_w, w)
        max_h = max(max_h, h)
    if max_w <= 0 or max_h <= 0:
        return 1920, 1080
    return max_w, max_h


def compose_with_transitions(
    seg_paths: Sequence[str],
    transitions: Sequence[SegmentTransitionKind],
    *,
    dissolve_sec: float = 0.35,
    segment_fade_ms: int = 80,
    out_path: str,
) -> str:
    """将多段视频按 transitions 合成；需要重编码。"""
    paths = list(seg_paths)
    if not paths:
        raise ValueError("seg_paths 为空")
    if len(paths) == 1:
        return paths[0]

    durs = _seg_durations(paths)
    trans = list(transitions)
    while len(trans) < len(paths):
        trans.append("hard_cut")

    # 是否全程硬切且无 micro-fade → 调用方可走 concat copy；此处统一重编码路径
    use_xfade = any(
        trans[i] in ("cross_dissolve", "fade_in", "fade_out")
        for i in range(1, len(paths))
    ) or trans[0] in ("fade_in",)

    if not use_xfade and segment_fade_ms <= 0:
        # 硬切 + concat demuxer
        from app.utils.ffmpeg_utils import write_concat_list

        concat_list = out_path + ".concat.txt"
        write_concat_list(paths, concat_list)
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
                out_path,
            ],
            desc="postprod concat+copy",
        )
        try:
            os.remove(concat_list)
        except OSError:
            pass
        return out_path

    d = max(0.05, min(float(dissolve_sec), 1.5))
    fade_a = max(0.0, segment_fade_ms / 1000.0)

    target_w, target_h = _resolve_target_canvas(paths)
    n = len(paths)
    logger.info(
        "postprod xfade: %d 段, 目标画布 %dx%d",
        n,
        target_w,
        target_h,
    )

    filter_parts: List[str] = []
    for i in range(n):
        w, h = probe_video_dimensions(paths[i], logger_=logger)
        if w != target_w or h != target_h:
            logger.info("postprod xfade: seg_%d %dx%d -> %dx%d", i, w, h, target_w, target_h)
        vf = _video_prep_filter(i, w, h, target_w, target_h)
        sr = probe_audio_sample_rate(paths[i], logger_=logger)
        af = _audio_prep_filter(i, sr)
        if fade_a > 0:
            af += f",afade=t=in:st=0:d={fade_a:.3f},afade=t=out:st={max(0.0, durs[i] - fade_a):.3f}:d={fade_a:.3f}"
        if i == 0 and trans[0] == "fade_in":
            fi = min(d, durs[0] * 0.4)
            vf += f",fade=t=in:st=0:d={fi:.3f}"
        if i == n - 1 and trans[-1] == "fade_out":
            fo = min(d, durs[-1] * 0.4)
            vf += f",fade=t=out:st={max(0.0, durs[-1] - fo):.3f}:d={fo:.3f}"
        filter_parts.append(f"{vf}[v{i}]")
        filter_parts.append(f"{af}[a{i}]")

    vlabel = "v0"
    alabel = "a0"
    acc_dur = durs[0]
    for i in range(1, n):
        kind = trans[i]
        if kind in ("cross_dissolve", "fade_in", "fade_out"):
            td = min(d, durs[i - 1] * 0.45, durs[i] * 0.45, acc_dur * 0.45)
            offset = max(0.0, acc_dur - td)
            vn = f"vx{i}"
            an = f"ax{i}"
            xfade_type = "fade" if kind == "cross_dissolve" else "fade"
            filter_parts.append(
                f"[{vlabel}][v{i}]xfade=transition={xfade_type}:duration={td:.3f}:offset={offset:.3f}[{vn}]"
            )
            filter_parts.append(
                f"[{alabel}][a{i}]acrossfade=d={td:.3f}[{an}]"
            )
            vlabel = vn
            alabel = an
            acc_dur = acc_dur + durs[i] - td
        else:
            vn = f"vc{i}"
            an = f"ac{i}"
            filter_parts.append(f"[{vlabel}][v{i}]concat=n=2:v=1:a=0[{vn}]")
            filter_parts.append(f"[{alabel}][a{i}]concat=n=2:v=0:a=1[{an}]")
            vlabel = vn
            alabel = an
            acc_dur += durs[i]

    filter_parts.append(f"[{vlabel}]null[vout]")
    filter_parts.append(f"[{alabel}]anull[aout]")
    fc = ";".join(filter_parts)

    cmd: List[str] = []
    for p in paths:
        cmd += ["-i", p]
    cmd += [
        "-filter_complex",
        fc,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        out_path,
    ]
    run_ffmpeg(cmd, desc="postprod xfade compose")
    return out_path
