"""TTS 成片：画面时长与配音时长不一致时的对齐策略（变速 / 定格 / 循环素材）。"""
from __future__ import annotations

import math
import os
from typing import Any, Optional, Tuple

from app.models.subtitle import TtsVideoAlignConfig
from app.utils.ffprobe_utils import probe_duration


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def build_atempo_filter_chain(factor: float) -> str:
    """
    ffmpeg atempo 单级限制约 [0.5, 2.0]，多级串联实现更大范围。
    factor>1 加速（时长变短），factor<1 减速（时长变长）。
    """
    if factor <= 0:
        factor = 1.0
    parts: list[str] = []
    rem = float(factor)
    while rem > 2.0 + 1e-6:
        parts.append("atempo=2.0")
        rem /= 2.0
    while rem < 0.5 - 1e-6:
        parts.append("atempo=0.5")
        rem /= 0.5
    parts.append(f"atempo={clamp(rem, 0.5, 2.0):.6f}")
    return ",".join(parts)


def resolve_stretch_audio_atempo(
    *, tts_sec: float, video_sec: float, cfg: TtsVideoAlignConfig
) -> Tuple[float, float]:
    """
    将配音时长压到不超过画面时长（允许误差）。
    返回 (实际使用的 atempo 乘积, 变速后的音频时长)。
    """
    if tts_sec <= 0 or video_sec <= 0:
        return 1.0, max(tts_sec, 0.001)
    raw = tts_sec / video_sec
    lim_lo = float(cfg.min_audio_atempo)
    lim_hi = float(cfg.max_audio_atempo)
    eff = clamp(raw, lim_lo, lim_hi)
    out_dur = tts_sec / eff
    return eff, out_dur


def resolve_stretch_video_pts_factor(
    *, tts_sec: float, video_sec: float, cfg: TtsVideoAlignConfig
) -> Tuple[float, float]:
    """
    将画面时长拉到接近配音时长：setpts 乘数 = tts_sec/video_sec。
    返回 (clamp 后的乘数, 拉伸后的视频时长)。
    """
    if tts_sec <= 0 or video_sec <= 0:
        return 1.0, max(video_sec, 0.001)
    raw = tts_sec / video_sec
    lim_lo = float(cfg.min_video_pts_factor)
    lim_hi = float(cfg.max_video_pts_factor)
    eff = clamp(raw, lim_lo, lim_hi)
    out_dur = video_sec * eff
    return eff, out_dur


def compute_timeline_duration_sec(
    *, tts_sec: float, video_sec: float, policy: str, cfg: TtsVideoAlignConfig
) -> float:
    """
    与 render_tts_segment 输出的段落时长对齐，用于生成 SRT。
    """
    tts_sec = max(0.001, float(tts_sec))
    video_sec = max(0.001, float(video_sec))
    eps = 0.03

    if policy == "stretch_audio":
        _ae, out_audio = resolve_stretch_audio_atempo(tts_sec=tts_sec, video_sec=video_sec, cfg=cfg)
        # 成片段落时长：至少覆盖画面；若变速后配音仍长于画面则还要再加定格时间
        return max(video_sec, out_audio)

    if policy == "stretch_video":
        # 成片音轨以 TTS 为准，段落时长与 probe(TTS) 一致（画面变速或裁切对齐）
        return tts_sec

    # freeze_last_frame | loop_video_to_cover：配音更长则成片跟配音；更短则裁掉多余画面
    if tts_sec + eps < video_sec:
        return tts_sec
    return tts_sec


def concat_repeat_count(*, need_sec: float, unit_sec: float) -> int:
    """循环拼接素材组次数（不含原始一组）。"""
    if unit_sec <= 0.05 or need_sec <= 0.02:
        return 0
    return int(math.ceil(need_sec / unit_sec))


def apply_timeline_duration_overrides(
    segments: list[Any],
    cfg: Optional[TtsVideoAlignConfig],
    tts_audio_dir: str,
) -> None:
    """按对齐策略为各段写入 timeline_duration_sec，供 resolve_durations / SRT 使用。"""
    if cfg is None or not segments:
        return
    for seg in segments:
        fn = getattr(seg, "tts_filename", None)
        if not fn:
            continue
        p = os.path.join(tts_audio_dir, os.path.basename(str(fn)))
        tts_d = float(probe_duration(p, log_on_failure=True) or 0.0)
        if tts_d <= 0.05:
            continue
        vd_raw = getattr(seg, "duration_sec", None)
        try:
            vd = float(vd_raw) if vd_raw is not None else None
        except Exception:
            vd = None
        if vd is None or vd <= 0.05:
            continue
        seg.timeline_duration_sec = compute_timeline_duration_sec(
            tts_sec=tts_d, video_sec=vd, policy=str(cfg.policy), cfg=cfg
        )
