from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Sequence

from app.utils.ffprobe_utils import probe_audio_sample_rate, probe_video_dimensions

from .ass_builder import build_ass
from app.utils.ffmpeg_utils import run_ffmpeg, write_concat_list
from .render_opts import (
    build_extra_video_filters,
    build_render_codec_args,
    canvas_wh_from_clip_scale_opts,
    force_video_reencode,
    iter_export_gpu_render_attempts,
    sanitize_merged_opts_for_final_burn,
    to_int,
)

if TYPE_CHECKING:
    from app.models.subtitle import SubtitleStyle

logger = logging.getLogger(__name__)


def _build_concat_codec_args(opts: Dict[str, str], normalize_audio: bool) -> List[str]:
    if normalize_audio:
        norm_render_opts = dict(opts)
        norm_render_opts["clip_acodec"] = "aac"
        return force_video_reencode(build_render_codec_args(norm_render_opts), render_opts=norm_render_opts)
    return force_video_reencode(build_render_codec_args(opts), render_opts=opts)


def _run_export_encode_attempts(
    *,
    prefer_gpu: bool,
    final_render_opts: Dict[str, str],
    normalize_audio: bool,
    cmd_for_codec: Callable[[List[str]], List[str]],
    desc: str,
) -> None:
    attempts = iter_export_gpu_render_attempts(final_render_opts, prefer_gpu)
    last_err: RuntimeError | None = None
    for idx, ro in enumerate(attempts):
        cc = _build_concat_codec_args(ro, normalize_audio)
        try:
            run_ffmpeg(cmd_for_codec(cc), desc=desc)
            if idx > 0:
                logger.warning("成片编码经回退后成功（第 %d 档）", idx + 1)
            return
        except RuntimeError as e:
            last_err = e
            if idx >= len(attempts) - 1:
                raise
            logger.warning("成片编码失败，尝试下一档（GPU→CPU 回退）: %s", e)
    if last_err:
        raise last_err


def _segments_uniform_for_stream_copy(seg_paths: List[str]) -> bool:
    """各段视频宽高、音频采样率一致时，concat 可走 stream copy（快）。"""
    if not seg_paths:
        return False
    w0, h0 = probe_video_dimensions(seg_paths[0], logger_=logger)
    sr0 = probe_audio_sample_rate(seg_paths[0], logger_=logger)
    for p in seg_paths[1:]:
        w, h = probe_video_dimensions(p, logger_=logger)
        if (w, h) != (w0, h0):
            return False
        if probe_audio_sample_rate(p, logger_=logger) != sr0:
            return False
    return True


