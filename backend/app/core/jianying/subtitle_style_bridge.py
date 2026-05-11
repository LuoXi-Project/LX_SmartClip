"""将 ``SubtitleStyle`` 转为 pyJianYingDraft 的 ``TextSegment``，供 ``import_srt(..., style_reference=...)`` 使用。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Optional, Tuple

if TYPE_CHECKING:
    from app.models.subtitle import SubtitleStyle


def _hex_to_rgb01(h: str) -> Tuple[float, float, float]:
    s = (h or "#FFFFFF").lstrip("#").strip()
    if len(s) == 6:
        try:
            r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
            return (r / 255.0, g / 255.0, b / 255.0)
        except ValueError:
            pass
    return (1.0, 1.0, 1.0)


def _norm_font_key(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip(), flags=re.UNICODE).lower()


def _resolve_font_type(font_name: str) -> Any:
    """前端字体名 -> pyJianYingDraft.FontType；无法识别则返回 None（剪映侧系统默认）。"""
    from pyJianYingDraft import FontType

    key = _norm_font_key(font_name)
    table = {
        "arial": FontType.Montserrat_Thin,
        "microsoft yahei": FontType.经典雅黑,
        "microsoft yahei ui": FontType.经典雅黑,
        "pingfang sc": FontType.HarmonyOS_Sans_SC_Regular,
        "noto sans sc": FontType.HarmonyOS_Sans_SC_Regular,
        "simhei": FontType.本黑体,
        "simsun": FontType.宋体,
        "stheiti": FontType.台北黑体_Regular,
        "impact": FontType.Anton,
    }
    return table.get(key)


def _jy_text_size_px(font_size: int) -> float:
    """前端字号（像素级 UI）映射到库 ``TextStyle.size``（与 import_srt 默认 5 同量级）。"""
    fs = float(font_size or 24)
    return max(2.0, min(28.0, fs / 10.0))


def _jy_max_line_width(max_chars: int) -> float:
    """按「每行字数」粗估行宽占屏比，与 ``import_srt`` 默认自动换行配合。"""
    n = max(4, min(48, int(max_chars or 20)))
    return max(0.18, min(0.96, n * 0.042))


def _jy_border_width(outline_width: float) -> float:
    """``SubtitleStyle.outline_width`` -> ``TextBorder`` 的 0~100 量纲。"""
    w = float(outline_width or 0.0)
    return max(0.0, min(100.0, w * 14.0))


def _clip_settings_for_subtitle(style: "SubtitleStyle", canvas_w: int, canvas_h: int) -> Any:
    from pyJianYingDraft.segment import ClipSettings

    y_pct = max(0.0, min(100.0, float(getattr(style, "pos_y_pct", 50.0))))
    x_pct = max(0.0, min(100.0, float(getattr(style, "pos_x_pct", 50.0))))
    rel_y = y_pct / 100.0
    transform_y = 0.8 - rel_y * 1.6
    transform_x = (x_pct / 100.0) * 2.0 - 1.0

    half_h = max(float(canvas_h) * 0.5, 1.0)
    mv = max(0.0, float(getattr(style, "margin_v", 0)))
    nudge = min(0.28, mv / half_h * 0.85)
    pos = str(getattr(style, "position", "bottom") or "bottom")
    if pos == "bottom":
        transform_y += nudge
    elif pos == "top":
        transform_y -= nudge

    return ClipSettings(transform_x=transform_x, transform_y=transform_y)


def build_subtitle_style_reference_for_srt(
    style: "SubtitleStyle",
    *,
    canvas_w: int,
    canvas_h: int,
) -> Any:
    """
    构造一条仅用于样式的 ``TextSegment``（文本与时长会被 ``import_srt`` 忽略后重写）。

    使用 ``style_reference`` 以便同时带上描边、背景、阴影等（``text_style`` 参数无法覆盖这些字段）。
    """
    from pyJianYingDraft import TextBorder, TextSegment, TextShadow, TextStyle
    from pyJianYingDraft.text_segment import TextBackground
    from pyJianYingDraft.time_util import Timerange

    fill = _hex_to_rgb01(str(getattr(style, "font_color", "#FFFFFF")))
    outline_rgb = _hex_to_rgb01(str(getattr(style, "outline_color", "#000000")))
    ts = TextStyle(
        size=_jy_text_size_px(int(getattr(style, "font_size", 24) or 24)),
        bold=bool(getattr(style, "bold", False)),
        italic=bool(getattr(style, "italic", False)),
        color=fill,
        align=1,
        auto_wrapping=True,
        max_line_width=_jy_max_line_width(int(getattr(style, "max_chars_per_line", 20) or 20)),
    )
    border: Optional[TextBorder] = None
    ow = float(getattr(style, "outline_width", 0.0) or 0.0)
    if ow > 0.05:
        border = TextBorder(color=outline_rgb, width=_jy_border_width(ow))

    background = None
    if bool(getattr(style, "background", False)):
        op = max(0.0, min(100.0, float(getattr(style, "background_opacity", 55))))
        pad_x = max(0.0, float(getattr(style, "background_pad_x", 6.0)))
        pad_y = max(0.0, float(getattr(style, "background_pad_y", 3.0)))
        bg_w = min(0.55, 0.12 + pad_x * 0.018)
        bg_h = min(0.45, 0.11 + pad_y * 0.022)
        background = TextBackground(
            color="#000000",
            alpha=op / 100.0,
            width=bg_w,
            height=bg_h,
            round_radius=0.02,
        )

    shadow = None
    sh = float(getattr(style, "shadow", 0.0) or 0.0)
    if sh > 0.05:
        shadow = TextShadow(color=(0.0, 0.0, 0.0), distance=min(30.0, 4.0 + sh * 8.0), diffuse=12.0)

    font = _resolve_font_type(str(getattr(style, "font_name", "") or ""))
    clip = _clip_settings_for_subtitle(style, canvas_w, canvas_h)

    return TextSegment(
        " ",
        Timerange(0, 1_000_000),
        font=font,
        style=ts,
        clip_settings=clip,
        border=border,
        background=background,
        shadow=shadow,
    )
