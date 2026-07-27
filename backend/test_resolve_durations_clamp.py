"""resolve_durations 的 clip_trims 时长 clamp 单测。

验证：当某条 clip_trim 的 duration_sec 超过「该 clip 内 clip_start_sec 之后剩余可用长度」时，
时长会被 clamp 到可用长度，与 materialize_clip_paths_for_group 的 clamp 一致，
避免字幕时间轴高估、与成片段落时长错位。
"""
import unittest

from app.core.subtitle.timeline import resolve_durations
from app.models.subtitle import ClipTrimPart, SubtitleSegmentInput


class _SegBuilder:
    def __init__(self):
        self.idx = 0

    def with_trims(self, trims, *, cid="c1", copy_text="x"):
        seg = SubtitleSegmentInput(
            copy_text=copy_text,
            clip_id=cid,
            clip_ids=[t.clip_id for t in trims],
            clip_trims=trims,
        )
        return seg


class ResolveDurationsClampTest(unittest.TestCase):
    def test_trim_within_clip_passes_through(self):
        """trim 时长 <= clip 剩余可用：原样累加。"""
        b = _SegBuilder()
        # clip 总长 10s，clip_start=2，duration=3 → 剩余 8s，请求 3s 不超
        seg = b.with_trims([ClipTrimPart(clip_id="c1", clip_start_sec=2.0, duration_sec=3.0)])
        durs, src = resolve_durations([seg], {"c1": 10.0}, "/nonexistent", use_tts=False)
        self.assertEqual(len(durs), 1)
        self.assertAlmostEqual(durs[0], 3.0, places=3)
        self.assertEqual(src, "clip_trims")

    def test_trim_exceeds_clip_is_clamped(self):
        """trim 时长 > clip 剩余可用：clamp 到可用长度（clip_total - clip_start_sec）。"""
        b = _SegBuilder()
        # clip 总长 10s，clip_start=8，请求 duration=5 → 剩余仅 2s，应 clamp 到 2s
        seg = b.with_trims([ClipTrimPart(clip_id="c1", clip_start_sec=8.0, duration_sec=5.0)])
        durs, _src = resolve_durations([seg], {"c1": 10.0}, "/nonexistent", use_tts=False)
        self.assertEqual(len(durs), 1)
        self.assertAlmostEqual(durs[0], 2.0, places=3)

    def test_multi_trim_each_clamped_independently(self):
        """多条 trims 各自 clamp；同一 clip_id 多段不同入点都能正确处理。"""
        b = _SegBuilder()
        # 两段同 clip：第一段 0→4（剩 10s，请求 4 不超）；第二段 9→5（剩 1s，clamp 到 1）
        seg = b.with_trims(
            [
                ClipTrimPart(clip_id="c1", clip_start_sec=0.0, duration_sec=4.0),
                ClipTrimPart(clip_id="c1", clip_start_sec=9.0, duration_sec=5.0),
            ]
        )
        durs, _src = resolve_durations([seg], {"c1": 10.0}, "/nonexistent", use_tts=False)
        self.assertEqual(len(durs), 1)
        self.assertAlmostEqual(durs[0], 4.0 + 1.0, places=3)

    def test_unknown_clip_id_falls_back_to_requested(self):
        """clip_id 不在 clip_durations（未知时长）：回退用请求 duration，不 clamp。"""
        b = _SegBuilder()
        seg = b.with_trims([ClipTrimPart(clip_id="cX", clip_start_sec=1.0, duration_sec=5.0)])
        durs, _src = resolve_durations([seg], {"c1": 10.0}, "/nonexistent", use_tts=False)
        self.assertEqual(len(durs), 1)
        self.assertAlmostEqual(durs[0], 5.0, places=3)


if __name__ == "__main__":
    unittest.main()
