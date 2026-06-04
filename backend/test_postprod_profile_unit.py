# -*- coding: utf-8 -*-
from app.core.postprod.intent import parse_production_intent
from app.core.postprod.presets import get_preset
from app.core.postprod.profile import resolve_production_profile
from app.models.production import ProductionProfilePatch


def test_parse_ecommerce_intent():
    patch = parse_production_intent("帮我做一条电商爆款口播，BGM别抢人声")
    assert patch.preset_id == "ecommerce"
    assert patch.audio is not None
    assert patch.audio.ducking == "strong"


def test_resolve_preset_merge():
    prof = resolve_production_profile(
        explicit=None,
        workspace_prefs={"default_production_preset": "knowledge"},
    )
    assert prof.preset_id == "knowledge"
    assert prof.subtitle_motion.template == "fade"


def test_preset_ecommerce_has_duck():
    p = get_preset("ecommerce")
    assert p.audio.ducking == "strong"
    assert p.subtitle_motion.template == "pop"


def test_video_prep_filter_scales_mismatch():
    from app.core.postprod.transitions import _video_prep_filter

    f = _video_prep_filter(0, 720, 960, 720, 1280)
    assert "scale=720:1280" in f
    assert "pad=720:1280" in f

    same = _video_prep_filter(1, 720, 1280, 720, 1280)
    assert "scale=" not in same
