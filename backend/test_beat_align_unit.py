# -*- coding: utf-8 -*-
"""BGM 节拍对齐单元测试：相位求解、边界条件与 librosa 真实检测。"""

import numpy as np

from app.core.bgm.beat_align import analyze_beats, best_phase_offset


def _grid(period=0.5, total=30.0):
    return np.arange(0.0, total, period)


def test_phase_offset_aligns_shifted_cuts():
    # 切点整体滞后节拍 0.13s：最优相位应能把误差压到极小
    beats = _grid()
    cuts = (beats + 0.13)[2:20]
    res = best_phase_offset(beats, cuts)
    assert res is not None
    assert res["mean_error"] < 0.03
    # 等效相位 0.5-0.13=0.37（把 0.5s 处的节拍提前到切点上）
    assert abs(res["offset_sec"] - 0.37) < 0.02 or res["offset_sec"] < 0.02


def test_phase_offset_already_aligned():
    beats = _grid()
    cuts = beats[3:15]
    res = best_phase_offset(beats, cuts)
    assert res is not None
    assert res["mean_error"] < 0.02


def test_phase_offset_needs_enough_inputs():
    beats = _grid()
    assert best_phase_offset(beats, [1.0]) is None  # 切点过少
    assert best_phase_offset(beats[:2], [1.0, 2.0, 3.0]) is None  # 节拍过少


def test_phase_offset_gives_up_on_aperiodic_cuts():
    # 非周期切点无法用单一相位对齐 → 平均误差超阈值 → 放弃
    beats = _grid()
    cuts = [0.31, 0.97, 2.13, 3.47, 5.02, 7.31, 8.83, 11.09]
    assert best_phase_offset(beats, cuts) is None


def test_analyze_beats_on_click_train(tmp_path):
    # 用 soundfile 合成 120BPM 的 click train，验证 librosa 检测链路
    import soundfile

    sr = 22050
    period = 0.5
    total = 20.0
    y = np.zeros(int(sr * total), dtype=np.float32)
    for t in np.arange(0.0, total, period):
        i = int(t * sr)
        # 短促脉冲（10ms 指数衰减）
        n = int(0.01 * sr)
        y[i : i + n] += (np.random.RandomState(0).rand(n) * 2 - 1) * np.exp(
            -np.linspace(0, 8, n)
        )
    path = str(tmp_path / "clicks.wav")
    soundfile.write(path, y, sr)

    info = analyze_beats(path)
    assert info is not None
    assert 110 <= info["tempo"] <= 135, f"tempo={info['tempo']}"
    assert info["beat_times"].size >= 20
