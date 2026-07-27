"""fast_render 直通路径单测。

覆盖：
- _collect_seg_src_info：单源多 clip_trims / 多源 / 跨段同源 / 段级配音解析
- _can_fast_render：带/不带配音、静音段、视觉特效、段数
- try_fast_render 的 filter_complex 字符串结构断言（mock ffmpeg/probe，不实际编码）

不依赖真实 ffprobe/ffmpeg：用 unittest.mock 打桩 probe_* 与 run_ffmpeg。
"""
import os
import unittest
from unittest import mock

from app.core.subtitle import fast_render as fr
from app.models.subtitle import ClipTrimPart, SubtitleSegmentInput


def _clip_map(cid, *, src="src.mp4", src_start=0.0, src_end=0.0, dur=10.0, path="clip.mp4"):
    """构造 clip_map 单条信息（src_end<=src_start 时由 collect 用 dur 兜底）。"""
    return {
        cid: {
            "path": path,
            "dur": dur,
            "src_video_path": src,
            "src_start": src_start,
            "src_end": src_end,
        }
    }


def _seg_with_trims(trims, *, tts_filename=None, cid="c1"):
    return SubtitleSegmentInput(
        copy_text="x",
        clip_id=cid,
        clip_ids=[t.clip_id for t in trims],
        clip_trims=trims,
        tts_filename=tts_filename,
    )


def _seg_single(cid, *, clip_start=None, duration=None, tts_filename=None):
    return SubtitleSegmentInput(
        copy_text="x",
        clip_id=cid,
        clip_ids=[cid],
        clip_start_sec=clip_start,
        duration_sec=duration,
        tts_filename=tts_filename,
    )


class CollectSegSrcInfoTest(unittest.TestCase):
    def setUp(self):
        # probe_duration 打桩：源片 100s，clip 文件 10s
        self._probe = mock.patch("app.core.subtitle.fast_render.probe_duration").start()
        self._probe.side_effect = lambda p, **kw: 100.0 if p == "src.mp4" else 10.0
        self._isfile = mock.patch("app.core.subtitle.fast_render.os.path.isfile").start()
        # 以 basename 判定，避免跨平台路径分隔符差异
        self._isfile.side_effect = lambda p: os.path.basename(p) in ("src.mp4", "a.wav", "clip.mp4", "c2.mp4")

    def tearDown(self):
        mock.patch.stopall()

    def test_single_source_multi_trims_flattens(self):
        """单源 + 每段多 clip_trims：展平为子 clip，全部同源 → 返回 plan。"""
        cm = _clip_map("c1", src="src.mp4", src_start=0.0, src_end=20.0, dur=20.0)
        cm["c2"] = {
            "path": "c2.mp4",
            "dur": 20.0,
            "src_video_path": "src.mp4",
            "src_start": 30.0,
            "src_end": 50.0,
        }
        seg1 = _seg_with_trims(
            [ClipTrimPart(clip_id="c1", clip_start_sec=1.0, duration_sec=3.0),
             ClipTrimPart(clip_id="c2", clip_start_sec=2.0, duration_sec=4.0)]
        )
        seg2 = _seg_single("c1", duration=5.0)
        plan = fr._collect_seg_src_info([seg1, seg2], cm, "/tts")
        self.assertIsNotNone(plan)
        self.assertEqual(plan.src_path, "src.mp4")
        self.assertEqual(len(plan.segments), 2)
        # seg1 展平为 2 个子 clip
        self.assertEqual(len(plan.segments[0].subclips), 2)
        # seg2 单 clip
        self.assertEqual(len(plan.segments[1].subclips), 1)
        # abs_start 映射：c2 src_start=30 + rel 2 = 32
        self.assertAlmostEqual(plan.segments[0].subclips[1].abs_start, 32.0, places=2)

    def test_multi_source_returns_none(self):
        """子 clip 来自不同源片 → None（无法直通）。"""
        cm = _clip_map("c1", src="srcA.mp4", src_start=0.0, src_end=10.0, dur=10.0)
        cm["c2"] = {
            "path": "c2.mp4",
            "dur": 10.0,
            "src_video_path": "srcB.mp4",
            "src_start": 0.0,
            "src_end": 10.0,
        }
        seg = _seg_with_trims(
            [ClipTrimPart(clip_id="c1", clip_start_sec=0.0, duration_sec=3.0),
             ClipTrimPart(clip_id="c2", clip_start_sec=0.0, duration_sec=3.0)]
        )
        plan = fr._collect_seg_src_info([seg, seg], cm, "/tts")
        self.assertIsNone(plan)

    def test_clip_without_src_video_returns_none(self):
        """clip 无源片映射（src_video_path 空）→ None。"""
        cm = _clip_map("c1", src="", src_start=0.0, src_end=10.0, dur=10.0)
        seg = _seg_single("c1", duration=3.0)
        plan = fr._collect_seg_src_info([seg, seg], cm, "/tts")
        self.assertIsNone(plan)

    def test_trims_span_exceeds_clip_is_clamped(self):
        """trim duration 超过 clip 剩余可用：clamp（与慢路径一致）。"""
        # c1: src 0-10，clip_start=8，请求 5 → 仅剩 2s
        cm = _clip_map("c1", src="src.mp4", src_start=0.0, src_end=10.0, dur=10.0)
        seg = _seg_with_trims(
            [ClipTrimPart(clip_id="c1", clip_start_sec=8.0, duration_sec=5.0)]
        )
        plan = fr._collect_seg_src_info([seg, seg], cm, "/tts")
        self.assertIsNotNone(plan)
        self.assertAlmostEqual(plan.segments[0].subclips[0].span, 2.0, places=2)

    def test_tts_filename_resolved_when_file_exists(self):
        """段级 tts_filename 文件存在 → plan 记录 tts_path/dur。"""
        cm = _clip_map("c1", src="src.mp4", src_start=0.0, src_end=10.0, dur=10.0)
        seg = _seg_single("c1", duration=3.0, tts_filename="a.wav")
        plan = fr._collect_seg_src_info([seg, seg], cm, "/tts")
        self.assertIsNotNone(plan)
        self.assertEqual(plan.segments[0].tts_path, os.path.join("/tts", "a.wav"))
        self.assertGreater(plan.segments[0].tts_dur, 0.0)

    def test_tts_filename_missing_treated_as_no_tts(self):
        """tts_filename 文件不存在 → 视为无配音（tts_path=None）。"""
        cm = _clip_map("c1", src="src.mp4", src_start=0.0, src_end=10.0, dur=10.0)
        seg = _seg_single("c1", duration=3.0, tts_filename="missing.wav")
        # isfile 对 missing.wav 返回 False
        plan = fr._collect_seg_src_info([seg, seg], cm, "/tts")
        self.assertIsNotNone(plan)
        self.assertIsNone(plan.segments[0].tts_path)


