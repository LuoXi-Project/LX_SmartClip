"""段间转场：xfade / acrossfade / micro-fade。"""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Literal, Optional, Sequence, Tuple

from app.core.subtitle.render_opts import build_render_codec_args
from app.models.production import ProductionProfile, TransitionPolicy
from app.utils.ffprobe_utils import probe_audio_sample_rate, probe_duration, probe_video_dimensions
from app.utils.ffmpeg_utils import run_ffmpeg

logger = logging.getLogger(__name__)

SegmentTransitionKind = Literal["hard_cut", "cross_dissolve", "fade_in", "fade_out"]


def _xfade_chunk_size() -> int:
    """
    xfade 分块大小：段数超过该阈值时，把单条超长 filter 链拆成多块各自一个 ffmpeg 进程，
    块间用 concat demuxer + copy 拼接（几乎零成本）。短链调度效率远高于 80 段单链。
    块边界只在 hard_cut 处切分，保证 cross_dissolve 不被拆断。
    """
    raw = (os.environ.get("SMARTCLIP_XFADE_CHUNK_SIZE") or "").strip()
    if raw:
        try:
            return max(4, int(float(raw)))
        except ValueError:
            pass
    return 12


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


def _segments_uniform_for_copy(paths: Sequence[str]) -> bool:
    """各段视频宽高、音频采样率一致时，concat demuxer 才能走 -c copy（零重编码）。

    concat demuxer + -c copy 仅复用各段原始包，不重采样/重缩放；段间分辨率或音频
    采样率不一致时，播放器按首段参数解码，第二段开始画面会卡死/黑屏/爆音。
    因此「纯硬切快路径」必须满足本函数为 True。
    """
    paths = list(paths)
    if not paths:
        return False
    w0, h0 = probe_video_dimensions(paths[0], default=(0, 0), logger_=logger)
    sr0 = probe_audio_sample_rate(paths[0], logger_=logger)
    for p in paths[1:]:
        w, h = probe_video_dimensions(p, default=(0, 0), logger_=logger)
        if (w, h) != (w0, h0):
            return False
        if probe_audio_sample_rate(p, logger_=logger) != sr0:
            return False
    return True


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
    """兜底画布：取各段中「出现次数最多」的分辨率（占比最高）。

    说明（与旧「取最大值」行为的差异）：
    - 混合分辨率混剪时（如 1 段 4K + 多段 1080p/720p），取最大值会把所有低清段放大到 4K：
      编码极慢、码率虚高，且放大的低清素材本就发糊，画质无明显收益。
    - 取占比最高的分辨率，多数段零成本直通，少数异类按需缩放，更贴近用户预期。
    - 出现次数并列时（多个分辨率频次相同），按宽*高降序取最大者，保持「不丢分辨率」的稳妥兜底。
    """
    from collections import Counter

    counts: Counter = Counter()
    for p in paths:
        w, h = probe_video_dimensions(p, default=(1920, 1080), logger_=logger)
        if w > 0 and h > 0:
            counts[(w, h)] += 1
    if not counts:
        return 1920, 1080
    # 频次最高；并列时取面积最大的（宽*高），避免在并列场景无谓缩水。
    best_w, best_h = max(counts.items(), key=lambda kv: (kv[1], kv[0][0] * kv[0][1]))[0]
    return best_w, best_h


def _make_even(x: int, *, min_v: int = 2) -> int:
    """偶数化（h264/yuv420p 要求宽高为偶数）。"""
    x = int(x)
    if x < min_v:
        x = min_v
    return x if (x % 2 == 0) else (x - 1)


