"""自然语言 → Production Profile 增量（规则引擎，Agent 免参数）。"""
from __future__ import annotations

import re
from typing import Any

from app.models.production import (
    AudioMasterPolicy,
    BgmProductionPolicy,
    ProductionProfilePatch,
    SubtitleMotionPolicy,
    TransitionPolicy,
)


def _patch(**kwargs: Any) -> ProductionProfilePatch:
    return ProductionProfilePatch(**kwargs)


_RULES: list[tuple[re.Pattern[str], ProductionProfilePatch]] = [
    (re.compile(r"(电商|带货|爆款|种草|促销)"), _patch(preset_id="ecommerce")),
    (re.compile(r"(知识|科普|教程|讲解|课堂)"), _patch(preset_id="knowledge")),
    (re.compile(r"(纪录片|电影感|叙事|文艺|cinematic)"), _patch(preset_id="cinematic")),
    (re.compile(r"(卡点|快剪|混剪|节奏快|高燃)"), _patch(preset_id="fast_cut")),
    (re.compile(r"转场.{0,6}(柔|软|淡|慢)"), _patch(transition=TransitionPolicy(policy="soft"))),
    (re.compile(r"转场.{0,6}(硬|利|快|切)"), _patch(transition=TransitionPolicy(policy="hard_cut"))),
    (re.compile(r"(不要|别).{0,4}转场"), _patch(transition=TransitionPolicy(policy="hard_cut"))),
    (re.compile(r"BGM.{0,8}(轻|小|低|别抢|不要抢)"), _patch(audio=AudioMasterPolicy(ducking="strong"))),
    (re.compile(r"BGM.{0,8}(响|大|突出)"), _patch(audio=AudioMasterPolicy(ducking="light"))),
    (re.compile(r"(人声优先|duck|闪避)"), _patch(audio=AudioMasterPolicy(ducking="strong"))),
    (re.compile(r"(卡节拍|对节拍|踩点|beat)"), _patch(bgm=BgmProductionPolicy(beat_align="strong"))),
    (re.compile(r"字幕.{0,6}(弹|跳|冲击)"), _patch(subtitle_motion=SubtitleMotionPolicy(template="pop"))),
    (re.compile(r"字幕.{0,6}(淡|柔|稳)"), _patch(subtitle_motion=SubtitleMotionPolicy(template="fade"))),
    (re.compile(r"字幕.{0,6}(滑|上升)"), _patch(subtitle_motion=SubtitleMotionPolicy(template="slide_up"))),
    (re.compile(r"字幕.{0,6}(静|不要动)"), _patch(subtitle_motion=SubtitleMotionPolicy(template="static"))),
    (re.compile(r"(响度|音量).{0,6}(统一|正常)"), _patch(audio=AudioMasterPolicy(loudnorm="fast"))),
    (re.compile(r"跟上次一样|保持风格|不变"), _patch()),  # no-op marker
]


def parse_production_intent(text: str) -> ProductionProfilePatch:
    """从用户话里提取制作意图 patch；多条规则可叠加（后者覆盖同块）。"""
    t = (text or "").strip()
    if not t:
        return ProductionProfilePatch()
    merged = ProductionProfilePatch()
    for pat, patch in _RULES:
        if pat.search(t):
            if patch.preset_id is not None:
                merged.preset_id = patch.preset_id
            if patch.transition is not None:
                merged.transition = patch.transition
            if patch.audio is not None:
                merged.audio = patch.audio
            if patch.bgm is not None:
                merged.bgm = patch.bgm
            if patch.subtitle_motion is not None:
                merged.subtitle_motion = patch.subtitle_motion
    return merged


def intent_summary(text: str) -> str:
    patch = parse_production_intent(text)
    parts: list[str] = []
    if patch.preset_id:
        parts.append(f"预设→{patch.preset_id}")
    if patch.transition:
        parts.append(f"转场→{patch.transition.policy}")
    if patch.audio and patch.audio.ducking:
        parts.append(f"duck→{patch.audio.ducking}")
    if patch.bgm and patch.bgm.beat_align:
        parts.append(f"节拍→{patch.bgm.beat_align}")
    if patch.subtitle_motion:
        parts.append(f"字幕→{patch.subtitle_motion.template}")
    return "、".join(parts) if parts else "未识别到制作参数调整"