class CanFastRenderTest(unittest.TestCase):
    def _plan(self, n=2, *, mute=False, visual=False, tts=True):
        from app.models.subtitle import SegmentVisualEffect
        segs = []
        for _ in range(n):
            s = SubtitleSegmentInput(
                copy_text="x", clip_id="c1", clip_ids=["c1"],
                mute_audio=mute,
                visual_effect=SegmentVisualEffect(zoom=1.1) if visual else None,
                tts_filename="a.wav" if tts else None,
            )
            fs = fr._FastSegment(seg=s, subclips=[fr._SubClip(cid="c1", abs_start=0.0, span=3.0)])
            if tts:
                fs.tts_path = "/tts/a.wav"
                fs.tts_dur = 3.0
            segs.append(fs)
        return fr._FastRenderPlan(src_path="src.mp4", segments=segs)

    def test_min_two_segments(self):
        plan = self._plan(n=1)
        ok, reason = fr._can_fast_render(plan, "/tts", {}, "auto")
        self.assertFalse(ok)
        self.assertIn("段数", reason)

    def test_tts_segments_now_allowed(self):
        """放开段级配音：带 tts 的段不再被拒绝。"""
        plan = self._plan(n=2, tts=True)
        with mock.patch("app.core.subtitle.fast_render.os.path.isfile", return_value=True):
            ok, reason = fr._can_fast_render(plan, "/tts", {}, "auto")
        self.assertTrue(ok, f"应允许带配音段直通，但被拒: {reason}")

    def test_mute_segment_rejected(self):
        plan = self._plan(n=2, mute=True)
        with mock.patch("app.core.subtitle.fast_render.os.path.isfile", return_value=True):
            ok, reason = fr._can_fast_render(plan, "/tts", {}, "auto")
        self.assertFalse(ok)
        self.assertIn("静音", reason)

    def test_visual_effect_rejected(self):
        plan = self._plan(n=2, visual=True)
        with mock.patch("app.core.subtitle.fast_render.os.path.isfile", return_value=True):
            ok, reason = fr._can_fast_render(plan, "/tts", {}, "auto")
        self.assertFalse(ok)
        self.assertIn("视觉特效", reason)

    def test_missing_tts_file_rejected(self):
        plan = self._plan(n=2, tts=True)
        with mock.patch("app.core.subtitle.fast_render.os.path.isfile", return_value=False):
            ok, reason = fr._can_fast_render(plan, "/tts", {}, "auto")
        self.assertFalse(ok)
        self.assertIn("配音文件缺失", reason)


