"""画布来源与纯硬切快路径单测。

验证两个关键优化：
1. 画布优先用 export 配置（clip_scale_*），而非取各段最大值
   （避免混合分辨率时把所有低清段放大到 4K）。
2. 纯硬切 + 无字幕 → concat -c copy 零编码；micro-fade 不再强制全量重编码。

不依赖真实 ffmpeg：mock probe_* 与 run_ffmpeg，断言命令结构。
"""
import os
import unittest
from unittest import mock


class CanvasResolutionTest(unittest.TestCase):
    """compose_with_transitions 的画布来源优先级。"""

    def setUp(self):
        self._patches = [
            mock.patch("app.core.postprod.transitions.probe_video_dimensions"),
            mock.patch("app.core.postprod.transitions._seg_durations"),
            mock.patch("app.core.postprod.transitions.run_ffmpeg"),
            mock.patch("app.core.postprod.transitions.build_render_codec_args", return_value=["-c:v", "libx264", "-c:a", "aac"]),
            mock.patch("app.core.postprod.transitions.probe_audio_sample_rate", return_value=48000),
        ]
        for p in self._patches:
            p.start()
        self.ffmpeg_calls = []

        def _capture(args, desc=""):
            self.ffmpeg_calls.append(list(args))
        from app.core.postprod import transitions as tr
        tr.run_ffmpeg.side_effect = _capture

    def tearDown(self):
        mock.patch.stopall()

    def test_target_canvas_overrides_max_value(self):
        """显式传入 target_canvas → 用传入值，不取各段最大值。"""
        from app.core.postprod import transitions as tr
        # 三段：1080p / 720p / 4K。若取最大值会变 4K；传入 1080p 应强制用 1080p。
        tr.probe_video_dimensions.side_effect = lambda p, **kw: {
            "a.mp4": (1920, 1080), "b.mp4": (1280, 720), "c.mp4": (3840, 2160),
        }[p]
        tr._seg_durations.return_value = [5.0, 5.0, 5.0]
        # 带一个 dissolve → 触发 xfade 重编码路径（才能看到画布）
        tr.compose_with_transitions(
            ["a.mp4", "b.mp4", "c.mp4"],
            ["hard_cut", "cross_dissolve", "hard_cut"],
            dissolve_sec=0.35,
            segment_fade_ms=0,
            out_path="out.mp4",
            target_canvas=(1920, 1080),
        )
        self.assertEqual(len(self.ffmpeg_calls), 1)
        fc = self.ffmpeg_calls[0][self.ffmpeg_calls[0].index("-filter_complex") + 1]
        # 应出现 scale=1920:1080（而非 3840:2160）
        self.assertIn("scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080", fc)
        self.assertNotIn("scale=3840:2160", fc)

    def test_no_target_canvas_falls_back_to_max(self):
        """未传入 target_canvas → 取各段最大值（兜底，保持旧行为）。"""
        from app.core.postprod import transitions as tr
        tr.probe_video_dimensions.side_effect = lambda p, **kw: {
            "a.mp4": (1920, 1080), "b.mp4": (3840, 2160),
        }[p]
        tr._seg_durations.return_value = [5.0, 5.0]
        tr.compose_with_transitions(
            ["a.mp4", "b.mp4"],
            ["hard_cut", "cross_dissolve"],
            dissolve_sec=0.35,
            segment_fade_ms=0,
            out_path="out.mp4",
            target_canvas=None,
        )
        self.assertEqual(len(self.ffmpeg_calls), 1)
        fc = self.ffmpeg_calls[0][self.ffmpeg_calls[0].index("-filter_complex") + 1]
        # 兜底取最大值 4K
        self.assertIn("scale=3840:2160:force_original_aspect_ratio=decrease,pad=3840:2160", fc)