def _try_hardcut_concat_filter(
    *,
    paths: List[str],
    target_w: int,
    target_h: int,
    render_opts: Optional[Dict[str, str]],
    out_path: str,
) -> bool:
    """纯硬切 + 段间分辨率不一致的合并路径：单条 concat filter，只编码一次。

    思路（已删去「逐段归一化」冗余层）：
      N 段原始输入 → filter 内每段 scale+pad 到统一画布 → concat → 重编码一次。
    全程只有一次编码，既快又彻底规避 concat demuxer + copy 的所有问题
    （B 帧 / SPS-PPS / timebase / encoder delay 不一致 → 画面冻结）。

    为什么不用 concat demuxer + copy（已踩三次坑）：
    字节级拼接要求各段参数「字节级一致」，逐段 NVENC 归一化仍无法保证；concat filter
    是「解码每帧 → filter graph 内拼接 → 重编码」，无 stream copy，参数不一致被解码层吸收。

    实测（22 段混合分辨率，NVENC p2）：单链 ~17s 编码 110s 成片，足够快，
    无需分块（分块反而会引入块间二次合并的额外编码）。

    返回 True 表示成功；False 表示失败/不可用，调用方回退到 _run_single_chain。
    """
    try:
        tw, th = _make_even(target_w), _make_even(target_h)
        n = len(paths)
        parts: List[str] = []
        inputs: List[str] = []
        for i, p in enumerate(paths):
            # 不用 -thread_queue_size：多输入 filter_graph 下大值（如 1024）会导致 ffmpeg 预缓冲
            # 爆内存 → 进程假死（实测 22 输入 × 1024 卡死）。默认缓冲稳定。
            inputs += ["-i", p]
            w, h = probe_video_dimensions(p, default=(tw, th), logger_=logger)
            if w != tw or h != th:
                logger.info("postprod hardcut concat: seg_%d %dx%d -> %dx%d", i, w, h, tw, th)
            # 与 _run_single_chain._video_prep_filter 一致：等大直接 setpts，不等大 scale+pad
            if w == tw and h == th:
                vf = f"[{i}:v]setsar=1,setpts=PTS-STARTPTS"
            else:
                vf = (
                    f"[{i}:v]scale={tw}:{th}:force_original_aspect_ratio=decrease,"
                    f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,setsar=1,setpts=PTS-STARTPTS"
                )
            sr = probe_audio_sample_rate(p, logger_=logger)
            af = _audio_prep_filter(i, sr)
            parts.append(vf + f"[v{i}]")
            parts.append(af + f"[a{i}]")
        cat = "".join(f"[v{i}][a{i}]" for i in range(n))
        parts.append(f"{cat}concat=n={n}:v=1:a=1[vout][aout]")
        fc = ";".join(parts)

        codec_args = build_render_codec_args(render_opts)
        run_ffmpeg(
            [*inputs, "-filter_complex", fc, "-map", "[vout]", "-map", "[aout]",
             *codec_args, "-movflags", "+faststart", out_path],
            desc=f"postprod hardcut concat filter ({n} segs, 1 encode)",
        )
        return True
    except Exception as e:
        logger.warning("postprod hardcut concat filter 失败，回退 xfade 单链: %s", e)
        return False