def _maybe_merge_segments_with_transitions(
    *,
    seg_paths: List[str],
    tmp: str,
    project_name: str,
    segment_transition_ins: Optional[Sequence[Optional[str]]],
    transition_dissolve_sec: float,
    segment_fade_ms: int,
    final_render_opts: Optional[Dict[str, str]] = None,
) -> List[str]:
    if len(seg_paths) <= 1 or not segment_transition_ins:
        return seg_paths
    from app.core.postprod.transitions import compose_with_transitions, resolve_segment_transitions
    from app.models.production import ProductionProfile, TransitionPolicy

    # 用临时 profile 解析 effective transitions
    prof = ProductionProfile(
        transition=TransitionPolicy(
            policy="soft" if any(t in ("cross_dissolve", "fade_in", "fade_out") for t in segment_transition_ins if t) else "hard_cut",
            dissolve_sec=transition_dissolve_sec,
            segment_fade_ms=segment_fade_ms,
        )
    )
    kinds = resolve_segment_transitions(
        len(seg_paths),
        prof,
        plan_transitions=segment_transition_ins,
    )
    # 仅当存在非硬切转场（dissolve/fade）时才走 xfade 重编码路径。
    # 纯硬切（即使带 micro-fade 消爆音）不在此处重编码：交给下方主流程，
    # 让等大段走 concat -c copy、不等大段按画布统一，避免 micro-fade 把全部硬切拖进重编码。
    need = any(k != "hard_cut" for k in kinds)
    if not need:
        return seg_paths
    # 解析统一画布：优先 export 配置（clip_scale_*），无配置时由 compose_with_transitions 取各段最大值兜底。
    target_canvas: Optional[tuple[int, int]] = None
    if seg_paths:
        opts_for_canvas = sanitize_merged_opts_for_final_burn(final_render_opts, seg_paths[0])
        cw, ch = canvas_wh_from_clip_scale_opts(opts_for_canvas, seg_paths[0])
        # canvas_wh_from_clip_scale_opts 在无配置时返回参考段原始分辨率；
        # 仅当配置了非零缩放（即用户/导出明确指定画布）时才作为显式画布传入，
        # 否则让 transitions 兜底取最大值，保持混剪等场景的旧行为。
        sw = to_int(opts_for_canvas, "clip_scale_width", 0)
        sh = to_int(opts_for_canvas, "clip_scale_height", 0)
        if sw > 0 or sh > 0:
            target_canvas = (cw, ch)
    merged = os.path.join(tmp, f"{project_name}__xfade.mp4")
    try:
        compose_with_transitions(
            seg_paths,
            kinds,
            dissolve_sec=transition_dissolve_sec,
            segment_fade_ms=segment_fade_ms,
            out_path=merged,
            render_opts=final_render_opts,
            target_canvas=target_canvas,
        )
        logger.info("段间转场合成完成: %s", merged)
        return [merged]
    except Exception as e:
        logger.warning("段间转场合成失败，回退 composer 多段拼接: %s", e)
        return seg_paths


