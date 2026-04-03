"""字幕烧录：MoviePy 处理音轨 + FFmpeg 合并 & 硬烧字幕（高性能方案）。"""
from __future__ import annotations

import logging
import math
import os
import subprocess
import tempfile
from typing import TYPE_CHECKING, Dict, List, Optional

from app.utils.paths import get_render_tmp_base_dir
from app.utils.ffprobe_utils import probe_duration, probe_video_dimensions

if TYPE_CHECKING:
    from app.models.subtitle import SubtitleStyle

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ASS 字幕生成（FFmpeg subtitles filter 原生支持，比 SRT 更丰富的样式控制）
# ---------------------------------------------------------------------------

def _style_to_ass_header(style: "SubtitleStyle", video_size: tuple) -> str:
    """将 SubtitleStyle 转换为 ASS [V4+ Styles] 段。"""
    vw, vh = video_size

    def hex_to_ass(h: str, alpha: int = 0) -> str:
        """#RRGGBB -> &HAABBGGRR (ASS 颜色格式，AA=透明度 00=不透明)"""
        h = h.lstrip("#")
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"&H{alpha:02X}{b}{g}{r}"

    # 垂直位置：Alignment 2=底中 8=顶中 5=正中（兼容旧字段）
    if style.position == "bottom":
        alignment = 2
        margin_v = style.margin_v
    elif style.position == "top":
        alignment = 8
        margin_v = style.margin_v
    else:
        alignment = 5
        margin_v = 0

    bold_val = -1 if style.bold else 0
    italic_val = -1 if style.italic else 0
    primary = hex_to_ass(style.font_color)
    outline_c = hex_to_ass(style.outline_color)
    shadow_c = "&H80000000"  # 半透明黑色阴影

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {vw}\n"
        f"PlayResY: {vh}\n"
        "WrapStyle: 0\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        f"Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{style.font_name},{style.font_size},"
        f"{primary},&H00FFFFFF,{outline_c},{shadow_c},"
        f"{bold_val},{italic_val},0,0,"
        f"100,100,0,0,1,{style.outline_width:.1f},{style.shadow:.1f},"
        f"{alignment},10,10,{margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    if getattr(style, "background", False):
        # 底层背景盒样式：使用 BorderStyle=3 的 box，仅用于承载背景，不覆盖文字描边样式。
        header = header.replace(
            "\n[Events]\n",
            (
                f"Style: BgBox,{style.font_name},{style.font_size},"
                # BorderStyle=3 时，盒子主色取 OutlineColour；此前误配为全透明导致背景不可见。
                "&HFF000000,&HFF000000,&H70000000,&HFF000000,"
                f"0,0,0,0,100,100,0,0,3,6,0,{alignment},10,10,{margin_v},1\n"
                "\n[Events]\n"
            ),
        )
    return header


def _style_to_ass_pos(style: "SubtitleStyle", video_size: tuple) -> tuple[int, int]:
    """将百分比坐标映射为 ASS 像素坐标。"""
    vw, vh = video_size
    x_pct = max(0.0, min(100.0, float(getattr(style, "pos_x_pct", 50.0))))
    y_pct = max(0.0, min(100.0, float(getattr(style, "pos_y_pct", 90.0))))
    x = int(round(vw * x_pct / 100.0))
    y = int(round(vh * y_pct / 100.0))
    return x, y