def compose_with_transitions(
    seg_paths: Sequence[str],
    transitions: Sequence[SegmentTransitionKind],
    *,
    dissolve_sec: float = 0.35,
    segment_fade_ms: int = 80,
    out_path: str,
    render_opts: Optional[Dict[str, str]] = None,
    target_canvas: Optional[Tuple[int, int]] = None,
) -> str:
    """将多段视频按 transitions 合成；需要重编码。编码器优先走配置（如 h264_nvenc），未配则 libx264。

    target_canvas：显式指定统一画布（宽,高），优先于「取各段最大值」的兜底逻辑。
    混合分辨率场景应传入 export 配置画布（如 1080p），避免把所有低清段放大到 4K。
    """
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
        # 纯硬切 + 无 micro-fade → 若各段分辨率/采样率一致才走 concat demuxer + copy（零重编码）。
        # 段间不一致时 concat copy 会让播放器按首段解码，第二段起画面卡死/黑屏；
        # 此时优先走「逐段归一化 + concat copy」快路径（失败回退下方 xfade 单链）。
        if _segments_uniform_for_copy(paths):
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

    # 画布来源优先级：调用方显式传入（export 配置）> 各段最大值兜底。
    if target_canvas is not None and target_canvas[0] > 0 and target_canvas[1] > 0:
        target_w, target_h = target_canvas
    else:
        target_w, target_h = _resolve_target_canvas(paths)
    n = len(paths)

    # 纯硬切 + 段间分辨率不一致 → 单条 concat filter（每段 scale+pad + concat + 一次重编码）。
    # 实测单链足够快（22 段 NVENC ~17s 编 110s），且无 stream copy，彻底规避 concat demuxer
    # 字节级拼接导致的画面冻结（B 帧 / SPS-PPS / timebase / encoder delay 不一致）。
    if not use_xfade and segment_fade_ms <= 0:
        if _try_hardcut_concat_filter(
            paths=paths,
            target_w=target_w,
            target_h=target_h,
            render_opts=render_opts,
            out_path=out_path,
        ):
            return out_path
        logger.warning("postprod: 归一化快路径失败，回退 xfade 单链重编码")

    logger.info(
        "postprod xfade: %d 段, 目标画布 %dx%d%s",
        n,
        target_w,
        target_h,
        "（配置）" if target_canvas is not None else "（占比最高兜底）",
    )

    def _run_single_chain(
        sub_paths: List[str],
        sub_trans: List[SegmentTransitionKind],
        sub_durs: List[float],
        block_out: str,
        *,
        is_first_block: bool,
        is_last_block: bool,
        input_index_base: int = 0,
    ) -> None:
        """对一组段构建单条 xfade/concat filter 链并运行（块内逻辑与原单进程一致）。"""
        bn = len(sub_paths)
        fparts: List[str] = []
        for li in range(bn):
            gi = input_index_base + li  # 仅用于日志，实际 filter 用块内局部下标 li
            w, h = probe_video_dimensions(sub_paths[li], logger_=logger)
            if w != target_w or h != target_h:
                logger.info("postprod xfade: seg_%d %dx%d -> %dx%d", gi, w, h, target_w, target_h)
            vf = _video_prep_filter(li, w, h, target_w, target_h)
            sr = probe_audio_sample_rate(sub_paths[li], logger_=logger)
            af = _audio_prep_filter(li, sr)
            if fade_a > 0:
                af += f",afade=t=in:st=0:d={fade_a:.3f},afade=t=out:st={max(0.0, sub_durs[li] - fade_a):.3f}:d={fade_a:.3f}"
            # fade_in 仅整片首段（第一个块的第一段）；fade_out 仅整片末段（最后一块的最后一段）。
            if is_first_block and li == 0 and sub_trans[0] == "fade_in":
                fi = min(d, sub_durs[0] * 0.4)
                vf += f",fade=t=in:st=0:d={fi:.3f}"
            if is_last_block and li == bn - 1 and sub_trans[-1] == "fade_out":
                fo = min(d, sub_durs[-1] * 0.4)
                vf += f",fade=t=out:st={max(0.0, sub_durs[-1] - fo):.3f}:d={fo:.3f}"
            fparts.append(f"{vf}[v{li}]")
            fparts.append(f"{af}[a{li}]")

        vlabel = "v0"
        alabel = "a0"
        acc_dur = sub_durs[0]
        for li in range(1, bn):
            kind = sub_trans[li]
            if kind in ("cross_dissolve", "fade_in", "fade_out"):
                td = min(d, sub_durs[li - 1] * 0.45, sub_durs[li] * 0.45, acc_dur * 0.45)
                offset = max(0.0, acc_dur - td)
                vn = f"vx{li}"
                an = f"ax{li}"
                xfade_type = "fade" if kind == "cross_dissolve" else "fade"
                fparts.append(
                    f"[{vlabel}][v{li}]xfade=transition={xfade_type}:duration={td:.3f}:offset={offset:.3f}[{vn}]"
                )
                fparts.append(
                    f"[{alabel}][a{li}]acrossfade=d={td:.3f}[{an}]"
                )
                vlabel = vn
                alabel = an
                acc_dur = acc_dur + sub_durs[li] - td
            else:
                vn = f"vc{li}"
                an = f"ac{li}"
                fparts.append(f"[{vlabel}][v{li}]concat=n=2:v=1:a=0[{vn}]")
                fparts.append(f"[{alabel}][a{li}]concat=n=2:v=0:a=1[{an}]")
                vlabel = vn
                alabel = an
                acc_dur += sub_durs[li]

        fparts.append(f"[{vlabel}]null[vout]")
        fparts.append(f"[{alabel}]anull[aout]")
        fc = ";".join(fparts)
        cmd: List[str] = []
        for p in sub_paths:
            cmd += ["-i", p]
        codec_args = build_render_codec_args(render_opts)
        cmd += [
            "-filter_complex",
            fc,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            *codec_args,
            "-movflags",
            "+faststart",
            block_out,
        ]
        run_ffmpeg(cmd, desc="postprod xfade compose")

    # 分块策略：段数 > 阈值时拆成多块，块边界只在 hard_cut 处，块间 concat+copy。
    # 单条超长 filter 链（如 80 段）调度效率低；拆成多块各自短链可显著加速。
    chunk_threshold = _xfade_chunk_size()
    use_chunked = n > chunk_threshold

    if not use_chunked:
        _run_single_chain(paths, trans, durs, out_path, is_first_block=True, is_last_block=True)
        return out_path

    # 找到所有可切的边界点（i 表示「第 i 段的入向转场」，即 trans[i] 控制第 i-1→i 段之间）。
    # 在 hard_cut 处切分，块间用 concat demuxer 拼接（硬切，无视觉差异）。
    hard_cut_boundaries = [i for i in range(1, n) if trans[i] == "hard_cut"]
    # 选间隔接近 chunk_threshold 的边界点作为切分点。
    cut_points: List[int] = []
    seg_start = 0
    for b in hard_cut_boundaries:
        if b - seg_start >= chunk_threshold:
            cut_points.append(b)
            seg_start = b
    # 未能切出足够大的块（边界不足）→ 退化为单链，保持效果与原实现一致。
    if len(cut_points) < 1:
        _run_single_chain(paths, trans, durs, out_path, is_first_block=True, is_last_block=True)
        return out_path

    block_ranges: List[Tuple[int, int]] = []  # [start, end) 半开区间
    prev = 0
    for cp in cut_points:
        block_ranges.append((prev, cp))
        prev = cp
    block_ranges.append((prev, n))

    logger.info(
        "postprod xfade 分块: %d 段 -> %d 块（块大小阈值 %d）",
        n,
        len(block_ranges),
        chunk_threshold,
    )

    block_paths: List[str] = []
    for bi, (bs, be) in enumerate(block_ranges):
        sub_paths = paths[bs:be]
        sub_trans = trans[bs:be]
        sub_durs = durs[bs:be]
        block_out = out_path + f".blk{bi:02d}.mp4"
        _run_single_chain(
            sub_paths,
            sub_trans,
            sub_durs,
            block_out,
            is_first_block=(bi == 0),
            is_last_block=(bi == len(block_ranges) - 1),
            input_index_base=bs,
        )
        block_paths.append(block_out)

    # 块间拼接：用 concat filter（解码→合并→重编码一次），不用 concat demuxer + copy。
    # 块间为硬切（边界均为 hard_cut），各块由 _run_single_chain 独立 NVENC 编码，SPS/PPS/
    # timebase 可能字节级不一致，concat copy 会触发跨块冻结。concat filter 各块已统一画布/采样率，
    # 链内无需 scale，只做时间轴重置 + concat，很轻；彻底无 stream copy，杜绝冻结。
    m = len(block_paths)
    bparts: List[str] = []
    binputs: List[str] = []
    for i, bp in enumerate(block_paths):
        binputs += ["-i", bp]
        bparts.append(f"[{i}:v]setpts=PTS-STARTPTS[v{i}]")
        bparts.append(f"[{i}:a]asetpts=PTS-STARTPTS[a{i}]")
    bcat = "".join(f"[v{i}][a{i}]" for i in range(m))
    bparts.append(f"{bcat}concat=n={m}:v=1:a=1[vout][aout]")
    bfc = ";".join(bparts)
    block_codec_args = build_render_codec_args(render_opts)
    run_ffmpeg(
        [*binputs, "-filter_complex", bfc, "-map", "[vout]", "-map", "[aout]",
         *block_codec_args, "-movflags", "+faststart", out_path],
        desc="postprod xfade block concat (filter merge)",
    )
    # 清理块中间文件
    for bp in block_paths:
        try:
            os.remove(bp)
        except OSError:
            pass
    return out_path
