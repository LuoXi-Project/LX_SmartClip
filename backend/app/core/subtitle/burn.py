"""字幕烧录：MoviePy 处理音轨 + FFmpeg 合并 & 硬烧字幕（高性能方案）。"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from app.api.subtitle import SubtitleStyle

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

    # 垂直位置：Alignment 2=底中 8=顶中 5=正中
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
    return header


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
    for entry in srt_entries:
        text = entry["text"].strip().replace("\n", "\\N")
        if not text or entry["end"] <= entry["start"]:
            continue
        lines.append(
            f"Dialogue: 0,{_ass_time(entry['start'])},{_ass_time(entry['end'])},"
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
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg 失败 [{desc}]\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stderr: {result.stderr.decode(errors='replace')[-2000:]}"
        )


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

    Returns:
        (data: bytes, saved_path: str | None)
    """
    from moviepy import AudioFileClip, VideoFileClip
    from fastapi import HTTPException

    with tempfile.TemporaryDirectory() as tmp:

        # ------------------------------------------------------------------
        # 步骤 1：MoviePy 逐段处理音轨，导出临时片段
        # ------------------------------------------------------------------
        seg_paths: List[str] = []
        for i, seg in enumerate(segments):
            info = clip_map.get(seg.clip_id)
            if not info or not os.path.isfile(info["path"] or ""):
                raise HTTPException(404, f"片段不存在: {seg.clip_id}")

            tts_path = (
                os.path.join(tts_audio_dir, os.path.basename(seg.tts_filename))
                if seg.tts_filename
                else None
            )

            seg_out = os.path.join(tmp, f"seg_{i:03d}.mp4")

            if tts_path and os.path.isfile(tts_path):
                # 有 TTS：用 MoviePy 替换音轨后导出
                video = VideoFileClip(info["path"])
                tts_audio = AudioFileClip(tts_path)
                duration = min(video.duration, tts_audio.duration)
                video = video.subclipped(0, duration).with_audio(
                    tts_audio.subclipped(0, duration)
                )
                video.write_videofile(
                    seg_out,
                    codec="libx264",
                    audio_codec="aac",
                    preset="ultrafast",
                    logger=None,
                )
                video.close()
                tts_audio.close()
                logger.info("seg %d (TTS) -> %s (%.2fs)", i + 1, seg_out, duration)
            else:
                # 无 TTS：直接用 FFmpeg 流复制，零损耗极速
                _run_ffmpeg(
                    ["-i", info["path"], "-c", "copy", seg_out],
                    desc=f"copy seg {i+1}",
                )
                logger.info("seg %d (copy) -> %s", i + 1, seg_out)

            seg_paths.append(seg_out)

        # ------------------------------------------------------------------
        # 步骤 2：生成 ASS 字幕文件
        #         需要视频尺寸，从第一个片段探测
        # ------------------------------------------------------------------
        # 用 FFmpeg ffprobe 探测视频尺寸（避免再次用 MoviePy 加载）
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0",
                seg_paths[0],
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        try:
            w_str, h_str = probe.stdout.decode().strip().split(",")
            video_size = (int(w_str), int(h_str))
        except Exception:
            video_size = (1920, 1080)  # 探测失败时的安全回退
            logger.warning("ffprobe 探测视频尺寸失败，回退为 %s", video_size)

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

        _run_ffmpeg(
            [
                "-f", "concat", "-safe", "0", "-i", concat_list,
                "-vf", vf_filter,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
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