class TryFastRenderFilterComplexTest(unittest.TestCase):
    """验证 try_fast_render 构建的 filter_complex 字符串结构（不实际编码）。"""

    def setUp(self):
        # 打桩所有外部依赖
        self._patches = [
            mock.patch("app.core.subtitle.fast_render.probe_duration", return_value=100.0),
            mock.patch("app.core.subtitle.fast_render.probe_video_dimensions", return_value=(1920, 1080)),
            mock.patch("app.core.subtitle.fast_render.os.path.isfile", return_value=True),
            mock.patch("app.core.subtitle.fast_render.run_ffmpeg"),
        ]
        for p in self._patches:
            p.start()
        self.ffmpeg_calls = []

        def _capture(args, desc=""):
            self.ffmpeg_calls.append(list(args))
        fr.run_ffmpeg.side_effect = _capture

    def tearDown(self):
        mock.patch.stopall()

    def test_multi_subclip_and_tts_builds_single_command(self):
        """多子 clip + 配音段：构建单条 ffmpeg 命令，filter_complex 含 concat/ttrim/ass。"""
        cm = _clip_map("c1", src="src.mp4", src_start=0.0, src_end=20.0, dur=20.0)
        cm["c2"] = {
            "path": "c2.mp4", "dur": 20.0,
            "src_video_path": "src.mp4", "src_start": 30.0, "src_end": 50.0,
        }
        # seg1: 两个子 clip + 配音；seg2: 单 clip 无配音
        seg1 = _seg_with_trims(
            [ClipTrimPart(clip_id="c1", clip_start_sec=1.0, duration_sec=3.0),
             ClipTrimPart(clip_id="c2", clip_start_sec=2.0, duration_sec=4.0)],
            tts_filename="a.wav",
        )
        seg2 = _seg_single("c1", duration=5.0)
        out = fr.try_fast_render(
            segments=[seg1, seg2], srt_entries=[], clip_map=cm,
            style=None, project_name="p", fonts_dir="", tmp="/tmp",
            final_render_opts={}, normalize_audio=False, prefer_gpu=False,
            tts_audio_dir="/tts", render_mode="auto", materialize_from_source=True,
            production_profile=None,
        )
        self.assertIsNotNone(out)
        self.assertEqual(len(self.ffmpeg_calls), 1, "应只调用一次 ffmpeg（单进程直通）")
        cmd = self.ffmpeg_calls[0]
        fc = cmd[cmd.index("-filter_complex") + 1]
        # 段1 多子 clip 预拼接 → concat=n=2
        self.assertIn("concat=n=2:v=1:a=1[vcat0][acat0]", fc)
        # 段1 配音覆盖 → trim + atrim 取 tts 输入
        self.assertIn("[vcat0]trim=start=0:end=", fc)
        self.assertIn("atrim=start=0:end=", fc)
        # 段2 单 clip → 直接 vcat1（无 concat）
        self.assertIn("[vcat1]setpts=PTS-STARTPTS[vseg1]", fc)
        # 段间转场（默认 hard_cut）→ concat=n=2
        self.assertIn("concat=n=2:v=1:a=0", fc)
        # 输入：2 个子clip(sep1) + 1 个子clip(seg2) + 1 个 tts = 4 个 -i
        i_count = cmd.count("-i")
        self.assertEqual(i_count, 4)
        # 映射最终输出
        self.assertIn("-map", cmd)
        self.assertIn("[vout]", cmd)
        self.assertIn("[aout]", cmd)


if __name__ == "__main__":
    unittest.main()
