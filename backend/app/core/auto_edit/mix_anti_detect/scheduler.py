"""防检测调度：随机种子、循环增益、蜘蛛爬行参数生成。"""
from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.models.auto_edit import MixAntiDetectConfig


@dataclass
class CrawlKeyframe:
    frame_idx: int
    dx: float
    dy: float


@dataclass
class RuntimeParams:
    seed: str
    iteration: int
    gain: float
    displacement_px: float
    color_shift: float
    scale_jitter: float
    pixel_noise_sigma: float
    crawl_amplitude: float
    crawl_path: list[CrawlKeyframe] = field(default_factory=list)
    speed_factors: list[float] = field(default_factory=list)
    pitch_cents: float = 0.0
    reverb_mix: float = 0.0
    noise_floor_db: float = -46.0


def _smooth_crawl_path(
    rng: random.Random,
    total_frames: int,
    amplitude: float,
    *,
    segments: int = 6,
) -> list[CrawlKeyframe]:
    """蜘蛛爬行：分段随机目标点 + 三次平滑插值。"""
    if total_frames <= 1 or amplitude <= 0:
        return [CrawlKeyframe(0, 0.0, 0.0)]

    seg_count = max(2, min(segments, total_frames // 30 + 2))
    anchors: list[tuple[int, float, float]] = [(0, 0.0, 0.0)]
    for i in range(1, seg_count):
        fi = int(total_frames * i / seg_count)
        anchors.append(
            (
                fi,
                rng.uniform(-amplitude, amplitude),
                rng.uniform(-amplitude, amplitude),
            )
        )
    anchors.append((max(0, total_frames - 1), 0.0, 0.0))

    def _interp(t: float, p0: float, p1: float, p2: float, p3: float) -> float:
        t2 = t * t
        t3 = t2 * t
        return 0.5 * (
            (2 * p1)
            + (-p0 + p2) * t
            + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
            + (-p0 + 3 * p1 - 3 * p2 + p3) * t3
        )

    path: list[CrawlKeyframe] = []
    for fi in range(total_frames):
        seg_i = 0
        for j in range(len(anchors) - 1):
            if anchors[j][0] <= fi <= anchors[j + 1][0]:
                seg_i = j
                break
        a0 = anchors[max(0, seg_i - 1)]
        a1 = anchors[seg_i]
        a2 = anchors[min(len(anchors) - 1, seg_i + 1)]
        a3 = anchors[min(len(anchors) - 1, seg_i + 2)]
        span = max(1, a2[0] - a1[0])
        t = (fi - a1[0]) / span
        dx = _interp(t, a0[1], a1[1], a2[1], a3[1])
        dy = _interp(t, a0[2], a1[2], a2[2], a3[2])
        path.append(CrawlKeyframe(fi, dx, dy))
    return path


class AntiDetectScheduler:
    def __init__(self, cfg: MixAntiDetectConfig) -> None:
        self.cfg = cfg
        base_seed = (cfg.scheduler.random_seed or "").strip() or uuid.uuid4().hex[:12]
        self.base_seed = base_seed

    def iterations(self) -> int:
        return max(1, int(self.cfg.scheduler.loop_iterations))

    def output_format(self) -> str:
        fmt = (self.cfg.scheduler.output_format or "mkv").strip().lower()
        return fmt if fmt in ("mkv", "mp4") else "mkv"

    def build_params(
        self,
        *,
        iteration: int,
        total_frames: int,
        audio_duration_sec: float,
    ) -> RuntimeParams:
        gain = float(self.cfg.scheduler.loop_gain) ** max(0, iteration - 1)
        rng = random.Random(f"{self.base_seed}:iter{iteration}")

        v = self.cfg.video
        a = self.cfg.audio

        disp = 0.0
        if v.enabled and v.enable_displacement:
            disp = rng.uniform(0.4, 1.0) * float(v.displacement_px_max) * gain

        color = 0.0
        if v.enabled and v.enable_color_shift:
            sign = -1.0 if rng.random() < 0.5 else 1.0
            color = sign * rng.uniform(0.3, 1.0) * float(v.color_shift_max) * gain

        scale = 0.0
        if v.enabled and v.enable_scale_jitter:
            scale = rng.uniform(0.2, 1.0) * float(v.scale_jitter_max) * gain

        noise_sigma = 0.0
        if v.enabled and v.enable_pixel_noise:
            noise_sigma = rng.uniform(0.5, 1.0) * float(v.pixel_noise_sigma) * math.sqrt(gain)

        crawl_amp = 0.0
        crawl_path: list[CrawlKeyframe] = []
        if v.enabled and v.enable_crawl:
            crawl_amp = rng.uniform(0.5, 1.0) * float(v.crawl_amplitude_px) * gain
            crawl_path = _smooth_crawl_path(rng, total_frames, crawl_amp)

        speed_factors: list[float] = []
        if a.enabled and a.enable_segment_speed and audio_duration_sec > 1.0:
            seg_n = max(3, min(12, int(audio_duration_sec / 4.0) + 2))
            base_var = float(a.speed_variation) * gain
            for _ in range(seg_n):
                speed_factors.append(1.0 + rng.uniform(-base_var, base_var))

        pitch_cents = 0.0
        reverb = 0.0
        if a.enabled and a.enable_reverb_pitch:
            pitch_cents = float(a.pitch_semitones) * 100.0 * rng.uniform(0.6, 1.0) * gain
            reverb = min(0.45, float(a.reverb_mix) * rng.uniform(0.7, 1.2) * gain)

        noise_db = float(a.noise_floor_db)
        if a.enabled and a.enable_fingerprint_obfusc:
            noise_db += rng.uniform(-2.0, 2.0)

        return RuntimeParams(
            seed=f"{self.base_seed}:{iteration}",
            iteration=iteration,
            gain=gain,
            displacement_px=disp,
            color_shift=color,
            scale_jitter=scale,
            pixel_noise_sigma=noise_sigma,
            crawl_amplitude=crawl_amp,
            crawl_path=crawl_path,
            speed_factors=speed_factors,
            pitch_cents=pitch_cents,
            reverb_mix=reverb,
            noise_floor_db=noise_db,
        )

    def summary_dict(self, params: RuntimeParams) -> dict[str, Any]:
        return {
            "seed": params.seed,
            "iteration": params.iteration,
            "gain": round(params.gain, 4),
            "displacement_px": round(params.displacement_px, 3),
            "color_shift": round(params.color_shift, 4),
            "scale_jitter": round(params.scale_jitter, 4),
            "pixel_noise_sigma": round(params.pixel_noise_sigma, 3),
            "crawl_amplitude": round(params.crawl_amplitude, 3),
            "speed_segments": len(params.speed_factors),
            "pitch_cents": round(params.pitch_cents, 2),
            "reverb_mix": round(params.reverb_mix, 4),
            "noise_floor_db": round(params.noise_floor_db, 2),
        }
