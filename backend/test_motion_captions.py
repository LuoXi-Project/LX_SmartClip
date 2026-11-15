"""动效字幕（SRT → kinetic captions）单元测试：模板清单、词级切分、合成生成、管线挂接回退。"""

from __future__ import annotations

import os

import pytest

from app.core.motion import caption_render
from app.models.production import ProductionProfile, ProductionProfilePatch


def test_list_caption_styles_shipped():
    styles = caption_render.list_caption_styles()
    slugs = {s["slug"] for s in styles}
    assert {"karaoke-hormozi", "typewriter", "pop-emphasis", "bottom-bar"} <= slugs
    for s in styles:
        assert s["title"] and s["params"]


def test_split_words_cjk_pairs():
    words = caption_render.split_words("别再买贵的了", 1.0, 3.0)
    assert [w["t"] for w in words] == ["别再", "买贵", "的了"]
    assert words[0]["s"] == pytest.approx(1.0, abs=0.01)
    assert words[-1]["e"] == pytest.approx(3.0, abs=0.01)
    # 无显式强调词且 ≥2 词 → 最长词标 em
    assert any(w["em"] for w in words)


def test_split_words_latin_and_emphasis():
    words = caption_render.split_words("only 99 percent know", 0.0, 2.0)
    assert [w["t"] for w in words] == ["only", "99", "percent", "know"]
    assert next(w for w in words if w["t"] == "99")["em"] is True


def test_build_caption_composition():
    html = caption_render.build_caption_composition(
        [{"start": 0.2, "end": 2.0, "text": "测试字幕内容"}],
        duration=4.5, width=1080, height=1920,
        style_slug="karaoke-hormozi", params={"highlight": "#00ff00"},
    )
    assert "__WIDTH__" not in html and "__DURATION__" not in html
    assert 'data-width="1080"' in html and 'data-duration="4.5"' in html
    assert "window.__CAPTION_DATA__" in html and "测试字幕内容" in html
    assert "background: transparent" in html          # 叠加层必须透明背景
    assert "#00ff00" in html                          # 参数已注入


def test_unknown_template_rejected():
    with pytest.raises(caption_render.renderer.MotionRenderError):
        caption_render.build_caption_composition(
            [{"start": 0, "end": 1, "text": "x"}],
            duration=1, width=100, height=100, style_slug="../evil",
        )


@pytest.mark.asyncio
async def test_apply_captions_falls_back_on_missing_file():
    fn, url = await caption_render.apply_hyperframes_captions(
        "not_exist.mp4", "", srt_content="1\n00:00:00,000 --> 00:00:01,000\nx\n"
    )
    assert fn == "not_exist.mp4"   # 回退原样


@pytest.mark.asyncio
async def test_apply_captions_falls_back_on_empty_srt():
    fn, url = await caption_render.apply_hyperframes_captions(
        "whatever.mp4", "http://x/storage/burned_videos/whatever.mp4", srt_content="  "
    )
    assert fn == "whatever.mp4"


def test_production_profile_captions_policy():
    p = ProductionProfile()
    assert p.captions.engine == "ass" and p.captions.style == "karaoke-hormozi"
    patched = ProductionProfilePatch(captions={"engine": "hyperframes", "style": "typewriter"}).to_profile()
    merged = p.merge(patched)
    assert merged.captions.engine == "hyperframes"
    assert merged.captions.style == "typewriter"
    assert "动效(typewriter)" in merged.human_summary()
    # locks 保护
    locked = ProductionProfile(locks=["captions"])
    kept = locked.merge(patched)
    assert kept.captions.engine == "ass"
