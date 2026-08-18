from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.subtitle import SubtitleStyle

logger = logging.getLogger(__name__)


def _opacity_pct_to_ass_alpha(opacity_pct: int | float) -> int:
    """
    不透明度(0~100) -> ASS Alpha(00~FF)。
    ASS 中 00=不透明，FF=全透明。
    """
    pct = max(0.0, min(100.0, float(opacity_pct)))
    return int(round(255 - (pct / 100.0) * 255))


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
        bg_alpha = _opacity_pct_to_ass_alpha(getattr(style, "background_opacity", 55))
        # 底层背景盒样式：使用 BorderStyle=3 的 box，仅用于承载背景，不覆盖文字描边样式。
        header = header.replace(
            "\n[Events]\n",
            (
                f"Style: BgBox,{style.font_name},{style.font_size},"
                # BorderStyle=3 时，盒子主色取 OutlineColour，Primary 设透明仅保留盒子。
                f"&HFF000000,&HFF000000,&H{bg_alpha:02X}000000,&HFF000000,"
                f"0,0,0,0,100,100,0,0,3,0,0,{alignment},10,10,{margin_v},1\n"
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


def wrap_text_for_ass_display(text: str, max_chars: int) -> str:
    """
    按「每行字数」折行，ASS 内用 \\N 换行。

    与 SRT 时间轴切分独立：同一条字幕事件内可显示多行，不改变起止时间。
    """
    from app.core.subtitle.timeline import (
        split_long_text_at_punctuation,
        strip_subtitle_edge_punctuation,
    )

    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return ""
    n = max(1, int(max_chars) if max_chars else 20)

    lines_out: list[str] = []
    for segment in raw.replace("\\N", "\n").split("\n"):
        # 纵深防御：任何路径漏进来的头尾标点/纯标点行都在显示前剥掉
        part = strip_subtitle_edge_punctuation(segment)
        if not part:
            continue
        if len(part) <= n:
            lines_out.append(part)
            continue
        for chunk in split_long_text_at_punctuation(part, n):
            chunk = strip_subtitle_edge_punctuation(chunk)
            if chunk:
                lines_out.append(chunk)
    return "\\N".join(lines_out)


def _motion_tags(style: "SubtitleStyle", pos_x: int, pos_y: int) -> str:
    template = str(getattr(style, "motion_template", "static") or "static")
    ms = int(getattr(style, "motion_fade_ms", 150) or 150)
    ms = max(50, min(600, ms))
    if template == "fade":
        return f"{{\\fad({ms},{ms})}}"
    if template == "pop":
        half = max(20, ms // 2)
        return (
            f"{{\\fscx50\\fscy50\\alpha&HFF&"
            f"\\t(0,{half},\\fscx100\\fscy100\\alpha&H00&)}}"
        )
    if template == "slide_up":
        y0 = pos_y + 40
        return f"{{\\move({pos_x},{y0},{pos_x},{pos_y},0,{ms})\\fad({ms // 2},{ms // 2})}}"
    return ""


def build_ass(srt_entries: list, style: "SubtitleStyle", video_size: tuple) -> str:
    """将 srt_entries 列表转换为完整 ASS 字幕字符串。"""
    lines = [_style_to_ass_header(style, video_size)]
    pos_x, pos_y = _style_to_ass_pos(style, video_size)
    bg_pad_x = max(0.0, float(getattr(style, "background_pad_x", 6.0)))
    bg_pad_y = max(0.0, float(getattr(style, "background_pad_y", 3.0)))
    max_chars = int(getattr(style, "max_chars_per_line", 20) or 20)
    # 对 BgBox 行单独使用 xbord/ybord，以支持横向与纵向扩展独立控制。
    bg_box_tags = f"{{\\pos({pos_x},{pos_y})\\xbord{bg_pad_x:.1f}\\ybord{bg_pad_y:.1f}}}"
    for entry in srt_entries:
        raw_text = wrap_text_for_ass_display(entry.get("text", ""), max_chars)
        if not raw_text or entry["end"] <= entry["start"]:
            continue
        text = raw_text
        motion = _motion_tags(style, pos_x, pos_y)
        # 用 \pos 锚定坐标，确保导出位置与前端预览一致。
        text = f"{{\\pos({pos_x},{pos_y})}}{motion}{text}"
        if getattr(style, "background", False):
            lines.append(
                f"Dialogue: 0,{_ass_time(entry['start'])},{_ass_time(entry['end'])},"
                f"BgBox,,0,0,0,,{bg_box_tags}{raw_text}"
            )
        lines.append(
            f"Dialogue: 1,{_ass_time(entry['start'])},{_ass_time(entry['end'])},"
            f"Default,,0,0,0,,{text}"
        )
    return "\n".join(lines) + "\n"

