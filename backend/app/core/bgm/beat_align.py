"""BGM 节拍对齐（beat align）：把 BGM 的节拍栅格对齐到成片切点。

思路：视频与 TTS 时长不可动（动了会失步），因此只做「BGM 相位对齐」——
在混音前把 BGM 从曲目内偏移 δ 秒处开始播放（atrim+asetpts），
使 BGM 的节拍落在成片的镜头切换时刻上，产生「卡点」感。

- 节拍检测：librosa onset_strength + beat_track（依赖已在 requirements 中）
- 相位求解：在 [0, 节拍周期) 上 5ms 步长网格搜索，最小化
  「切点到最近节拍的距离之和」；节拍不稳定/过短时返回 None（放弃对齐）。
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)

# 仅信任 60~200 BPM 的节拍栅格；范围外多为检测噪声
_MIN_TEMPO, _MAX_TEMPO = 60.0, 200.0
# 相位网格搜索步长（秒）
_PHASE_STEP = 0.005
# 对齐后平均误差低于该值才认为有效（秒）
_GOOD_MEAN_ERROR = 0.09


def analyze_beats(audio_path: str) -> Optional[dict]:
    """检测音频的节拍栅格。返回 {"tempo": float, "beat_times": np.ndarray}；失败/不稳定返回 None。"""
    try:
        import librosa

        y, sr = librosa.load(audio_path, sr=22050, mono=True)
        if len(y) < sr:  # 短于 1 秒
            return None
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
        tempo = float(np.atleast_1d(tempo)[0])
        beats = librosa.frames_to_time(beat_frames, sr=sr)
        beat_times = np.asarray(beats, dtype=float)
        if tempo < _MIN_TEMPO or tempo > _MAX_TEMPO:
            logger.info("[BeatAlign] 节拍 %.1f BPM 超出信任区间 [%s,%s]，放弃对齐", tempo, _MIN_TEMPO, _MAX_TEMPO)
            return None
        if beat_times.size < 4:
            logger.info("[BeatAlign] 节拍数不足（%d），放弃对齐", beat_times.size)
            return None
        return {"tempo": tempo, "beat_times": beat_times}
    except Exception as e:
        logger.warning("[BeatAlign] 节拍检测失败，跳过对齐: %s", e)
        return None


def _nearest_beat_cost(beat_times: np.ndarray, cuts: np.ndarray, phase: float) -> float:
    """给定 BGM 起播偏移 phase（输出时间轴上节拍变为 beat-phase），
    返回切点到最近节拍的距离总和。"""
    shifted = beat_times - phase
    if shifted.size == 0:
        return float("inf")
    idx = np.searchsorted(shifted, cuts)
    best = np.full(cuts.shape, np.inf)
    for j in (idx - 1, idx):
        valid = (j >= 0) & (j < shifted.size)
        dist = np.abs(cuts[valid] - shifted[j[valid]])
        best[valid] = np.minimum(best[valid], dist)
    return float(np.sum(np.minimum(best, 0.75)))  # 单点误差封顶 0.75s，防长尾主导


def best_phase_offset(beat_times: np.ndarray, cut_times: Sequence[float]) -> Optional[dict]:
    """求最优 BGM 起播偏移 δ：使节拍栅格尽量贴合切点。

    返回 {"offset_sec": δ(≥0), "mean_error": 对齐后平均误差}；
    切点过少或对齐无收益（误差仍大）时返回 None。
    """
    cuts = np.asarray([float(t) for t in cut_times if t > 0.05], dtype=float)
    beats = np.asarray(beat_times, dtype=float)
    if cuts.size < 2 or beats.size < 4:
        return None

    intervals = np.diff(beats)
    period = float(np.median(intervals))
    if period <= 0.2 or period > 1.2:  # 约 50~300 BPM 之外的周期不可信
        return None

    steps = max(2, int(round(period / _PHASE_STEP)))
    phases = np.arange(steps) * (period / steps)
    costs = np.asarray([_nearest_beat_cost(beats, cuts, p) for p in phases])
    best_i = int(np.argmin(costs))
    best_phase = float(phases[best_i])

    # 平均误差（含封顶后）评估对齐质量
    mean_err = costs[best_i] / cuts.size
    if mean_err > _GOOD_MEAN_ERROR:
        logger.info("[BeatAlign] 最优相位平均误差 %.3fs 超过阈值，放弃对齐", mean_err)
        return None
    logger.info(
        "[BeatAlign] 相位对齐：offset=%.3fs，平均误差=%.3fs（切点 %d 个）",
        best_phase, mean_err, cuts.size,
    )
    return {"offset_sec": best_phase, "mean_error": mean_err}


def align_bgm_offset(bgm_path: str, cut_times: Sequence[float]) -> Optional[float]:
    """一步到位：检测节拍并求最优起播偏移；任何不满足条件时返回 None（保持原混音）。"""
    info = analyze_beats(bgm_path)
    if info is None:
        return None
    res = best_phase_offset(info["beat_times"], cut_times)
    if res is None:
        return None
    return res["offset_sec"]