def compose_final_video(
    *,
    seg_paths: List[str],
    srt_entries: list,
    style: "SubtitleStyle",
    fonts_dir: str,
    tmp: str,
    project_name: str,
    final_render_opts: Dict[str, str],
    normalize_audio: bool,
    prefer_gpu: bool = False,
    segment_transition_ins: Optional[Sequence[Optional[str]]] = None,
    transition_dissolve_sec: float = 0.35,
    segment_fade_ms: int = 80,
) -> str:
    seg_paths = _maybe_merge_segments_with_transitions(
        seg_paths=list(seg_paths),
        tmp=tmp,
        project_name=project_name,
        segment_transition_ins=segment_transition_ins,
        transition_dissolve_sec=transition_dissolve_sec,
        segment_fade_ms=segment_fade_ms,
        final_render_opts=final_render_opts,
    )
    out_path = os.path.join(tmp, f"{project_name}.mp4")

    opts_for_vf = sanitize_merged_opts_for_final_burn(final_render_opts, seg_paths[0])
    extra_filters = build_extra_video_filters(opts_for_vf)

    # 快路径：无字幕、无成片缩放/帧率、各段规格一致 → concat demuxer + copy，避免再整片 x264。
    uniform = _segments_uniform_for_stream_copy(seg_paths)
    if not srt_entries and not extra_filters and uniform:
        concat_list = os.path.join(tmp, "concat.txt")
        write_concat_list(seg_paths, concat_list)
        if not normalize_audio:
            logger.info("FFmpeg concat+copy（无重编码）")
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
                desc="concat+copy",
            )
            return out_path
        a_bitrate = to_int(final_render_opts, "clip_audio_bitrate_kbps", 192)
        logger.info("FFmpeg concat+copy_v+encode_a 完成")
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
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                f"{a_bitrate}k",
                "-avoid_negative_ts",
                "make_zero",
                "-movflags",
                "+faststart",
                out_path,
            ],
            desc="concat+copy_v+encode_a",
        )
        logger.info("FFmpeg concat+copy_v+encode_a 完成")
        return out_path

    # === 两步走（避免「N 段塞进单条 filter_complex + 每段 scale」导致的超时）===
    #
    # 历史问题：带字幕或混合分辨率时，旧实现把所有段塞进一条 filter_complex
    # （concat=n={N} + 每段 scale+pad 到画布 + ass），N 较大（如 42）时单条链
    # 调度极慢甚至超时。
    #
    # 正确做法（与 compose_final_video_moviepy 一致）：
    #   步骤1：先把所有段「分块合并」成单个中间文件（无字幕）。
    #          等大段 → concat demuxer + copy（零重编码）；
    #          不等大 → 分块统一画布重编码（块≤12，块间 copy）。
    #   步骤2：对合并后的单文件做一次 ass overlay + 成片滤镜 + 编码（O(1)，与段数无关）。

    # —— 步骤1：合并画面（无字幕）。 ——
    needs_merge_for_burn = bool(srt_entries) or bool(extra_filters) or (not uniform)
    merged_path = out_path
    if needs_merge_for_burn and len(seg_paths) > 1:
        merged_path = _merge_segments_to_single(
            seg_paths=seg_paths,
            tmp=tmp,
            project_name=f"{project_name}__merged",
            final_render_opts=final_render_opts,
            normalize_audio=normalize_audio,
            prefer_gpu=prefer_gpu,
            segment_transition_ins=segment_transition_ins,
            transition_dissolve_sec=transition_dissolve_sec,
            segment_fade_ms=segment_fade_ms,
        )

    # —— 步骤2：单文件烧字幕 + 成片滤镜 + 编码。 ——
    # 无字幕/无滤镜/已 copy 合并 → 直接返回。
    if not srt_entries and not extra_filters:
        if merged_path != out_path:
            _replace_file(merged_path, out_path)
        return out_path

    # 构建字幕滤镜（作用于单文件）
    vf_filter = "setpts=PTS-STARTPTS"
    if srt_entries:
        video_size = probe_video_dimensions(merged_path, default=(1920, 1080), logger_=logger)
        ass_path = os.path.join(tmp, f"{project_name}__subtitles.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(build_ass(srt_entries, style, video_size))
        logger.info("ASS 字幕已写入: %s (%d 条)", ass_path, len(srt_entries))
        ass_filter_path = ass_path.replace("\\", "/").replace(":", "\\:")
        vf_filter = f"setpts=PTS-STARTPTS,ass='{ass_filter_path}'"
        if fonts_dir and os.path.isdir(fonts_dir):
            safe_fonts = fonts_dir.replace("\\", "/").replace(":", "\\:")
            vf_filter = f"setpts=PTS-STARTPTS,ass='{ass_filter_path}':fontsdir='{safe_fonts}'"
    if extra_filters:
        vf_filter = f"{vf_filter},{','.join(extra_filters)}"

    def _cmd_burn(concat_codec_args: List[str]) -> List[str]:
        return [
            "-i",
            merged_path,
            "-vf",
            vf_filter,
            "-c:a",
            "copy" if not normalize_audio else "aac",
            *concat_codec_args,
            "-avoid_negative_ts",
            "make_zero",
            "-movflags",
            "+faststart",
            out_path,
        ]

    logger.info("FFmpeg 单文件烧字幕（%s 段已合并为单文件）", len(seg_paths))
    _run_export_encode_attempts(
        prefer_gpu=prefer_gpu,
        final_render_opts=final_render_opts,
        normalize_audio=normalize_audio,
        cmd_for_codec=_cmd_burn,
        desc="merge+burn",
    )
    logger.info("FFmpeg 单文件烧字幕完成")
    return out_path


def _merge_segments_to_single(
    *,
    seg_paths: List[str],
    tmp: str,
    project_name: str,
    final_render_opts: Optional[Dict[str, str]],
    normalize_audio: bool,
    prefer_gpu: bool,
    segment_transition_ins: Optional[Sequence[Optional[str]]] = None,
    transition_dissolve_sec: float = 0.35,
    segment_fade_ms: int = 0,
) -> str:
    """
    把多段合并为单个中间文件（不含字幕）。

    - 等大段：concat demuxer + -c copy（零重编码，秒级）。
    - 不等大：调用分块的 compose_with_transitions（纯硬切 + 配置画布，块≤12，块间 copy）。
    """
    out = os.path.join(tmp, f"{project_name}.mp4")

    # 等大 → concat copy
    if _segments_uniform_for_stream_copy(seg_paths):
        concat_list = os.path.join(tmp, f"{project_name}__concat.txt")
        write_concat_list(seg_paths, concat_list)
        if not normalize_audio:
            logger.info("合并画面：concat+copy（%d 段，零重编码）", len(seg_paths))
            run_ffmpeg(
                ["-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", concat_list,
                 "-c", "copy", "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", out],
                desc="merge concat+copy",
            )
            return out
        a_bitrate = to_int(final_render_opts, "clip_audio_bitrate_kbps", 192)
        logger.info("合并画面：concat+copy_v+encode_a（%d 段）", len(seg_paths))
        run_ffmpeg(
            ["-fflags", "+genpts", "-f", "concat", "-safe", "0", "-i", concat_list,
             "-c:v", "copy", "-c:a", "aac", "-b:a", f"{a_bitrate}k",
             "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", out],
            desc="merge concat+copy_v+encode_a",
        )
        return out

    # 不等大 → 分块统一画布（纯硬切 + 配置画布）
    from app.core.postprod.transitions import compose_with_transitions, resolve_segment_transitions
    from app.models.production import ProductionProfile, TransitionPolicy

    n = len(seg_paths)
    # 解析画布：优先 export 配置
    target_canvas: Optional[tuple] = None
    if seg_paths:
        opts_for_canvas = sanitize_merged_opts_for_final_burn(final_render_opts, seg_paths[0])
        sw = to_int(opts_for_canvas, "clip_scale_width", 0)
        sh = to_int(opts_for_canvas, "clip_scale_height", 0)
        if sw > 0 or sh > 0:
            cw, ch = canvas_wh_from_clip_scale_opts(opts_for_canvas, seg_paths[0])
            target_canvas = (cw, ch)

    # 纯硬切 transitions（合并阶段不做视觉转场，转场已在 _maybe_merge 处理或这里统一）
    plan_trans = list(segment_transition_ins) if segment_transition_ins else [None] * n
    policy = "soft" if any(t in ("cross_dissolve", "fade_in", "fade_out") for t in plan_trans if t) else "hard_cut"
    prof = ProductionProfile(
        transition=TransitionPolicy(
            policy=policy,
            dissolve_sec=transition_dissolve_sec,
            segment_fade_ms=segment_fade_ms,
        )
    )
    kinds = resolve_segment_transitions(n, prof, plan_transitions=plan_trans)
    logger.info("合并画面：分块统一画布（%d 段，画布=%s）", n, target_canvas)
    compose_with_transitions(
        seg_paths,
        kinds,
        dissolve_sec=transition_dissolve_sec,
        segment_fade_ms=segment_fade_ms,
        out_path=out,
        render_opts=final_render_opts,
        target_canvas=target_canvas,
    )
    return out


def _replace_file(src: str, dst: str) -> None:
    """跨盘符/占用安全的文件替换。"""
    try:
        os.replace(src, dst)
    except Exception:
        with open(src, "rb") as rf, open(dst, "wb") as wf:
            wf.write(rf.read())


def compose_final_video_moviepy(
    *,
    seg_paths: List[str],
    srt_entries: list,
    style: "SubtitleStyle",
    fonts_dir: str,
    tmp: str,
    project_name: str,
    final_render_opts: Dict[str, str],
    normalize_audio: bool,
    prefer_gpu: bool = False,
    segment_transition_ins: Optional[Sequence[Optional[str]]] = None,
    transition_dissolve_sec: float = 0.35,
    segment_fade_ms: int = 80,
) -> str:
    """
    备用导出方案：先用 FFmpeg 将分段拼成中间 MP4，再用 FFmpeg 做单文件烧字幕/滤镜/编码。

    说明：历史上曾用 MoviePy 做第一步拼接；当某段「视频轨时长 ≫ 音轨时长」时，MoviePy 读音频会在
    t>audio_dur 处抛错（口播快剪等场景易出现）。现第一步改为与 compose_final_video 相同的 FFmpeg
    拼接逻辑（不在此阶段套用 export 缩放/帧率，与旧 MoviePy 第一步语义一致）。
    """
    out_path = os.path.join(tmp, f"{project_name}.mp4")
    concat_path = os.path.join(tmp, f"{project_name}__concat.mp4")

    # 1) FFmpeg 拼接：去掉成片缩放/帧率（留给第 2 步），避免与旧 MoviePy 双阶段语义不一致。
    plain_opts = dict(final_render_opts or {})
    plain_opts["clip_fps"] = "0"
    plain_opts["clip_scale_width"] = "0"
    plain_opts["clip_scale_height"] = "0"
    logger.info("FFmpeg 拼接分段（moviepy 管线第 1 步）: %d 段 -> %s", len(seg_paths), concat_path)
    compose_final_video(
        seg_paths=seg_paths,
        srt_entries=[],
        style=style,
        fonts_dir=fonts_dir,
        tmp=tmp,
        project_name=f"{project_name}__concat",
        final_render_opts=plain_opts,
        normalize_audio=False,
        prefer_gpu=prefer_gpu,
        segment_transition_ins=segment_transition_ins,
        transition_dissolve_sec=transition_dissolve_sec,
        segment_fade_ms=segment_fade_ms,
    )
    logger.info("FFmpeg 拼接完成: %s", concat_path)

    # 2) 单文件阶段：烧字幕 + 额外滤镜 + 编码参数（复用现有 ffmpeg 管线）。
    opts_for_vf = sanitize_merged_opts_for_final_burn(final_render_opts, concat_path)
    extra_filters = build_extra_video_filters(opts_for_vf)

    if srt_entries:
        video_size = probe_video_dimensions(concat_path, default=(1920, 1080), logger_=logger)
        ass_path = os.path.join(tmp, f"{project_name}__subtitles.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(build_ass(srt_entries, style, video_size))
        logger.info("ASS 字幕已写入: %s (%d 条)", ass_path, len(srt_entries))
        ass_filter_path = ass_path.replace("\\", "/").replace(":", "\\:")
        vf_filter = f"setpts=PTS-STARTPTS,ass='{ass_filter_path}'"
        if fonts_dir and os.path.isdir(fonts_dir):
            safe_fonts = fonts_dir.replace("\\", "/").replace(":", "\\:")
            vf_filter = f"setpts=PTS-STARTPTS,ass='{ass_filter_path}':fontsdir='{safe_fonts}'"
    else:
        vf_filter = "setpts=PTS-STARTPTS"

    if extra_filters:
        vf_filter = f"{vf_filter},{','.join(extra_filters)}"

    # 若无需字幕/滤镜且不要求音频编码，则直接返回 MoviePy 拼接结果。
    if (not srt_entries) and (not extra_filters) and (not normalize_audio):
        if concat_path != out_path:
            try:
                os.replace(concat_path, out_path)
            except Exception:
                # Windows 跨盘符/占用时 fallback 到拷贝式
                with open(concat_path, "rb") as rf, open(out_path, "wb") as wf:
                    wf.write(rf.read())
        return out_path

    def _cmd_moviepy_burn(concat_codec_args: List[str]) -> List[str]:
        return [
            "-i",
            concat_path,
            "-vf",
            vf_filter,
            "-c:a",
            "copy" if not normalize_audio else "aac",
            *([] if normalize_audio else []),
            *([] if normalize_audio else []),
            *([] if normalize_audio else []),
            *concat_codec_args,
            "-avoid_negative_ts",
            "make_zero",
            "-movflags",
            "+faststart",
            out_path,
        ]

    logger.info("FFmpeg moviepy_concat+burn（可能多档 GPU/CPU 回退）")
    _run_export_encode_attempts(
        prefer_gpu=prefer_gpu,
        final_render_opts=final_render_opts,
        normalize_audio=normalize_audio,
        cmd_for_codec=_cmd_moviepy_burn,
        desc="moviepy_concat+burn",
    )
    logger.info("FFmpeg moviepy_concat+burn 完成")
    return out_path

