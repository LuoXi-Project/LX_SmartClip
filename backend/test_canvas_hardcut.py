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

    def test_no_target_canvas_uses_majority_resolution(self):
        """未传入 target_canvas → 取各段占比最高的分辨率（兜底），而非最大值。

        复现用户反馈：1 段 4K + 多段 1080p/720p 时，取最大值会把所有低清段
        放大到 4K（编码慢且发糊）。占比最高策略让多数段直通。
        这里 1080p 出现 3 次、4K 仅 1 次 → 应取 1080p。
        """
        from app.core.postprod import transitions as tr
        tr.probe_video_dimensions.side_effect = lambda p, **kw: {
            "a.mp4": (1920, 1080), "b.mp4": (1920, 1080),
            "c.mp4": (1280, 720), "d.mp4": (3840, 2160),
        }[p]
        tr._seg_durations.return_value = [5.0, 5.0, 5.0, 5.0]
        tr.compose_with_transitions(
            ["a.mp4", "b.mp4", "c.mp4", "d.mp4"],
            ["hard_cut", "cross_dissolve", "hard_cut", "hard_cut"],
            dissolve_sec=0.35,
            segment_fade_ms=0,
            out_path="out.mp4",
            target_canvas=None,
        )
        self.assertEqual(len(self.ffmpeg_calls), 1)
        fc = self.ffmpeg_calls[0][self.ffmpeg_calls[0].index("-filter_complex") + 1]
        # 4K 段应缩进 1080p 画布（而非把 1080p/720p 放大到 4K）
        self.assertIn("pad=1920:1080", fc)
        self.assertNotIn("scale=3840:2160", fc)



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