class HardCutFastPathTest(unittest.TestCase):
    """纯硬切不进 xfade 重编码；等大段走 concat -c copy。"""

    def setUp(self):
        self._patches = [
            mock.patch("app.core.subtitle.composer.probe_video_dimensions"),
            mock.patch("app.core.subtitle.composer.probe_audio_sample_rate"),
            mock.patch("app.core.subtitle.composer.run_ffmpeg"),
            mock.patch("app.core.subtitle.composer.write_concat_list"),
        ]
        for p in self._patches:
            p.start()
        self.ffmpeg_calls = []

        def _capture(args, desc=""):
            self.ffmpeg_calls.append((desc, list(args)))
        from app.core.subtitle import composer as cp
        cp.run_ffmpeg.side_effect = _capture

    def tearDown(self):
        mock.patch.stopall()

    def test_pure_hard_cut_uniform_uses_concat_copy(self):
        """纯硬切 + 等大段 + 无字幕 → concat -c copy（零重编码）。"""
        from app.core.subtitle import composer as cp
        # 所有段等大等采样率
        cp.probe_video_dimensions.return_value = (1920, 1080)
        cp.probe_audio_sample_rate.return_value = 48000
        cp.compose_final_video(
            seg_paths=["a.mp4", "b.mp4", "c.mp4"],
            srt_entries=[],
            style=None,
            fonts_dir="",
            tmp="/tmp",
            project_name="p",
            final_render_opts={},
            normalize_audio=False,
            segment_transition_ins=["hard_cut", "hard_cut", "hard_cut"],
            transition_dissolve_sec=0.35,
            segment_fade_ms=0,
        )
        self.assertEqual(len(self.ffmpeg_calls), 1)
        desc, cmd = self.ffmpeg_calls[0]
        self.assertIn("concat", desc)
        # 应有 -c copy（视频音频都不重编码）
        self.assertIn("-c", cmd)
        copy_idx = cmd.index("-c")
        self.assertEqual(cmd[copy_idx + 1], "copy")

    def test_microfade_does_not_force_xfade_for_hardcut(self):
        """纯硬切但 segment_fade_ms=80 → 仍走 concat copy（不被 micro-fade 拖进重编码）。"""
        from app.core.subtitle import composer as cp
        cp.probe_video_dimensions.return_value = (1920, 1080)
        cp.probe_audio_sample_rate.return_value = 48000
        cp.compose_final_video(
            seg_paths=["a.mp4", "b.mp4"],
            srt_entries=[],
            style=None,
            fonts_dir="",
            tmp="/tmp",
            project_name="p",
            final_render_opts={},
            normalize_audio=False,
            segment_transition_ins=["hard_cut", "hard_cut"],
            transition_dissolve_sec=0.35,
            segment_fade_ms=80,  # micro-fade 开启
        )
        self.assertEqual(len(self.ffmpeg_calls), 1)
        desc, cmd = self.ffmpeg_calls[0]
        self.assertIn("concat", desc)
        copy_idx = cmd.index("-c")
        self.assertEqual(cmd[copy_idx + 1], "copy",
                         "纯硬切即使带 micro-fade 也应走 concat copy，不应全量重编码")


class ComposerCanvasFromConfigTest(unittest.TestCase):
    """compose_final_video 合并阶段画布读 export 配置。"""

    def setUp(self):
        self._patches = [
            mock.patch("app.core.subtitle.composer.probe_video_dimensions"),
            mock.patch("app.core.subtitle.composer.probe_audio_sample_rate"),
            mock.patch("app.core.subtitle.composer.run_ffmpeg"),
            mock.patch("app.core.subtitle.composer.write_concat_list"),
            # 拦截 compose_with_transitions 调用，断言传入的 target_canvas
            mock.patch("app.core.postprod.transitions.compose_with_transitions"),
            mock.patch("app.core.postprod.transitions.probe_duration", return_value=5.0),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        mock.patch.stopall()

    def test_mixed_resolution_passes_config_canvas_to_merge(self):
        """混合分辨率 + 配置 1080p → 合并阶段把配置画布(1920,1080)传给 compose_with_transitions。"""
        from app.core.subtitle import composer as cp
        from app.core.postprod import transitions as tr
        # 4K + 720p 不等大 → 走分块合并路径
        cp.probe_video_dimensions.side_effect = lambda p, **kw: {
            "a.mp4": (3840, 2160), "b.mp4": (1280, 720),
        }[p]
        cp.probe_audio_sample_rate.return_value = 48000
        opts = {"clip_scale_width": "1920", "clip_scale_height": "1080"}
        cp.compose_final_video(
            seg_paths=["a.mp4", "b.mp4"],
            srt_entries=[],
            style=None,
            fonts_dir="",
            tmp="/tmp",
            project_name="p",
            final_render_opts=opts,
            normalize_audio=False,
            segment_transition_ins=["hard_cut", "hard_cut"],
            transition_dissolve_sec=0.35,
            segment_fade_ms=0,
        )
        # compose_with_transitions 应被调用，且 target_canvas 为配置的 1080p（非 4K 最大值）
        tr.compose_with_transitions.assert_called_once()
        kwargs = tr.compose_with_transitions.call_args.kwargs
        self.assertEqual(kwargs.get("target_canvas"), (1920, 1080),
                         "合并阶段应传入配置画布 1080p，而非取最大值 4K")


if __name__ == "__main__":
    unittest.main()
