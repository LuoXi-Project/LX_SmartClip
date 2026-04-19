from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Callable, Dict, List

from app.utils.ffprobe_utils import probe_audio_sample_rate, probe_video_dimensions

from .ass_builder import build_ass
from app.utils.ffmpeg_utils import run_ffmpeg, write_concat_list
from .render_opts import (
    build_extra_video_filters,
    build_render_codec_args,
    force_video_reencode,
    iter_export_gpu_render_attempts,
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
) -> str:
    out_path = os.path.join(tmp, f"{project_name}.mp4")
    target_w, target_h = probe_video_dimensions(seg_paths[0], default=(1920, 1080), logger_=logger)

    if srt_entries:
        video_size = probe_video_dimensions(seg_paths[0], default=(1920, 1080), logger_=logger)
        ass_path = os.path.join(tmp, "subtitles.ass")
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

    extra_filters = build_extra_video_filters(final_render_opts)
    if extra_filters:
        vf_filter = f"{vf_filter},{','.join(extra_filters)}"

    # 注意：dynaudnorm / alimiter 这类实时音频滤镜非常吃 CPU。
    # 这里默认不做任何音频后处理；若上层显式要求 normalize_audio，仅做“音频转码/统一编码器”，不加滤镜。
    audio_post = "anull"

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

    # 慢路径：规格不一致或需要字幕/缩放 → filter_complex concat，逐路按需 scale / resample。
    filter_parts: List[str] = []
    concat_in = []
    for i in range(len(seg_paths)):
        w, h = probe_video_dimensions(seg_paths[i], logger_=logger)
        if w == target_w and h == target_h:
            filter_parts.append(f"[{i}:v]setsar=1,setpts=PTS-STARTPTS[v{i}]")
        else:
            filter_parts.append(
                f"[{i}:v]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
                f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,setpts=PTS-STARTPTS[v{i}]"
            )
        sr = probe_audio_sample_rate(seg_paths[i], logger_=logger)
        if sr == 48000:
            filter_parts.append(f"[{i}:a]asetpts=PTS-STARTPTS[a{i}]")
        else:
            filter_parts.append(
                f"[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS[a{i}]"
            )
        concat_in.append(f"[v{i}][a{i}]")
    filter_parts.append(f"{''.join(concat_in)}concat=n={len(seg_paths)}:v=1:a=1[vcat][acat]")
    filter_parts.append(f"[vcat]{vf_filter}[vout]")
    filter_parts.append(f"[acat]{audio_post}[aout]")
    filter_complex = ";".join(filter_parts)

    cmd = []
    for p in seg_paths:
        cmd += ["-i", p]

    def _cmd_concat_burn(concat_codec_args: List[str]) -> List[str]:
        return [
            *cmd,
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            *concat_codec_args,
            "-avoid_negative_ts",
            "make_zero",
            "-movflags",
            "+faststart",
            out_path,
        ]

    _run_export_encode_attempts(
        prefer_gpu=prefer_gpu,
        final_render_opts=final_render_opts,
        normalize_audio=normalize_audio,
        cmd_for_codec=_cmd_concat_burn,
        desc="concat+burn",
    )
    return out_path


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
) -> str:
    """
    备用导出方案：MoviePy 负责“拼接输出中间文件”，随后用 FFmpeg 做单文件烧字幕/滤镜/编码。

    设计动机：避免对 N 段输入构建复杂 `filter_complex concat`，让成片阶段的命令更简单、易定位问题。
    """
    out_path = os.path.join(tmp, f"{project_name}.mp4")
    concat_path = os.path.join(tmp, f"{project_name}__concat.mp4")

    # 1) MoviePy 拼接（简化调用；实际底层仍会调用 ffmpeg，通常会发生一次转码）。
    # MoviePy 2.x 移除了 `moviepy.editor` 的常用导入路径，做兼容处理。
    try:
        from moviepy.editor import VideoFileClip, concatenate_videoclips  # type: ignore
    except Exception:
        try:
            from moviepy import VideoFileClip, concatenate_videoclips  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"MoviePy 导入失败：{e}")

    logger.info(f"MoviePy 拼接开始: {seg_paths}")
    clips = []
    final_clip = None
    try:
        for p in seg_paths:
            clips.append(VideoFileClip(p))

        # 同规格优先 chain，避免 compose 的额外开销；不一致则 compose。
        target_w, target_h = probe_video_dimensions(seg_paths[0], default=(1920, 1080), logger_=logger)
        same_size = True
        for p in seg_paths[1:]:
            w, h = probe_video_dimensions(p, default=(target_w, target_h), logger_=logger)
            if (w, h) != (target_w, target_h):
                same_size = False
                break
        final_clip = concatenate_videoclips(clips, method="chain" if same_size else "compose")

        v_bitrate = to_int(final_render_opts, "clip_video_bitrate_kbps", 0) or 0
        a_bitrate = to_int(final_render_opts, "clip_audio_bitrate_kbps", 192)

        write_kwargs = {
            "codec": "libx264",
            "audio_codec": "aac",
            "preset": (final_render_opts.get("clip_preset") or "").strip() or "veryfast",
            # 让 ffmpeg 自动选择线程数（通常等价于用满可用核）。
            # 注意：若 MoviePy 侧“供帧”成为瓶颈，CPU 依然可能吃不满。
            "threads": 0,
            "logger": None,
        }
        if v_bitrate > 0:
            write_kwargs["bitrate"] = f"{v_bitrate}k"
        if a_bitrate > 0:
            write_kwargs["audio_bitrate"] = f"{a_bitrate}k"

        final_clip.write_videofile(concat_path, **write_kwargs)
    finally:
        try:
            if final_clip is not None:
                final_clip.close()
        except Exception:
            pass
        for c in clips:
            try:
                c.close()
            except Exception:
                pass

    logger.info("MoviePy 拼接完成: %s", concat_path)

    # 2) 单文件阶段：烧字幕 + 额外滤镜 + 编码参数（复用现有 ffmpeg 管线）。
    extra_filters = build_extra_video_filters(final_render_opts)

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