class HardCutMixedResolutionTest(unittest.TestCase):
    """回归：纯硬切但段间分辨率/采样率不一致时，绝不能走 concat -c copy。

    复现场景（用户反馈「手动匹配 一键成片 最终视频后面部分卡死」）：
    多个不同源片段拼接 → 各段分辨率不同 → 旧实现误走 concat demuxer + -c copy，
    复用各段原始包，播放器按首段参数解码，第二段起画面卡死。
    正确行为：不一致时应落到 xfade 重编码路径统一画布后再拼接。
    """

    def setUp(self):
        self._patches = [
            mock.patch("app.core.postprod.transitions.probe_video_dimensions"),
            mock.patch("app.core.postprod.transitions._seg_durations"),
            mock.patch("app.core.postprod.transitions.run_ffmpeg"),
            mock.patch(
                "app.core.postprod.transitions.build_render_codec_args",
                return_value=["-c:v", "libx264", "-c:a", "aac"],
            ),
            mock.patch(
                "app.core.postprod.transitions.probe_audio_sample_rate",
                return_value=48000,
            ),
            mock.patch("app.core.postprod.transitions.probe_duration", return_value=5.0),
        ]
        for p in self._patches:
            p.start()
        self.ffmpeg_calls = []

        def _capture(args, desc=""):
            self.ffmpeg_calls.append((desc, list(args)))

        from app.core.postprod import transitions as tr
        tr.run_ffmpeg.side_effect = _capture

    def tearDown(self):
        mock.patch.stopall()

    def test_mixed_resolution_hardcut_single_concat_filter(self):
        """混合分辨率 + 纯硬切 → 单条 concat filter，只编码一次（无逐段归一化、无 concat copy）。

        复现场景：1080p/720p/1080p 三段硬切。正确做法是一条 filter：每段 scale+pad + concat + 一次重编码。
        绝不能逐段归一化（冗余编码）或 concat demuxer + copy（会卡死）。
        """
        from app.core.postprod import transitions as tr
        dims = {"a.mp4": (1920, 1080), "b.mp4": (1280, 720), "c.mp4": (1920, 1080)}
        tr.probe_video_dimensions.side_effect = lambda p, **kw: dims.get(p, (1920, 1080))
        tr._seg_durations.return_value = [5.0, 5.0, 5.0]

        tr.compose_with_transitions(
            ["a.mp4", "b.mp4", "c.mp4"],
            ["hard_cut", "hard_cut", "hard_cut"],
            dissolve_sec=0.35,
            segment_fade_ms=0,
            out_path="out.mp4",
            target_canvas=None,
        )
        self.assertTrue(self.ffmpeg_calls, "应有 ffmpeg 调用")

        # 只应有一次 ffmpeg 调用（单链一次编码），不应有逐段归一化的多路命令
        self.assertEqual(
            len(self.ffmpeg_calls), 1,
            f"硬切混分辨率应单条 concat filter 一次编码，实际 {len(self.ffmpeg_calls)} 次调用",
        )
        desc, cmd = self.ffmpeg_calls[0]
        self.assertIn("hardcut concat filter", desc)

        # 必须是 concat filter：含 -filter_complex，concat=n=3，且每段 scale+pad 在同一链内
        self.assertIn("-filter_complex", cmd)
        fc = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("concat=n=3", fc)
        # 720p 段在链内被 scale+pad（与 1080p 段共处一条 filter）
        self.assertIn("scale=1920:1080:force_original_aspect_ratio=decrease", fc)
        # 3 个输入
        self.assertEqual(cmd.count("-i"), 3)

        # 绝不能有 concat demuxer + copy
        has_concat_demuxer = "-f" in cmd and "concat" in cmd
        has_copy = "-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"
        self.assertFalse(has_concat_demuxer and has_copy, "禁用 concat demuxer + copy（会卡死）")

    def test_mixed_audio_samplerate_hardcut_concat_filter(self):
        """分辨率相同但音频采样率不一致 → 单条 concat filter（音频统一 aresample）一次编码。"""
        from app.core.postprod import transitions as tr
        tr.probe_video_dimensions.return_value = (1920, 1080)
        tr.probe_audio_sample_rate.side_effect = lambda p, **kw: {
            "a.mp4": 44100, "b.mp4": 48000,
        }[p]
        tr._seg_durations.return_value = [5.0, 5.0]

        tr.compose_with_transitions(
            ["a.mp4", "b.mp4"],
            ["hard_cut", "hard_cut"],
            dissolve_sec=0.35,
            segment_fade_ms=0,
            out_path="out.mp4",
            target_canvas=None,
        )
        # 单次调用，concat filter，44100 段音频经 aresample 到 48k
        self.assertEqual(len(self.ffmpeg_calls), 1)
        desc, cmd = self.ffmpeg_calls[0]
        self.assertIn("-filter_complex", cmd)
        fc = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("concat=n=2", fc)
        # aresample 统一采样率（_audio_prep_filter 对非 48k 段会加 aresample=48000）
        self.assertIn("aresample=48000", fc)

    def test_hardcut_merge_never_uses_concat_copy(self):
        """纯硬切混分辨率合并的每条 ffmpeg 命令都不得包含 concat demuxer + copy。

        这是卡死问题的核心回归守卫：concat demuxer + copy 已造成画面冻结，
        合并阶段一律走 concat filter（重编码），彻底杜绝 stream copy。
        """
        from app.core.postprod import transitions as tr
        dims = {"a.mp4": (3840, 2160), "b.mp4": (1280, 720), "c.mp4": (1920, 1080)}
        tr.probe_video_dimensions.side_effect = lambda p, **kw: dims[p]
        tr._seg_durations.return_value = [4.0, 4.0, 4.0]

        tr.compose_with_transitions(
            ["a.mp4", "b.mp4", "c.mp4"],
            ["hard_cut", "hard_cut", "hard_cut"],
            dissolve_sec=0.35,
            segment_fade_ms=0,
            out_path="out.mp4",
            target_canvas=None,
        )
        for desc, cmd in self.ffmpeg_calls:
            has_concat_demuxer = "-f" in cmd and "concat" in cmd
            has_any_copy = (
                ("-c" in cmd and cmd[cmd.index("-c") + 1] == "copy")
                or ("-c:v" in cmd and cmd[cmd.index("-c:v") + 1] == "copy")
                or ("-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "copy")
            )
            self.assertFalse(
                has_concat_demuxer and has_any_copy,
                f"合并阶段禁用 concat demuxer + copy。desc={desc}",
            )


class ResolveTargetCanvasTest(unittest.TestCase):
    """兜底画布选取规则：占比最高（多数段零缩放），并列时取面积最大。"""

    def setUp(self):
        self._patch = mock.patch("app.core.postprod.transitions.probe_video_dimensions")
        self.mock_dims = self._patch.start()

    def tearDown(self):
        mock.patch.stopall()

    def _dims_table(self, table):
        self.mock_dims.side_effect = lambda p, **kw: table[p]

    def test_majority_resolution_wins(self):
        """1 段 4K + 3 段 1080p → 取 1080p（占比最高）。"""
        from app.core.postprod.transitions import _resolve_target_canvas
        self._dims_table({
            "a.mp4": (3840, 2160),
            "b.mp4": (1920, 1080), "c.mp4": (1920, 1080), "d.mp4": (1920, 1080),
        })
        self.assertEqual(
            _resolve_target_canvas(["a.mp4", "b.mp4", "c.mp4", "d.mp4"]),
            (1920, 1080),
        )

    def test_tie_break_picks_largest_area(self):
        """频次并列时取面积最大（不丢分辨率的稳妥兜底）。"""
        from app.core.postprod.transitions import _resolve_target_canvas
        # 1080p 与 4K 各 1 段 → 并列 → 取 4K
        self._dims_table({"a.mp4": (1920, 1080), "b.mp4": (3840, 2160)})
        self.assertEqual(_resolve_target_canvas(["a.mp4", "b.mp4"]), (3840, 2160))

    def test_single_resolution_passthrough(self):
        """所有段同分辨率 → 原样返回（不触发缩放）。"""
        from app.core.postprod.transitions import _resolve_target_canvas
        self._dims_table({"a.mp4": (1280, 720), "b.mp4": (1280, 720)})
        self.assertEqual(_resolve_target_canvas(["a.mp4", "b.mp4"]), (1280, 720))

    def test_probe_failure_falls_back_to_default(self):
        """探测失败/全 0 → 返回默认 1080p。"""
        from app.core.postprod.transitions import _resolve_target_canvas
        self.mock_dims.return_value = (0, 0)
        self.assertEqual(_resolve_target_canvas(["a.mp4", "b.mp4"]), (1920, 1080))


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