def _ass_time(s: float) -> str:
    """秒 -> ASS 时间格式 H:MM:SS.cc"""
    cs = int(round(s * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    sec, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"


def build_ass(srt_entries: list, style: "SubtitleStyle", video_size: tuple) -> str:
    """将 srt_entries 列表转换为完整 ASS 字幕字符串。"""
    lines = [_style_to_ass_header(style, video_size)]
    pos_x, pos_y = _style_to_ass_pos(style, video_size)
    for entry in srt_entries:
        text = entry["text"].strip().replace("\n", "\\N")
        if not text or entry["end"] <= entry["start"]:
            continue
        # 用 \pos 锚定坐标，确保导出位置与前端预览一致。
        text = f"{{\\pos({pos_x},{pos_y})}}{text}"
        if getattr(style, "background", False):
            lines.append(
                f"Dialogue: 0,{_ass_time(entry['start'])},{_ass_time(entry['end'])},"
                f"BgBox,,0,0,0,,{text}"
            )
        lines.append(
            f"Dialogue: 1,{_ass_time(entry['start'])},{_ass_time(entry['end'])},"
            f"Default,,0,0,0,,{text}"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# FFmpeg 工具
# ---------------------------------------------------------------------------

def _run_ffmpeg(args: List[str], desc: str = "") -> None:
    """运行 FFmpeg 命令，失败时抛出 RuntimeError 并附带 stderr 输出。"""
    cmd = ["ffmpeg", "-y"] + args
    logger.info("FFmpeg%s: %s", f" [{desc}]" if desc else "", " ".join(cmd))
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=3600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg 失败 [{desc}]\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stderr: {result.stderr.decode(errors='replace')[-2000:]}"
        )


def _write_concat_list(paths: List[str], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        for p in paths:
            f.write(f"file '{p.replace(chr(92), '/')}' \n")


def _to_int(opts: Dict[str, str], key: str, default: int) -> int:
    try:
        return int(float((opts.get(key) or "").strip() or default))
    except Exception:
        return default


def _to_float(opts: Dict[str, str], key: str, default: float) -> float:
    try:
        return float((opts.get(key) or "").strip() or default)
    except Exception:
        return default


def _build_render_codec_args(render_opts: Optional[Dict[str, str]] = None) -> List[str]:
    """根据配置构建编码参数，避免硬编码渲染质量。"""
    opts = render_opts or {}
    vcodec = (opts.get("clip_vcodec") or "libx264").strip()
    acodec = (opts.get("clip_acodec") or "aac").strip()
    preset = (opts.get("clip_preset") or "veryfast").strip()
    pix_fmt = (opts.get("clip_pix_fmt") or "yuv420p").strip()
    crf = _to_int(opts, "clip_crf", 23)
    v_bitrate_kbps = _to_int(opts, "clip_video_bitrate_kbps", 0)
    a_bitrate_kbps = _to_int(opts, "clip_audio_bitrate_kbps", 128)

    args: List[str] = ["-c:v", vcodec]
    if vcodec in ("libx264", "libx265") and preset:
        args += ["-preset", preset]
    if v_bitrate_kbps > 0:
        args += ["-b:v", f"{v_bitrate_kbps}k"]
    elif crf >= 0 and vcodec in ("libx264", "libx265"):
        args += ["-crf", str(crf)]
    if pix_fmt:
        args += ["-pix_fmt", pix_fmt]

    args += ["-c:a", acodec]
    if a_bitrate_kbps > 0 and acodec != "copy":
        args += ["-b:a", f"{a_bitrate_kbps}k"]
    return args


def _build_extra_video_filters(render_opts: Optional[Dict[str, str]] = None) -> List[str]:
    """根据配置构建额外视频滤镜（缩放/帧率）。"""
    opts = render_opts or {}
    fps = _to_float(opts, "clip_fps", 0.0)
    scale_w = _to_int(opts, "clip_scale_width", 0)
    scale_h = _to_int(opts, "clip_scale_height", 0)

    filters: List[str] = []
    if scale_w > 0 or scale_h > 0:
        sw = scale_w if scale_w > 0 else -2
        sh = scale_h if scale_h > 0 else -2
        filters.append(f"scale={sw}:{sh}:flags=lanczos")
    if fps > 0:
        filters.append(f"fps={fps}")
    return filters


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def burn_to_mp4(
    segments,
    srt_entries: list,
    clip_map: dict,
    style: "SubtitleStyle",
    project_name: str,
    tts_audio_dir: str,
    fonts_dir: str,
    render_opts: Optional[Dict[str, str]] = None,
    normalize_audio: bool = False,
    output_dir: str = None,
) -> tuple:
    """
    合并视频片段、替换 TTS 音轨、硬烧字幕，导出为 MP4 字节数据。

    流程:
        1. MoviePy 逐段处理（剪切 + TTS 音轨替换）→ 导出临时片段文件
        2. 生成 ASS 字幕文件
        3. FFmpeg concat + subtitles filter 一步完成合并 & 字幕烧录
        4. 流式读取返回字节（避免大文件 OOM）

    Args:
        segments:      SubtitleSegmentInput 列表
        srt_entries:   parse_srt 解析结果 [{start, end, text}, ...]
        clip_map:      {clip_id: {path, dur}} 来自 DB 查询
        style:         SubtitleStyle 样式
        project_name:  输出文件名（不含扩展名）
        tts_audio_dir: TTS 音频目录
        fonts_dir:     字体目录（供 FFmpeg subtitles filter 引用，可选）
        normalize_audio: 是否对最终音频做归一化/限幅

    Returns:
        (data: bytes, saved_path: str | None)
    """
    from fastapi import HTTPException

    tmp_base_dir = get_render_tmp_base_dir()
    with tempfile.TemporaryDirectory(dir=tmp_base_dir, prefix="burn_") as tmp:
        logger.info("临时渲染目录: %s", tmp)

        # ------------------------------------------------------------------
        # 步骤 1：MoviePy 逐段处理音轨，导出临时片段
        # ------------------------------------------------------------------
        seg_paths: List[str] = []
        for i, seg in enumerate(segments):
            raw_ids = list(getattr(seg, "clip_ids", None) or [])
            if not raw_ids and getattr(seg, "clip_id", None):
                raw_ids = [seg.clip_id]
            clip_ids = list(dict.fromkeys([cid for cid in raw_ids if cid]))
            if not clip_ids:
                raise HTTPException(400, f"片段缺少 clip_id: seg_{i + 1}")

            infos = []
            for cid in clip_ids:
                info = clip_map.get(cid)
                if not info or not os.path.isfile(info["path"] or ""):
                    raise HTTPException(404, f"片段不存在: {cid}")
                infos.append(info)

            tts_path = (
                os.path.join(tts_audio_dir, os.path.basename(seg.tts_filename))
                if seg.tts_filename
                else None
            )

            seg_out = os.path.join(tmp, f"seg_{i:03d}.mp4")
            # 用户可控段落时长（秒）：用于裁剪该段输出，让字幕时间轴与画面严格对齐
            desired_dur = None
            try:
                desired_dur = float(getattr(seg, "duration_sec", None)) if getattr(seg, "duration_sec", None) is not None else None
            except Exception:
                desired_dur = None
            if desired_dur is not None and desired_dur <= 0:
                desired_dur = None

            if tts_path and os.path.isfile(tts_path):
                # 有 TTS：先顺序使用候选 clip 组；若总时长不足，再按整组循环补齐。
                audio_dur = probe_duration(tts_path, log_on_failure=True)
                if desired_dur is not None and desired_dur > 0:
                    # 缩短 TTS：会截断音频与字幕；放长则没有意义（仍按实际 TTS 裁切）
                    audio_dur = min(audio_dur, desired_dur) if audio_dur > 0 else desired_dur
                video_dur = sum(
                    float(info.get("dur") or probe_duration(info["path"], log_on_failure=True) or 0.0)
                    for info in infos
                )
                if audio_dur <= 0:
                    raise HTTPException(400, f"TTS 音频无效: {seg.tts_filename}")
                if video_dur <= 0:
                    raise HTTPException(400, f"视频片段无效: {','.join(clip_ids)}")

                loop_count = max(0, math.ceil(audio_dur / video_dur) - 1)
                concat_list_path = os.path.join(tmp, f"seg_{i:03d}_concat.txt")
                _write_concat_list([info["path"] for info in infos], concat_list_path)
                seg_codec_args = _build_render_codec_args(render_opts)
                seg_filter_parts = _build_extra_video_filters(render_opts)
                seg_vf_args = ["-vf", ",".join(seg_filter_parts)] if seg_filter_parts else []
                _run_ffmpeg(
                    [
                        "-stream_loop", str(loop_count),
                        "-f", "concat",
                        "-safe", "0",
                        "-i", concat_list_path,
                        "-i", tts_path,
                        "-map", "0:v:0",
                        "-map", "1:a:0",
                        "-t", f"{audio_dur:.3f}",
                        *seg_vf_args,
                        *seg_codec_args,
                        "-shortest",
                        "-movflags", "+faststart",
                        seg_out,
                    ],
                    desc=f"fit seg {i+1} to tts",
                )
                logger.info(
                    "seg %d (TTS对齐) -> %s (audio=%.2fs, video_group=%.2fs, clips=%d, loop=%d)",
                    i + 1,
                    seg_out,
                    audio_dur,
                    video_dur,
                    len(clip_ids),
                    loop_count,
                )
            else:
                # 无 TTS：允许按 desired_dur 裁剪该段（需要重编码以保证裁剪准确）
                source_total_dur = sum(float(info.get("dur") or 0.0) for info in infos) or None
                trim_dur = None
                if desired_dur is not None and desired_dur > 0:
                    trim_dur = desired_dur
                    if source_total_dur is not None and source_total_dur > 0:
                        trim_dur = min(trim_dur, source_total_dur)

                if len(infos) == 1:
                    if trim_dur is None:
                        # 无裁剪：直接复制，最快
                        _run_ffmpeg(
                            ["-i", infos[0]["path"], "-c", "copy", seg_out],
                            desc=f"copy seg {i+1}",
                        )
                    else:
                        seg_codec_args = _build_render_codec_args(render_opts)
                        seg_filter_parts = _build_extra_video_filters(render_opts)
                        seg_vf_args = ["-vf", ",".join(seg_filter_parts)] if seg_filter_parts else []
                        clip_start = getattr(seg, "clip_start_sec", None)
                        clip_start_v = None
                        try:
                            clip_start_v = float(clip_start) if clip_start is not None else None
                        except Exception:
                            clip_start_v = None

                        # 支持按句子区间裁剪（精确优先：-ss 放在 -i 之后）
                        if clip_start_v is not None and clip_start_v > 0:
                            _run_ffmpeg(
                                [
                                    "-i",
                                    infos[0]["path"],
                                    "-ss",
                                    f"{clip_start_v:.3f}",
                                    "-t",
                                    f"{trim_dur:.3f}",
                                    *seg_vf_args,
                                    *seg_codec_args,
                                    "-movflags",
                                    "+faststart",
                                    seg_out,
                                ],
                                desc=f"trim seg {i+1} (with clip_start)",
                            )
                        else:
                            _run_ffmpeg(
                                [
                                    "-i",
                                    infos[0]["path"],
                                    "-t",
                                    f"{trim_dur:.3f}",
                                    *seg_vf_args,
                                    *seg_codec_args,
                                    "-movflags",
                                    "+faststart",
                                    seg_out,
                                ],
                                desc=f"trim seg {i+1}",
                            )
                else:
                    concat_list_path = os.path.join(tmp, f"seg_{i:03d}_concat.txt")
                    _write_concat_list([info["path"] for info in infos], concat_list_path)
                    if trim_dur is None:
                        _run_ffmpeg(
                            ["-f", "concat", "-safe", "0", "-i", concat_list_path, "-c", "copy", seg_out],
                            desc=f"concat seg {i+1}",
                        )
                    else:
                        seg_codec_args = _build_render_codec_args(render_opts)
                        seg_filter_parts = _build_extra_video_filters(render_opts)
                        seg_vf_args = ["-vf", ",".join(seg_filter_parts)] if seg_filter_parts else []
                        _run_ffmpeg(
                            ["-f", "concat", "-safe", "0", "-i", concat_list_path, "-t", f"{trim_dur:.3f}", *seg_vf_args, *seg_codec_args, "-movflags", "+faststart", seg_out],
                            desc=f"concat+trim seg {i+1}",
                        )
                logger.info(
                    "seg %d (no-tts) -> %s (clips=%d, desired_dur=%s)",
                    i + 1,
                    seg_out,
                    len(clip_ids),
                    f'{desired_dur:.3f}' if desired_dur else "-",
                )

            seg_paths.append(seg_out)

        # ------------------------------------------------------------------
        # 步骤 2：生成 ASS 字幕文件
        #         需要视频尺寸，从第一个片段探测
        # ------------------------------------------------------------------
        # 用 ffprobe 探测视频尺寸（避免再次用 MoviePy 加载）
        video_size = probe_video_dimensions(seg_paths[0], default=(1920, 1080), logger_=logger)

        ass_path = os.path.join(tmp, "subtitles.ass")
        ass_content = build_ass(srt_entries, style, video_size)
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)
        logger.info("ASS 字幕已写入: %s (%d 条)", ass_path, len(srt_entries))

        # ------------------------------------------------------------------
        # 步骤 3：FFmpeg concat + subtitles filter 一步合并 & 烧录
        # ------------------------------------------------------------------
        concat_list = os.path.join(tmp, "concat.txt")
        with open(concat_list, "w", encoding="utf-8") as f:
            for p in seg_paths:
                # Windows 路径需要用正斜杠或转义
                f.write(f"file '{p.replace(chr(92), '/')}' \n")

        out_path = os.path.join(tmp, f"{project_name}.mp4")

        # subtitles filter 路径在 Windows 下需特殊转义冒号
        ass_filter_path = ass_path.replace("\\", "/").replace(":", "\\:")

        # 字体目录参数（fontsdir 让 FFmpeg 优先使用项目字体）
        vf_filter = f"ass='{ass_filter_path}'"
        if fonts_dir and os.path.isdir(fonts_dir):
            safe_fonts = fonts_dir.replace("\\", "/").replace(":", "\\:")
            vf_filter = f"ass='{ass_filter_path}':fontsdir='{safe_fonts}'"
        extra_filters = _build_extra_video_filters(render_opts)
        if extra_filters:
            vf_filter = f"{vf_filter},{','.join(extra_filters)}"
        af_filter = None
        concat_codec_args = _build_render_codec_args(render_opts)
        if normalize_audio:
            # 需要音频滤镜时必须重编码，避免 clip_acodec=copy 导致滤镜失效
            af_filter = "dynaudnorm=f=150:g=15,alimiter=limit=0.98"
            norm_render_opts = dict(render_opts or {})
            norm_render_opts["clip_acodec"] = "aac"
            concat_codec_args = _build_render_codec_args(norm_render_opts)

        _run_ffmpeg(
            [
                "-f", "concat", "-safe", "0", "-i", concat_list,
                "-vf", vf_filter,
                *([] if not af_filter else ["-af", af_filter]),
                *concat_codec_args,
                "-movflags", "+faststart",
                out_path,
            ],
            desc="concat+burn",
        )
        logger.info("导出 MP4 完成: %s", out_path)

        # ------------------------------------------------------------------
        # 步骤 4：持久化保存（若提供 output_dir）并返回
        # ------------------------------------------------------------------
        with open(out_path, "rb") as f:
            data = f.read()

        saved_path = None
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            saved_path = os.path.join(output_dir, f"{project_name}.mp4")
            with open(saved_path, "wb") as f:
                f.write(data)
            logger.info("持久化保存: %s", saved_path)

    return data, saved_path
