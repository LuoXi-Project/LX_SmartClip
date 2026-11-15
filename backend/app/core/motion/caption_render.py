"""SRT → 动效字幕（kinetic captions）：

1. SRT 句级条目 → 词级时间（CJK 按字、拉丁按词，时长按字数比例内插）+ 强调词标记
2. 套用模板（caption_templates/<slug>/template.html）生成透明背景合成
3. HyperFrames 渲染为带 alpha 的 WebM 叠加层（静态帧由渲染器去重复用，长视频可控）
4. ffmpeg overlay 一次性合成到底片（快）

挂接：ProductionProfile.captions.engine == "hyperframes" 时替代 ASS 硬字幕。
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

from app.core.motion import renderer
from app.core.subtitle.srt import parse_srt

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent / "caption_templates"
_EM_CHARS = set("！!？?…🔥💰✅❗")


def list_caption_styles() -> list[dict[str, Any]]:
    """全部字幕模板清单（供 API/前端选择器与 Agent 使用）。"""
    items = []
    if not TEMPLATES_DIR.is_dir():
        return items
    for child in sorted(TEMPLATES_DIR.iterdir()):
        manifest = child / "manifest.json"
        template = child / "template.html"
        if not (manifest.is_file() and template.is_file()):
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        data["slug"] = data.get("slug") or child.name
        items.append(data)
    return items


def get_caption_template(slug: str) -> str:
    path = TEMPLATES_DIR / slug / "template.html"
    if not (path.is_file() and re.match(r"^[a-z0-9_-]{2,40}$", slug)):
        raise renderer.MotionRenderError(f"字幕模板不存在：{slug}")
    return path.read_text(encoding="utf-8")


# ── SRT → 词级数据 ──────────────────────────────────────────────────────────


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF
        or 0xF900 <= cp <= 0xFAFF or 0x3040 <= cp <= 0x30FF
    )


def split_words(text: str, start: float, end: float) -> list[dict[str, Any]]:
    """句级 → 词级时间（比例内插）。CJK 2 字一组；拉丁按空格。附带强调词标记。"""
    dur = max(0.08, end - start)
    toks = text.split()
    if len(toks) <= 1:
        chars = [c for c in text if not c.isspace()]
        if not chars:
            return []
        # CJK 2 字一组（更像自然词粒度）；非 CJK 长串（如数字/型号）整段一组
        if any(_is_cjk(c) for c in chars):
            toks = ["".join(chars[i:i + 2]) for i in range(0, len(chars), 2)]
        else:
            toks = ["".join(chars)]
    total_units = sum(len(t) for t in toks) or 1
    words: list[dict[str, Any]] = []
    t0 = start
    for tok in toks:
        d = dur * len(tok) / total_units
        words.append({"t": tok, "s": round(t0, 3), "e": round(t0 + d, 3), "em": _is_emphasis(tok)})
        t0 += d
    # 无显式强调词时，组内最长词（≥2 字）作为强调（供 pop-emphasis 用）
    if words and not any(w["em"] for w in words) and len(words) >= 2:
        longest = max(words, key=lambda w: len(w["t"]))
        if len(longest["t"]) >= 2:
            longest["em"] = True
    return words


def _is_emphasis(tok: str) -> bool:
    if any(c.isdigit() for c in tok):
        return True
    return any(c in _EM_CHARS for c in tok)


def build_caption_data(
    srt_entries: list[dict[str, Any]],
    *,
    duration: float,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    groups = []
    for e in srt_entries:
        text = str(e.get("text") or "").strip()
        if not text:
            continue
        words = split_words(text, float(e["start"]), float(e["end"]))
        if words:
            groups.append({
                "start": round(float(e["start"]), 3),
                "end": round(float(e["end"]), 3),
                "text": text,
                "words": words,
            })
    return {"duration": round(max(duration, 0.5), 3), "groups": groups, "params": params or {}}


def build_caption_composition(
    srt_entries: list[dict[str, Any]],
    *,
    duration: float,
    width: int,
    height: int,
    style_slug: str,
    params: dict[str, Any] | None = None,
) -> str:
    """模板 + 数据 → 完整合成 HTML（透明背景，供 WebM 叠加层渲染）。"""
    template = get_caption_template(style_slug)
    data = build_caption_data(srt_entries, duration=duration, params=params)
    font_size = max(24, round(min(width, height) * 0.075))
    position = str((params or {}).get("position") or "bottom")
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = (
        template
        .replace("__WIDTH__", str(int(width)))
        .replace("__HEIGHT__", str(int(height)))
        .replace("__DURATION__", str(round(duration, 3)))
        .replace("__FONT_SIZE__", str(font_size))
        .replace("__POSITION__", position)
    )
    # 数据岛注入：<body> 后、主脚本前（模板主脚本读 window.__CAPTION_DATA__）
    html = html.replace(
        "<body>",
        f'<body><script>window.__CAPTION_DATA__ = {data_json};</script>',
        1,
    )
    return html


# ── 叠加层渲染 + 合成 ──────────────────────────────────────────────────────


async def render_caption_overlay_webm(
    srt_entries: list[dict[str, Any]],
    *,
    duration: float,
    width: int,
    height: int,
    style_slug: str,
    params: dict[str, Any] | None = None,
) -> Path:
    """渲染字幕叠加层为带 alpha 的 WebM（中间产物，不入 renders 库）。"""
    from app.utils.paths import ensure_storage_subpath

    comp_id = renderer.new_composition_id()
    html = build_caption_composition(
        srt_entries, duration=duration, width=width, height=height,
        style_slug=style_slug, params=params,
    )
    project_dir = renderer.save_composition(comp_id, html)
    out_path = Path(ensure_storage_subpath("motion")) / f"{comp_id}_captions.webm"
    final = await renderer.run_render_bridge(
        project_dir.parent, out_path, fps=30, quality="standard", output_format="webm",
    )
    if final.get("t") != "done":
        raise renderer.MotionRenderError(f"字幕叠加层渲染失败：{str(final.get('error'))[:400]}")
    return out_path


def composite_overlay_ffmpeg(video_path: str, overlay_webm: str, out_path: str) -> str:
    """ffmpeg：透明 WebM 叠加到底片（视频重编码一次，音频直通）。"""
    from app.utils.ffmpeg_utils import run_ffmpeg

    run_ffmpeg(
        [
            "-i", video_path,
            "-i", overlay_webm,
            # eof_action=pass：叠加层比底片略短（帧数取整）时不再重复末帧
            "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto:eof_action=pass",
            "-c:v", "libx264", "-crf", "18", "-preset", "medium",
            "-c:a", "copy",
            "-movflags", "+faststart",
            out_path,
        ],
        desc="hyperframes captions overlay",
    )
    return out_path


async def apply_hyperframes_captions(
    filename: str,
    url: str,
    *,
    srt_content: str,
    style_slug: str = "karaoke-hormozi",
    params: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """链式挂接入口：给成片叠动效字幕，返回 (新 filename, 新 url)。失败回退原片。

    与 apply_mix_overlay_if_needed 同构：resolve url → 探测 → 叠加 → 回 (basename, public_url)。
    """
    from app.core.bgm.auto_bgm import resolve_burned_videos_dir_from_public_url
    from app.core.blocking_pool import run_heavy
    from app.utils.ffprobe_utils import probe_duration, probe_video_dimensions
    from app.utils.paths import ensure_storage_subpath, storage_public_url_for_file

    if not (srt_content or "").strip():
        logger.warning("hyperframes 字幕跳过：无 SRT 内容")
        return filename, url
    burn_dir = (
        resolve_burned_videos_dir_from_public_url(url)
        if (url or "").strip()
        else ensure_storage_subpath("burned_videos")
    )
    src = os.path.join(burn_dir, filename)
    if not os.path.isfile(src):
        logger.warning("hyperframes 字幕跳过：成片不存在 %s", src)
        return filename, url

    try:
        entries = parse_srt(srt_content)
        if not entries:
            return filename, url
        duration = probe_duration(src) or max(e["end"] for e in entries)
        width, height = probe_video_dimensions(src)
        overlay = await render_caption_overlay_webm(
            entries, duration=duration, width=width, height=height,
            style_slug=style_slug, params=params,
        )
        out_dir = ensure_storage_subpath("burned_videos")
        stem = Path(filename).stem or "final"
        out_path = os.path.join(out_dir, f"{stem}_hfcap_{uuid.uuid4().hex[:6]}.mp4")
        await run_heavy(composite_overlay_ffmpeg, src, str(overlay), out_path)
        if not os.path.isfile(out_path):
            raise RuntimeError("ffmpeg 叠加未产出文件")
        return os.path.basename(out_path), storage_public_url_for_file(out_path)
    except Exception:
        logger.exception("hyperframes 动效字幕失败，回退原成片")
        return filename, url
