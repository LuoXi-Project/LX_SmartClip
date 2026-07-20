"""直通渲染器：单源片切片拼接场景的单进程直通路径。

适用场景（智能路由判定）：
- 所有 segment 来自同一源视频（如口播快剪 ASR 句子切片）
- 无 TTS 配音、无静音段、无混剪视觉特效
- 无需成片缩放（或缩放与源片一致）

核心思路：把"逐段材质化(80次重编码) → 逐段 concat → 二次合成烧字幕/转场"
压缩成"单条 ffmpeg 命令一次出片"：
- 每段一个 -ss -t -i src 输入（容器级 seek，毫秒级）
- filter_complex 内完成：段预处理 → 段间转场(xfade/concat) → 烧字幕(ass)
- 单次编码（沿用 build_render_codec_args，与通用管线画质参数完全一致）

收益：跳过 N 次关键帧扫描（实测 80 段 100+ 秒）和 N 次 ffmpeg 进程开销。
失败时返回 None，由调用方回退通用管线。
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

from app.core.postprod.transitions import SegmentTransitionKind, resolve_segment_transitions
from app.core.subtitle.ass_builder import build_ass
from app.core.subtitle.render_opts import (
    build_extra_video_filters,
    build_render_codec_args,
    sanitize_merged_opts_for_final_burn,
    sanitize_no_stream_copy,
)
from app.utils.ffprobe_utils import probe_duration, probe_video_dimensions
from app.utils.ffmpeg_utils import run_ffmpeg

if TYPE_CHECKING:
    from app.models.production import ProductionProfile
    from app.models.subtitle import SubtitleStyle

logger = logging.getLogger(__name__)


def _fast_render_mode() -> str:
    """智能路由开关：auto(默认自动判定) / on(强制尝试) / off(禁用)。"""
    return (os.environ.get("SMARTCLIP_FAST_RENDER") or "auto").strip().lower()


def _collect_seg_src_info(
    segments: list,
    clip_map: dict,
) -> Optional[List[Tuple[object, str, float, float, float]]]:
    """
    收集每个 segment 在源片的绝对时间区间。

    返回 list[(seg, src_video_path, abs_start, span, clip_dur)]，失败返回 None。
    仅当所有 segment 都能解析出同一源片时才返回结果。
    """
    out: List[Tuple[object, str, float, float, float]] = []
    common_src: Optional[str] = None
    for i, seg in enumerate(segments):
        # 取 clip_id / clip_ids / clip_trims（与 collect_segment_sources 一致的优先级）
        trims = getattr(seg, "clip_trims", None) or []
        if trims:
            cid = str(getattr(trims[0], "clip_id", "") or "").strip()
            if not cid or cid not in clip_map:
                return None
            clip_rel_start = float(getattr(trims[0], "clip_start_sec", 0.0) or 0.0)
            span = float(getattr(trims[0], "duration_sec", 0.0) or 0.0)
        else:
            raw_ids = list(getattr(seg, "clip_ids", None) or [])
            if not raw_ids and getattr(seg, "clip_id", None):
                raw_ids = [seg.clip_id]
            raw_ids = [c for c in raw_ids if c]
            if len(raw_ids) != 1:
                # 多 clip 组（混剪）→ 不走直通
                return None
            cid = str(raw_ids[0])
            if cid not in clip_map:
                return None
            rel_cs = getattr(seg, "clip_start_sec", None)
            try:
                clip_rel_start = float(rel_cs) if rel_cs is not None else 0.0
            except Exception:
                clip_rel_start = 0.0
            # duration_sec：用户/规划指定时长
            dur_want = getattr(seg, "duration_sec", None)
            try:
                span = float(dur_want) if dur_want is not None else 0.0
            except Exception:
                span = 0.0

        info = clip_map[cid]
        src_video = str(info.get("src_video_path") or "").strip()
        if not src_video or not os.path.isfile(src_video):
            return None
        if common_src is None:
            common_src = src_video
        elif src_video != common_src:
            # 多源片 → 不走直通
            return None

        clip_dur = float(info.get("dur") or 0.0)
        # 映射到源片绝对时间（与 segment_render.py:466-478 一致）
        clip_abs_start = float(info.get("src_start") or 0.0)
        abs_start = clip_abs_start + clip_rel_start
        if span <= 0.05:
            span = max(0.1, clip_dur - clip_rel_start)
        out.append((seg, src_video, abs_start, span, clip_dur))
    return out


def _can_fast_render(
    segments: list,
    clip_map: dict,
    seg_src: List[Tuple[object, str, float, float, float]],
    tts_audio_dir: str,
    final_render_opts: Dict[str, str],
    mode: str,
) -> Tuple[bool, str]:
    """
    直通路径启用条件校验。返回 (可否直通, 原因)。

    保守策略：任一条件不满足即回退通用管线。
    """
    from app.core.subtitle.segment_render import segment_has_tts

    # 1. 至少 2 段（1 段直接走通用快路径即可）
    if len(segments) < 2:
        return False, "段数 < 2"

    # 2. 无 TTS 配音段
    if mode == "tts" or any(segment_has_tts(seg, tts_audio_dir) for seg in segments):
        return False, "存在 TTS 配音段"

    # 3. 无静音段
    if any(bool(getattr(seg, "mute_audio", False)) for seg in segments):
        return False, "存在静音段"

    # 4. 无混剪视觉特效
    if any(getattr(seg, "visual_effect", None) is not None for seg in segments):
        return False, "存在混剪视觉特效"

    # 5. 无成片缩放（缩放与源片不一致时交由通用管线处理 scale+pad）
    opts = sanitize_merged_opts_for_final_burn(final_render_opts, seg_src[0][1])
    sw = _opt_int(opts, "clip_scale_width")
    sh = _opt_int(opts, "clip_scale_height")
    if sw > 0 or sh > 0:
        src_w, src_h = probe_video_dimensions(seg_src[0][1], default=(0, 0), logger_=logger)
        if sw > 0 and sh > 0 and (sw, sh) != (src_w, src_h):
            return False, f"成片缩放 {sw}x{sh} 与源片 {src_w}x{src_h} 不一致"
        if (sw > 0 and sw != src_w) or (sh > 0 and sh != src_h):
            return False, "成片缩放与源片不一致"

    return True, "ok"


def _opt_int(opts: Dict[str, str], key: str) -> int:
    try:
        return int(float((opts.get(key) or "").strip() or 0))
    except Exception:
        return 0


def _build_transition_chain(
    n: int,
    transitions: Sequence[SegmentTransitionKind],
    seg_durs: List[float],
    dissolve_sec: float,
    segment_fade_ms: int,
    is_bookend_fade_in: bool,
    is_bookend_fade_out: bool,
) -> Tuple[List[str], str, str, List[float]]:
    """
    构建段间转场 filter 链（视频+音频）。

    返回 (filter_parts, 最终视频 label, 最终音频 label, 每段实际占用时长)。
    与 transitions.py 的 compose_with_transitions 语义一致，仅内联到单进程。

    trans[i] 表示进入第 i 段的转场。
    """
    d = max(0.05, min(float(dissolve_sec), 1.5))
    fade_a = max(0.0, segment_fade_ms / 1000.0)
    parts: List[str] = []

    # 段预处理（每段加 micro-fade 消爆音；首段 fade_in / 末段 fade_out 仅 bookend 时）
    for i in range(n):
        vf = f"[v{i}]setpts=PTS-STARTPTS"
        # 注意：setsar=1 已在调用方段预处理里加过，这里不重复
        af = f"[a{i}]asetpts=PTS-STARTPTS"
        if fade_a > 0:
            af += f",afade=t=in:st=0:d={fade_a:.3f},afade=t=out:st={max(0.0, seg_durs[i] - fade_a):.3f}:d={fade_a:.3f}"
        if i == 0 and is_bookend_fade_in and transitions[0] == "fade_in":
            fi = min(d, seg_durs[0] * 0.4)
            vf += f",fade=t=in:st=0:d={fi:.3f}"
        if i == n - 1 and is_bookend_fade_out and transitions[-1] == "fade_out":
            fo = min(d, seg_durs[-1] * 0.4)
            vf += f",fade=t=out:st={max(0.0, seg_durs[-1] - fo):.3f}:d={fo:.3f}"
        parts.append(f"{vf}[vv{i}]")
        parts.append(f"{af}[aa{i}]")

    vlabel = "vv0"
    alabel = "aa0"
    acc_dur = seg_durs[0]
    for i in range(1, n):
        kind = transitions[i] if i < len(transitions) else "hard_cut"
        if kind in ("cross_dissolve", "fade_in", "fade_out"):
            td = min(d, seg_durs[i - 1] * 0.45, seg_durs[i] * 0.45, acc_dur * 0.45)
            offset = max(0.0, acc_dur - td)
            vn, an = f"vx{i}", f"ax{i}"
            parts.append(
                f"[{vlabel}][vv{i}]xfade=transition=fade:duration={td:.3f}:offset={offset:.3f}[{vn}]"
            )
            parts.append(f"[{alabel}][aa{i}]acrossfade=d={td:.3f}[{an}]")
            vlabel, alabel = vn, an
            acc_dur = acc_dur + seg_durs[i] - td
        else:
            vn, an = f"vc{i}", f"ac{i}"
            parts.append(f"[{vlabel}][vv{i}]concat=n=2:v=1:a=0[{vn}]")
            parts.append(f"[{alabel}][aa{i}]concat=n=2:v=0:a=1[{an}]")
            vlabel, alabel = vn, an
            acc_dur += seg_durs[i]

    return parts, vlabel, alabel, seg_durs


def try_fast_render(
    *,
    segments: list,
    srt_entries: list,
    clip_map: dict,
    style: Optional["SubtitleStyle"],
    project_name: str,
    fonts_dir: str,
    tmp: str,
    final_render_opts: Dict[str, str],
    normalize_audio: bool,
    prefer_gpu: bool,
    tts_audio_dir: str,
    render_mode: str,
    materialize_from_source: bool,
    production_profile: Optional["ProductionProfile"] = None,
) -> Optional[str]:
    """
    尝试直通渲染。成功返回成片路径，不满足条件或失败返回 None。

    所有异常均被捕获并记日志后返回 None，由调用方回退通用管线。
    """
    mode_env = _fast_render_mode()
    if mode_env == "off":
        return None

    try:
        # ===== 1. 路由判定 =====
        seg_src = _collect_seg_src_info(segments, clip_map)
        if seg_src is None:
            if mode_env == "on":
                logger.info("fast_render: 强制模式但无法解析源片信息，回退通用管线")
            return None

        mode = (render_mode or "auto").strip().lower()
        if mode == "auto":
            from app.core.subtitle.segment_render import segment_has_tts

            mode = "tts" if any(segment_has_tts(s, tts_audio_dir) for s in segments) else "original"

        can, reason = _can_fast_render(
            segments, clip_map, seg_src, tts_audio_dir, final_render_opts, mode
        )
        if not can:
            if mode_env == "on":
                logger.info("fast_render: 强制模式但条件不满足(%s)，回退通用管线", reason)
            return None

        n = len(seg_src)
        src_path = seg_src[0][1]
        logger.info("fast_render: 直通路径启用 (%d 段, 源=%s)", n, os.path.basename(src_path))

        # ===== 2. 构建输入（每段一个 -ss -t -i）=====
        cmd_inputs: List[str] = []
        seg_durs: List[float] = []
        for _seg, _src, abs_start, span, _cd in seg_src:
            cmd_inputs += ["-ss", f"{abs_start:.3f}", "-t", f"{span:.3f}", "-i", src_path]
            seg_durs.append(max(0.05, span))

        # ===== 3. 构建 filter_complex =====
        filter_parts: List[str] = []

        # 段预处理：setsar=1 + 成片额外滤镜（fps 等，不含 scale，已由 _can_fast_render 排除）
        opts_for_vf = sanitize_merged_opts_for_final_burn(final_render_opts, src_path)
        extra_filters = [f for f in build_extra_video_filters(opts_for_vf) if not f.startswith("scale=")]
        vf_tail = ("," + ",".join(extra_filters)) if extra_filters else ""

        for i in range(n):
            filter_parts.append(f"[{i}:v]setsar=1,setpts=PTS-STARTPTS{vf_tail}[v{i}]")
            filter_parts.append(f"[{i}:a]asetpts=PTS-STARTPTS[a{i}]")

        # 段间转场链
        trans = _resolve_transitions_for_fast(segments, production_profile, n)
        tp = None
        is_bookend_in = is_bookend_out = False
        dissolve_sec = 0.35
        segment_fade_ms = 0
        if production_profile is not None:
            tp = production_profile.transition
            dissolve_sec = float(tp.dissolve_sec)
            segment_fade_ms = int(tp.segment_fade_ms)
            is_bookend_in = tp.bookend_fade_in_sec > 0
            is_bookend_out = tp.bookend_fade_out_sec > 0

        chain_parts, vlabel, alabel, _ = _build_transition_chain(
            n, trans, seg_durs, dissolve_sec, segment_fade_ms, is_bookend_in, is_bookend_out
        )
        filter_parts.extend(chain_parts)

        # 烧字幕（ass）—— 套在转场链之后
        vf_post = ""
        if srt_entries and style is not None:
            src_w, src_h = probe_video_dimensions(src_path, default=(1920, 1080), logger_=logger)
            ass_path = os.path.join(tmp, f"{project_name}__fast.ass")
            with open(ass_path, "w", encoding="utf-8") as f:
                f.write(build_ass(srt_entries, style, (src_w, src_h)))
            ass_filter_path = ass_path.replace("\\", "/").replace(":", "\\:")
            ass_filter = f"ass='{ass_filter_path}'"
            if fonts_dir and os.path.isdir(fonts_dir):
                safe_fonts = fonts_dir.replace("\\", "/").replace(":", "\\:")
                ass_filter = f"ass='{ass_filter_path}':fontsdir='{safe_fonts}'"
            vf_post = f",{ass_filter}"
            logger.info("fast_render: 字幕 %d 条已生成", len(srt_entries))

        filter_parts.append(f"[{vlabel}]null{vf_post}[vout]")
        filter_parts.append(f"[{alabel}]anull[aout]")
        filter_complex = ";".join(filter_parts)

        # ===== 4. 编码参数（完全沿用通用管线）=====
        # 音频经 filter 必须重编码；视频沿用 build_render_codec_args（含 NVENC/CQ/CRF）
        codec_opts = sanitize_no_stream_copy(dict(final_render_opts or {}))
        # 确保音频编码器非 copy
        if (codec_opts.get("clip_acodec") or "aac").lower() == "copy":
            codec_opts["clip_acodec"] = "aac"
        codec_args = build_render_codec_args(codec_opts)
        # 滤镜链含 ass/xfade，必须重编码视频
        codec_args = _ensure_video_reencode(codec_args, codec_opts)

        out_path = os.path.join(tmp, f"{project_name}.mp4")
        cmd = ["-hwaccel", "auto"]
        cmd += cmd_inputs
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "[aout]",
            *codec_args,
            "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart",
            out_path,
        ]

        logger.info(
            "fast_render: %d 段直通合成 (转场=%d xfade, 字幕=%s)",
            n,
            sum(1 for t in trans[1:] if t != "hard_cut"),
            "有" if vf_post else "无",
        )
        run_ffmpeg(cmd, desc=f"fast_render 直通({n}段)")
        logger.info("fast_render: 直通合成完成 -> %s", out_path)
        return out_path

    except Exception as e:
        logger.warning("fast_render: 直通失败，回退通用管线: %s", e)
        return None


def _resolve_transitions_for_fast(
    segments: list,
    production_profile: Optional["ProductionProfile"],
    n: int,
) -> List[SegmentTransitionKind]:
    """复用 resolve_segment_transitions 解析每段入向转场。"""
    plan = [getattr(s, "transition_in", None) for s in segments]
    if production_profile is not None:
        return resolve_segment_transitions(n, production_profile, plan_transitions=plan)
    return [p or "hard_cut" for p in plan]


def _ensure_video_reencode(codec_args: List[str], opts: Dict[str, str]) -> List[str]:
    """filter_complex 含 ass/xfade 等滤镜时，确保视频非 stream copy。"""
    out = list(codec_args)
    try:
        vi = out.index("-c:v")
    except ValueError:
        return out
    if vi + 1 >= len(out):
        return out
    if (out[vi + 1] or "").strip().lower() != "copy":
        return out
    # copy → 回退到配置编码器（与 force_video_reencode 一致）
    fallback = dict(opts)
    fallback["clip_vcodec"] = fallback.get("clip_vcodec") or "libx264"
    fallback.setdefault("clip_preset", "veryfast")
    fallback.setdefault("clip_crf", "18")
    fallback.setdefault("clip_g", "48")
    fallback.setdefault("clip_pix_fmt", "yuv420p")
    return build_render_codec_args(fallback)
