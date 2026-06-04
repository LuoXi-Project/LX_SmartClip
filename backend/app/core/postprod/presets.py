"""制作风格预设：Agent 与用户自选共用。"""
from __future__ import annotations

from app.models.production import (
    AudioMasterPolicy,
    BgmProductionPolicy,
    ProductionPresetId,
    ProductionProfile,
    SubtitleMotionPolicy,
    TransitionPolicy,
)

_PRESETS: dict[ProductionPresetId, ProductionProfile] = {}


def _register(preset_id: ProductionPresetId, profile: ProductionProfile) -> None:
    profile.preset_id = preset_id
    _PRESETS[preset_id] = profile


_register(
    "auto",
    ProductionProfile(
        preset_id="auto",
        transition=TransitionPolicy(policy="auto", dissolve_sec=0.35),
        audio=AudioMasterPolicy(loudnorm="fast", ducking="medium"),
        bgm=BgmProductionPolicy(beat_align="light"),
        subtitle_motion=SubtitleMotionPolicy(template="fade"),
    ),
)

_register(
    "ecommerce",
    ProductionProfile(
        preset_id="ecommerce",
        transition=TransitionPolicy(policy="soft", dissolve_sec=0.25, segment_fade_ms=60),
        audio=AudioMasterPolicy(loudnorm="fast", ducking="strong"),
        bgm=BgmProductionPolicy(beat_align="strong", beat_snap_max_ms=200),
        subtitle_motion=SubtitleMotionPolicy(template="pop", fade_ms=120),
    ),
)

_register(
    "knowledge",
    ProductionProfile(
        preset_id="knowledge",
        transition=TransitionPolicy(policy="soft", dissolve_sec=0.45, segment_fade_ms=100),
        audio=AudioMasterPolicy(loudnorm="fast", ducking="light"),
        bgm=BgmProductionPolicy(beat_align="off"),
        subtitle_motion=SubtitleMotionPolicy(template="fade", fade_ms=200),
    ),
)

_register(
    "cinematic",
    ProductionProfile(
        preset_id="cinematic",
        transition=TransitionPolicy(
            policy="soft",
            dissolve_sec=0.55,
            bookend_fade_in_sec=0.4,
            bookend_fade_out_sec=0.8,
        ),
        audio=AudioMasterPolicy(loudnorm="precise", ducking="light"),
        bgm=BgmProductionPolicy(beat_align="off"),
        subtitle_motion=SubtitleMotionPolicy(template="slide_up", fade_ms=180),
    ),
)

_register(
    "fast_cut",
    ProductionProfile(
        preset_id="fast_cut",
        transition=TransitionPolicy(policy="hard_cut", segment_fade_ms=40),
        audio=AudioMasterPolicy(loudnorm="fast", ducking="medium"),
        bgm=BgmProductionPolicy(beat_align="strong", beat_snap_max_ms=220),
        subtitle_motion=SubtitleMotionPolicy(template="pop", fade_ms=100),
    ),
)

_register(
    "custom",
    ProductionProfile(preset_id="custom"),
)


def get_preset(preset_id: str | None) -> ProductionProfile:
    key = (preset_id or "auto").strip().lower()
    if key not in _PRESETS:
        key = "auto"
    return _PRESETS[key].model_copy(deep=True)


def list_preset_ids() -> list[str]:
    return [k for k in _PRESETS if k != "custom"]
