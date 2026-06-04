"""成片制作配置（Production Profile）：听感/观感/转场，与 Content Plan 分离。"""
from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field


ProductionPresetId = Literal["auto", "ecommerce", "knowledge", "cinematic", "fast_cut", "custom"]
TransitionPolicyKind = Literal["auto", "hard_cut", "soft"]
LoudnormMode = Literal["off", "fast", "precise"]
DuckingStrength = Literal["off", "light", "medium", "strong"]
SubtitleMotionTemplate = Literal["static", "fade", "pop", "slide_up"]
BeatAlignMode = Literal["off", "light", "strong"]


class TransitionPolicy(BaseModel):
    policy: TransitionPolicyKind = "auto"
    dissolve_sec: float = Field(0.35, ge=0.05, le=2.0)
    segment_fade_ms: int = Field(80, ge=0, le=500, description="硬切时段级 micro-fade，消爆音")
    bookend_fade_in_sec: float = Field(0.25, ge=0.0, le=2.0)
    bookend_fade_out_sec: float = Field(0.45, ge=0.0, le=3.0)


class AudioMasterPolicy(BaseModel):
    loudnorm: LoudnormMode = "fast"
    target_lufs: float = Field(-16.0, ge=-24.0, le=-12.0)
    ducking: DuckingStrength = "medium"
    limiter: bool = True


class BgmProductionPolicy(BaseModel):
    beat_align: BeatAlignMode = "off"
    beat_snap_max_ms: int = Field(180, ge=0, le=400)


class SubtitleMotionPolicy(BaseModel):
    template: SubtitleMotionTemplate = "fade"
    fade_ms: int = Field(150, ge=50, le=600)


class ProductionProfile(BaseModel):
    """会话/方案级制作风格；Agent preset 与用户 Inspector 自选共用。"""

    preset_id: ProductionPresetId = "auto"
    transition: TransitionPolicy = Field(default_factory=TransitionPolicy)
    audio: AudioMasterPolicy = Field(default_factory=AudioMasterPolicy)
    bgm: BgmProductionPolicy = Field(default_factory=BgmProductionPolicy)
    subtitle_motion: SubtitleMotionPolicy = Field(default_factory=SubtitleMotionPolicy)
    locks: List[str] = Field(default_factory=list, description="锁定字段路径，Agent 不得覆盖")

    def merge(self, other: "ProductionProfile", *, respect_locks: bool = True) -> "ProductionProfile":
        """浅合并 other 到 self；locks 中的顶层块不被覆盖。"""
        if not other:
            return self.model_copy(deep=True)
        base = self.model_copy(deep=True)
        locks = set(base.locks or [])
        data = other.model_dump(exclude_unset=True, exclude_none=True)
        if "preset_id" in data and (not respect_locks or "preset_id" not in locks):
            base.preset_id = data["preset_id"]
        for block in ("transition", "audio", "bgm", "subtitle_motion"):
            if block not in data:
                continue
            if respect_locks and block in locks:
                continue
            cur = getattr(base, block)
            patched = cur.model_copy(update=data[block])
            setattr(base, block, patched)
        if "locks" in data and data["locks"]:
            base.locks = list(dict.fromkeys([*(base.locks or []), *data["locks"]]))
        return base

    def human_summary(self) -> str:
        tr = self.transition.policy
        if tr == "auto":
            tr = "自动转场"
        elif tr == "soft":
            tr = f"柔和叠化({self.transition.dissolve_sec:.2f}s)"
        else:
            tr = "硬切"
        duck = {"off": "无", "light": "轻", "medium": "中", "strong": "强"}.get(
            self.audio.ducking, self.audio.ducking
        )
        motion = self.subtitle_motion.template
        beat = self.bgm.beat_align
        ln = self.audio.loudnorm
        return (
            f"预设={self.preset_id} · 转场={tr} · 响度={ln} · "
            f"人声优先(duck)={duck} · 字幕={motion} · 节拍={beat}"
        )


class ProductionProfilePatch(BaseModel):
    """Agent / Inspector 局部更新。"""

    preset_id: Optional[ProductionPresetId] = None
    transition: Optional[TransitionPolicy] = None
    audio: Optional[AudioMasterPolicy] = None
    bgm: Optional[BgmProductionPolicy] = None
    subtitle_motion: Optional[SubtitleMotionPolicy] = None
    locks: Optional[List[str]] = None

    def to_profile(self) -> ProductionProfile:
        d: dict[str, Any] = {}
        if self.preset_id is not None:
            d["preset_id"] = self.preset_id
        if self.transition is not None:
            d["transition"] = self.transition
        if self.audio is not None:
            d["audio"] = self.audio
        if self.bgm is not None:
            d["bgm"] = self.bgm
        if self.subtitle_motion is not None:
            d["subtitle_motion"] = self.subtitle_motion
        if self.locks is not None:
            d["locks"] = self.locks
        return ProductionProfile(**d)
