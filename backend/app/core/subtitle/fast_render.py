"""直通渲染器：单源片切片拼接场景的单进程直通路径。

适用场景（智能路由判定）：
- 所有 segment（含其 clip_trims 的每个子 clip）来自同一源视频
  （如口播快剪 ASR 句子切片、手动匹配/音频匹配的多段一键成片）
- 无静音段、无混剪视觉特效
- 无需成片缩放（或缩放与源片一致）
- 可带段级配音覆盖（TTS / 切片原声 am_*.wav）：有配音的段以配音为硬上限截断画面

核心思路：把"逐段材质化(N×M 次重编码) → 逐段 concat → 二次合成烧字幕/转场"
压缩成"单条 ffmpeg 命令一次出片"：
- 每个子 clip 一个 -ss -t -i src 输入（容器级 seek，毫秒级）
- 每个有配音的段额外一个 -i tts 输入
- filter_complex 内完成：段内子 clip 预拼接 → 段级配音覆盖 → 段间转场(xfade/concat) → 烧字幕(ass)
- 单次编码（沿用 build_render_codec_args，与通用管线画质参数完全一致）

收益：跳过 N×M 次关键帧扫描、N×M 次 ffmpeg 进程开销与 N×M 次重编码，
且单进程不爆机，避免「切片多导致合成失败」。

失败时返回 None，由调用方回退通用管线。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
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


@dataclass
class _SubClip:
    """单个子 clip 在源片上的绝对时间区间（待 seek）。"""

    cid: str
    abs_start: float
    span: float
    # 输入索引（-ss -t -i src 在 cmd 中的序号），由 try_fast_render 统一分配
    input_idx: int = -1


@dataclass
class _FastSegment:
    """直通方案中的一个段落：由若干子 clip 预拼接而成，可选配音覆盖。"""

    seg: object
    subclips: List[_SubClip]
    # 有配音段：tts 文件绝对路径；无配音段：None（保留源音）
    tts_path: Optional[str] = None
    tts_dur: float = 0.0
    # 配音输入索引（-i tts 在 cmd 中的序号），无配音时为 -1
    tts_input_idx: int = -1

    @property
    def video_dur(self) -> float:
        """该段子 clip 预拼接后的画面总时长。"""
        return sum(max(0.05, float(s.span)) for s in self.subclips)


@dataclass
class _FastRenderPlan:
    """直通方案：同源 + 多段（每段可含多子 clip + 可选配音）。"""

    src_path: str
    segments: List[_FastSegment] = field(default_factory=list)


def _fast_render_mode() -> str:
    """智能路由开关：auto(默认自动判定) / on(强制尝试) / off(禁用)。"""
    return (os.environ.get("SMARTCLIP_FAST_RENDER") or "auto").strip().lower()


def _resolve_seg_subclips(
    seg,
    clip_map: dict,
    src_total: float,
    common_src: Optional[str],
) -> Tuple[Optional[List[Tuple[str, float, float]]], Optional[str], Optional[str]]:
    """
    解析单段的子 clip 列表（clip_trims 优先，回退单 clip_id）。

    返回 (subclips, src_video, new_common_src)：
    - subclips: [(cid, abs_start, span)]；解析失败返回 (None, ...)
    - src_video: 本段源片绝对路径（未配置源片则为 ""，调用方据此判多源/不可直通）
    - new_common_src: 累计的公共源片（与既有不一致时表示多源）

    abs_start / span 的 clamp 与 segment_render.py:466-478 的 materialize 逐帧一致。
    """
    trims = getattr(seg, "clip_trims", None) or []
    pairs: List[Tuple[str, float, float]] = []  # (cid, clip_rel_start, clip_rel_span)
    if trims:
        for t in trims:
            cid = str(getattr(t, "clip_id", "") or "").strip()
            if not cid or cid not in clip_map:
                return None, None, common_src
            try:
                rel_st = float(getattr(t, "clip_start_sec", 0.0) or 0.0)
                rel_sp = float(getattr(t, "duration_sec", 0.0) or 0.0)
            except Exception:
                rel_st, rel_sp = 0.0, 0.0
            pairs.append((cid, rel_st, rel_sp))
    else:
        raw_ids = list(getattr(seg, "clip_ids", None) or [])
        if not raw_ids and getattr(seg, "clip_id", None):
            raw_ids = [seg.clip_id]
        raw_ids = [c for c in raw_ids if c]
        if not raw_ids:
            return None, None, common_src
        rel_cs = getattr(seg, "clip_start_sec", None)
        try:
            rel_st0 = float(rel_cs) if rel_cs is not None else 0.0
        except Exception:
            rel_st0 = 0.0
        dur_want = getattr(seg, "duration_sec", None)
        try:
            rel_sp0 = float(dur_want) if dur_want is not None else 0.0
        except Exception:
            rel_sp0 = 0.0
        # 单 clip：把请求区间映射到每个 clip（保持与慢路径「无 trims」一致的回退语义）
        if len(raw_ids) == 1:
            pairs.append((str(raw_ids[0]), rel_st0, rel_sp0))
        else:
            # 无 trims 的多 clip：回退为整段使用（与 materialize 无 trims 的回退一致）
            for cid in raw_ids:
                pairs.append((str(cid), 0.0, 0.0))

    out: List[Tuple[str, float, float]] = []
    src_video = ""
    for cid, clip_rel_start, clip_rel_span in pairs:
        info = clip_map[cid]
        this_src = str(info.get("src_video_path") or "").strip()
        if not this_src:
            # 该 clip 无源片映射（只有预处理文件）→ 无法走源片直通
            return None, None, common_src
        if src_video == "":
            src_video = this_src
        # clip 级时长（用于 span 兜底）
        clip_probe_total = float(info.get("dur") or 0.0)
        if clip_probe_total <= 0.05:
            clip_probe_total = float(probe_duration(info.get("path") or "", log_on_failure=True) or 0.0)
        # 映射到源片绝对时间（与 segment_render.py:466-478 一致 + clamp）
        clip_abs_start = float(info.get("src_start") or 0.0)
        clip_abs_end = float(info.get("src_end") or 0.0)
        if clip_abs_end <= clip_abs_start + 0.02:
            clip_abs_end = clip_abs_start + clip_probe_total
        abs_start = clip_abs_start + clip_rel_start
        abs_start = max(0.0, min(abs_start, src_total - 0.05, clip_abs_end - 0.05))
        if clip_rel_span <= 0.05:
            # 未指定时长：取 clip 内剩余可用
            span = max(0.1, min(clip_abs_end - abs_start, src_total - abs_start))
        else:
            span = min(
                clip_rel_span,
                max(0.05, clip_abs_end - abs_start),
                max(0.05, src_total - abs_start),
            )
        out.append((cid, abs_start, max(0.05, span)))

    if common_src is None:
        new_common = src_video if src_video else None
    elif src_video and src_video != common_src:
        new_common = None  # 多源标记
    else:
        new_common = common_src
    return out, src_video, new_common


def _collect_seg_src_info(
    segments: list,
    clip_map: dict,
    tts_audio_dir: str,
) -> Optional[_FastRenderPlan]:
    """
    收集直通方案。仅当所有子 clip 都能解析出同一源片时返回 plan，否则 None。

    段级配音（tts_filename）会被解析并写入 plan（不存在视为无配音）。
    """
    # 第一遍：确定 common_src（任一子 clip 多源 → 直接放弃）。
    # 源片总时长依赖 common_src，故先不 clamp 地扫一遍判定同源。
    common_src: Optional[str] = None
    for seg in segments:
        sub_src_only, src_video, common_src = _resolve_seg_subclips(
            seg, clip_map, src_total=1e9, common_src=common_src
        )
        if sub_src_only is None:
            return None
        if common_src is None:
            # src_video 为空说明该 clip 无源片映射
            return None
    if common_src is None or not os.path.isfile(common_src):
        return None

    src_total = float(probe_duration(common_src, log_on_failure=True) or 0.0)
    if src_total <= 0.05:
        return None

    plan = _FastRenderPlan(src_path=common_src)
    for seg in segments:
        pairs, _src_video, _ = _resolve_seg_subclips(seg, clip_map, src_total=src_total, common_src=common_src)
        if pairs is None:
            return None
        subclips = [_SubClip(cid=cid, abs_start=st, span=sp) for (cid, st, sp) in pairs]
        # 段级配音
        tts_path: Optional[str] = None
        tts_dur = 0.0
        tts_name = str(getattr(seg, "tts_filename", "") or "").strip()
        if tts_name:
            cand = os.path.join(tts_audio_dir, os.path.basename(tts_name))
            if os.path.isfile(cand):
                tts_path = cand
                tts_dur = float(probe_duration(cand, log_on_failure=True) or 0.0)
        plan.segments.append(
            _FastSegment(seg=seg, subclips=subclips, tts_path=tts_path, tts_dur=tts_dur)
        )
    return plan


def _can_fast_render(
    plan: _FastRenderPlan,
    tts_audio_dir: str,
    final_render_opts: Dict[str, str],
    mode: str,  # noqa: ARG001 - 保留入参以兼容旧调用；直通路径现支持段级配音，不再按 mode 拒绝
) -> Tuple[bool, str]:
    """
    直通路径启用条件校验。返回 (可否直通, 原因)。

    保守策略：任一条件不满足即回退通用管线。
    段级配音（TTS / 切片原声）不再拒绝：配音段在 filter 内做覆盖 + 配音时长硬截断。
    """
    n = len(plan.segments)
    # 1. 至少 2 段（1 段直接走通用快路径即可）
    if n < 2:
        return False, "段数 < 2"

    # 2. 无静音段
    if any(bool(getattr(fs.seg, "mute_audio", False)) for fs in plan.segments):
        return False, "存在静音段"

    # 3. 无混剪视觉特效
    if any(getattr(fs.seg, "visual_effect", None) is not None for fs in plan.segments):
        return False, "存在混剪视觉特效"

    # 4. 有配音段：配音文件必须存在（已在 collect 阶段解析；这里再兜底校验）
    for fs in plan.segments:
        if fs.tts_path and not os.path.isfile(fs.tts_path):
            return False, f"配音文件缺失: {fs.tts_path}"

    # 5. 无成片缩放（缩放与源片不一致时交由通用管线处理 scale+pad）
    opts = sanitize_merged_opts_for_final_burn(final_render_opts, plan.src_path)
    sw = _opt_int(opts, "clip_scale_width")
    sh = _opt_int(opts, "clip_scale_height")
    if sw > 0 or sh > 0:
        src_w, src_h = probe_video_dimensions(plan.src_path, default=(0, 0), logger_=logger)
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


def _build_per_segment_chain(
    plan: _FastRenderPlan,
    vf_tail: str,
) -> Tuple[List[str], List[str], List[str], List[float]]:
    """
    构建每段「子 clip 预拼接 + 配音覆盖」的 filter 片段。

    返回 (filter_parts, video_labels, audio_labels, seg_durs)：
    - video_labels[i] / audio_labels[i]：第 i 段最终输出 label（供转场链消费）
    - seg_durs[i]：第 i 段最终画面时长（配音段以配音为硬上限截断）

    label 约定：每段子 clip 预拼接后产出 [vcat{i}]/[acat{i}]；配音覆盖/截断后产出
    [vseg{i}]/[aseg{i}]（无配音段为 [vseg{i}]/[aseg{i}] = 源画面+源音）。
    """
    parts: List[str] = []
    # 段内子 clip 预拼接：统一产出 [vcat{i}]/[acat{i}]
    for fs_idx, fs in enumerate(plan.segments):
        subs = fs.subclips
        if len(subs) == 1:
            sc = subs[0]
            parts.append(f"[{sc.input_idx}:v]setsar=1,setpts=PTS-STARTPTS{vf_tail}[vcat{fs_idx}]")
            parts.append(f"[{sc.input_idx}:a]asetpts=PTS-STARTPTS[acat{fs_idx}]")
        else:
            # 多子 clip：每子 clip reset 时间轴 → concat=n=k:v=1:a=1
            for k, sc in enumerate(subs):
                parts.append(f"[{sc.input_idx}:v]setsar=1,setpts=PTS-STARTPTS{vf_tail}[vpre{fs_idx}{k}]")
                parts.append(f"[{sc.input_idx}:a]asetpts=PTS-STARTPTS[apre{fs_idx}{k}]")
            concat_in = "".join(f"[vpre{fs_idx}{k}][apre{fs_idx}{k}]" for k in range(len(subs)))
            parts.append(f"{concat_in}concat=n={len(subs)}:v=1:a=1[vcat{fs_idx}][acat{fs_idx}]")

    # 配音覆盖 / 截断：产出 [vseg{i}]/[aseg{i}]
    video_labels: List[str] = []
    audio_labels: List[str] = []
    seg_durs: List[float] = []
    for fs_idx, fs in enumerate(plan.segments):
        v_dur = fs.video_dur
        if fs.tts_path and fs.tts_dur > 0.05:
            # 配音覆盖：以配音时长为硬上限截断画面；音轨用配音。
            # 画面短于配音时保留全长（直通路径不补帧/轮播，那属通用管线的 loop 策略）。
            out_dur = min(v_dur, fs.tts_dur)
            parts.append(
                f"[vcat{fs_idx}]trim=start=0:end={out_dur:.3f},setpts=PTS-STARTPTS[vseg{fs_idx}]"
            )
            parts.append(
                f"[{fs.tts_input_idx}:a]atrim=start=0:end={out_dur:.3f},asetpts=PTS-STARTPTS[aseg{fs_idx}]"
            )
            seg_durs.append(out_dur)
        else:
            # 无配音：保留源音与画面全长
            parts.append(f"[vcat{fs_idx}]setpts=PTS-STARTPTS[vseg{fs_idx}]")
            parts.append(f"[acat{fs_idx}]asetpts=PTS-STARTPTS[aseg{fs_idx}]")
            seg_durs.append(v_dur)
        video_labels.append(f"vseg{fs_idx}")
        audio_labels.append(f"aseg{fs_idx}")

    return parts, video_labels, audio_labels, seg_durs


def _build_transition_chain_from_labels(
    n: int,
    transitions: Sequence[SegmentTransitionKind],
    seg_durs: List[float],
    video_labels: List[str],
    audio_labels: List[str],
    dissolve_sec: float,
    segment_fade_ms: int,
    is_bookend_fade_in: bool,
    is_bookend_fade_out: bool,
) -> Tuple[List[str], str, str]:
    """
    基于每段输入 label 构建段间转场 filter 链（视频+音频）。

    与 transitions.py 的 compose_with_transitions 语义一致，仅内联到单进程。
    返回 (filter_parts, 最终视频 label, 最终音频 label)。

    trans[i] 表示进入第 i 段的转场。
    """
    d = max(0.05, min(float(dissolve_sec), 1.5))
    fade_a = max(0.0, segment_fade_ms / 1000.0)
    parts: List[str] = []

    # 段预处理（每段加 micro-fade 消爆音；首段 fade_in / 末段 fade_out 仅 bookend 时）
    vv_labels: List[str] = []
    aa_labels: List[str] = []
    for i in range(n):
        vf = f"[{video_labels[i]}]setpts=PTS-STARTPTS"
        af = f"[{audio_labels[i]}]asetpts=PTS-STARTPTS"
        if fade_a > 0:
            af += f",afade=t=in:st=0:d={fade_a:.3f},afade=t=out:st={max(0.0, seg_durs[i] - fade_a):.3f}:d={fade_a:.3f}"
        if i == 0 and is_bookend_fade_in and transitions[0] == "fade_in":
            fi = min(d, seg_durs[0] * 0.4)
            vf += f",fade=t=in:st=0:d={fi:.3f}"
        if i == n - 1 and is_bookend_fade_out and transitions[-1] == "fade_out":
            fo = min(d, seg_durs[-1] * 0.4)
            vf += f",fade=t=out:st={max(0.0, seg_durs[-1] - fo):.3f}:d={fo:.3f}"
        vv = f"vv{i}"
        aa = f"aa{i}"
        parts.append(f"{vf}[{vv}]")
        parts.append(f"{af}[{aa}]")
        vv_labels.append(vv)
        aa_labels.append(aa)

    vlabel = vv_labels[0]
    alabel = aa_labels[0]
    acc_dur = seg_durs[0]
    for i in range(1, n):
        kind = transitions[i] if i < len(transitions) else "hard_cut"
        if kind in ("cross_dissolve", "fade_in", "fade_out"):
            td = min(d, seg_durs[i - 1] * 0.45, seg_durs[i] * 0.45, acc_dur * 0.45)
            offset = max(0.0, acc_dur - td)
            vn, an = f"vx{i}", f"ax{i}"
            parts.append(
                f"[{vlabel}][{vv_labels[i]}]xfade=transition=fade:duration={td:.3f}:offset={offset:.3f}[{vn}]"
            )
            parts.append(f"[{alabel}][{aa_labels[i]}]acrossfade=d={td:.3f}[{an}]")
            vlabel, alabel = vn, an
            acc_dur = acc_dur + seg_durs[i] - td
        else:
            vn, an = f"vc{i}", f"ac{i}"
            parts.append(f"[{vlabel}][{vv_labels[i]}]concat=n=2:v=1:a=0[{vn}]")
            parts.append(f"[{alabel}][{aa_labels[i]}]concat=n=2:v=0:a=1[{an}]")
            vlabel, alabel = vn, an
            acc_dur += seg_durs[i]

    return parts, vlabel, alabel


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
        plan = _collect_seg_src_info(segments, clip_map, tts_audio_dir)
        if plan is None:
            if mode_env == "on":
                logger.info("fast_render: 强制模式但无法解析源片信息，回退通用管线")
            return None

        can, reason = _can_fast_render(plan, tts_audio_dir, final_render_opts, render_mode)
        if not can:
            if mode_env == "on":
                logger.info("fast_render: 强制模式但条件不满足(%s)，回退通用管线", reason)
            return None

        n = len(plan.segments)
        n_subclips = sum(len(fs.subclips) for fs in plan.segments)
        n_tts = sum(1 for fs in plan.segments if fs.tts_path)
        logger.info(
            "fast_render: 直通路径启用 (%d 段, %d 子clip, %d 配音段, 源=%s)",
            n,
            n_subclips,
            n_tts,
            os.path.basename(plan.src_path),
        )

        # ===== 2. 分配输入索引：先所有子 clip，再配音输入 =====
        next_idx = 0
        cmd_inputs: List[str] = []
        for fs in plan.segments:
            for sc in fs.subclips:
                sc.input_idx = next_idx
                cmd_inputs += ["-ss", f"{sc.abs_start:.3f}", "-t", f"{sc.span:.3f}", "-i", plan.src_path]
                next_idx += 1
        for fs in plan.segments:
            if fs.tts_path:
                fs.tts_input_idx = next_idx
                cmd_inputs += ["-i", fs.tts_path]
                next_idx += 1

        # ===== 3. 构建 filter_complex =====
        filter_parts: List[str] = []

        # 段预处理尾部：成片额外滤镜（fps 等，不含 scale，已由 _can_fast_render 排除）
        opts_for_vf = sanitize_merged_opts_for_final_burn(final_render_opts, plan.src_path)
        extra_filters = [f for f in build_extra_video_filters(opts_for_vf) if not f.startswith("scale=")]
        vf_tail = ("," + ",".join(extra_filters)) if extra_filters else ""

        seg_parts, video_labels, audio_labels, seg_durs = _build_per_segment_chain(plan, vf_tail)
        filter_parts.extend(seg_parts)

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

        chain_parts, vlabel, alabel = _build_transition_chain_from_labels(
            n,
            trans,
            seg_durs,
            video_labels,
            audio_labels,
            dissolve_sec,
            segment_fade_ms,
            is_bookend_in,
            is_bookend_out,
        )
        filter_parts.extend(chain_parts)

        # 烧字幕（ass）—— 套在转场链之后
        vf_post = ""
        if srt_entries and style is not None:
            src_w, src_h = probe_video_dimensions(plan.src_path, default=(1920, 1080), logger_=logger)
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
        # filter_complex 含 ass/xfade/concat，音视频均必须重编码。
        codec_opts = sanitize_no_stream_copy(dict(final_render_opts or {}))
        if (codec_opts.get("clip_acodec") or "aac").lower() == "copy":
            codec_opts["clip_acodec"] = "aac"
        codec_args = build_render_codec_args(codec_opts)
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
            "fast_render: %d 段直通合成 (转场=%d xfade, 字幕=%s, 配音=%d段)",
            n,
            sum(1 for t in trans[1:] if t != "hard_cut"),
            "有" if vf_post else "无",
            n_tts,
        )
        run_ffmpeg(cmd, desc=f"fast_render 直通({n}段,{n_subclips}子clip)")
        logger.info("fast_render: 直通合成完成 -> %s", out_path)
        return out_path

    except Exception as e:
        logger.warning("fast_render: 直通失败，回退通用管线: %s", e)
        return None
