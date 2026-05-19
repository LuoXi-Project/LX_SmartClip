"""混剪：按概率为各段落分配视觉随机变换，并生成 FFmpeg 滤镜链。"""
from __future__ import annotations

import math
import random
from typing import List, Sequence

from app.models.auto_edit import MixVisualRandomConfig, SegmentPlan
from app.models.subtitle import SegmentVisualEffect


def linear_volume_to_db(volume: float) -> float:
    v = max(0.001, float(volume))
    return 20.0 * math.log10(v)


def build_segment_visual_filters(effect: SegmentVisualEffect | None) -> List[str]:
    if effect is None:
        return []
    parts: List[str] = []
    if effect.zoom is not None and float(effect.zoom) > 1.001:
        z = float(effect.zoom)
        parts.append(f"scale=iw*{z:.4f}:ih*{z:.4f}")
        parts.append(f"crop=iw/{z:.4f}:ih/{z:.4f}")
    if effect.mirror:
        parts.append("hflip")
    if effect.rotation_deg is not None and abs(float(effect.rotation_deg)) > 0.001:
        rad = float(effect.rotation_deg) * math.pi / 180.0
        parts.append(f"rotate={rad:.6f}:ow=iw:oh=ih:c=black")
    if effect.color_intensity is not None:
        i = float(effect.color_intensity)
        parts.append(f"eq=saturation={1.0 + i:.4f}:contrast={1.0 + i * 0.35:.4f}")
        parts.append(f"hue=h={i * 18.0:.2f}")
    return parts


def assign_visual_effects_to_segments(
    segments: Sequence[SegmentPlan],
    cfg: MixVisualRandomConfig,
    *,
    seed: str | None = None,
) -> List[SegmentPlan]:
    """按配置为每个段落独立掷骰，生成可复现（seed）的视觉变换。"""
    if not any(
        (
            cfg.enable_zoom,
            cfg.enable_mirror,
            cfg.enable_rotation,
            cfg.enable_color,
        )
    ):
        return list(segments)

    rng = random.Random(seed or "mix-visual")
    last_zoom_idx = -10**9
    min_gap = max(0, int(cfg.zoom_min_interval_segments or 0))
    out: List[SegmentPlan] = []

    for idx, seg in enumerate(segments):
        eff = SegmentVisualEffect()
        has_any = False

        if cfg.enable_zoom and (idx - last_zoom_idx) >= min_gap:
            if rng.random() < float(cfg.zoom_probability):
                z_lo = float(cfg.zoom_ratio_min)
                z_hi = float(cfg.zoom_ratio_max)
                if z_hi < z_lo:
                    z_lo, z_hi = z_hi, z_lo
                eff.zoom = round(rng.uniform(z_lo, z_hi), 4)
                last_zoom_idx = idx
                has_any = True

        if cfg.enable_mirror and rng.random() < float(cfg.mirror_probability):
            eff.mirror = True
            has_any = True

        if cfg.enable_rotation and rng.random() < float(cfg.rotation_probability):
            r_lo = float(cfg.rotation_deg_min)
            r_hi = float(cfg.rotation_deg_max)
            if r_hi < r_lo:
                r_lo, r_hi = r_hi, r_lo
            eff.rotation_deg = round(rng.uniform(r_lo, r_hi), 3)
            has_any = True

        if cfg.enable_color and rng.random() < float(cfg.color_probability):
            c_lo = float(cfg.color_intensity_min)
            c_hi = float(cfg.color_intensity_max)
            if c_hi < c_lo:
                c_lo, c_hi = c_hi, c_lo
            eff.color_intensity = round(rng.uniform(c_lo, c_hi), 4)
            has_any = True

        if has_any:
            out.append(seg.model_copy(update={"visual_effect": eff}))
        else:
            out.append(seg)

    return out
