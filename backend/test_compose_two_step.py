"""复现 + 验证：多段 + 字幕的合成不应走单条 N 段 filter_complex。

回归场景（用户反馈）：42 段混合分辨率 + 字幕「一键成片」，
旧实现把 42 段全塞进一条 filter_complex（concat=n=42）+ 每段 scale 到 4K → 超时。

正确实现（两步走）：
  步骤1：分块合并画面（无字幕，等大段 copy / 不等大分块统一画布）
  步骤2：对合并后单文件做单次 ass overlay

本测试断言：带字幕时不再出现 concat=n={大段数} 的单条 filter，且字幕烧录是单文件 overlay。
"""
import os
import shutil
import tempfile
import unittest
from unittest import mock


class ManySegmentsSubtitleTest(unittest.TestCase):
    """多段 + 字幕 → 两步走（分块合画面 + 单次字幕烧录）。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="lxtest_")
        self._patches = [
            mock.patch("app.core.subtitle.composer.probe_video_dimensions"),
            mock.patch("app.core.subtitle.composer.probe_audio_sample_rate"),
            mock.patch("app.core.subtitle.composer.run_ffmpeg"),
            mock.patch("app.core.subtitle.composer.write_concat_list"),
            mock.patch("app.core.subtitle.composer.build_ass", return_value="ASS_CONTENT"),
            mock.patch("app.core.subtitle.composer.os.path.isdir", return_value=True),
            mock.patch("app.core.postprod.transitions.probe_duration", return_value=5.0),
            mock.patch("app.core.postprod.transitions.probe_video_dimensions"),
            mock.patch("app.core.postprod.transitions.probe_audio_sample_rate", return_value=48000),
            mock.patch("app.core.postprod.transitions.run_ffmpeg"),
            mock.patch("app.core.postprod.transitions.build_render_codec_args", return_value=["-c:v", "libx264", "-c:a", "aac"]),
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
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_subtitle_does_not_use_single_n_segment_filter(self):
        """带字幕 + 多段不等大：不应出现 concat=n=20 的单条 filter_complex。"""
        from app.core.subtitle import composer as cp
        from app.models.subtitle import SubtitleStyle

        # 20 段混合分辨率（1080p/720p 交替）→ 不等大 → 必走合并+字幕路径
        dims = {}
        paths = []
        for i in range(20):
            p = f"seg_{i:03d}.mp4"
            paths.append(p)
            dims[p] = (1920, 1080) if i % 2 == 0 else (1280, 720)
        cp.probe_video_dimensions.side_effect = lambda p, **kw: dims.get(p, (1920, 1080))
        cp.probe_audio_sample_rate.return_value = 48000
        # transitions 模块的 probe 也用同一份维度表（compose_with_transitions 内部调用）
        from app.core.postprod import transitions as tr
        tr.probe_video_dimensions.side_effect = lambda p, **kw: dims.get(p, (1920, 1080))

        style = SubtitleStyle(font_size=48)
        srt = [{"start": 0.0, "end": 1.0, "text": "测试"}]

        cp.compose_final_video(
            seg_paths=paths,
            srt_entries=srt,
            style=style,
            fonts_dir="/fonts",
            tmp=self._tmp,
            project_name="p",
            final_render_opts={"clip_scale_width": "1920", "clip_scale_height": "1080"},
            normalize_audio=False,
            segment_transition_ins=["hard_cut"] * 20,
            transition_dissolve_sec=0.35,
            segment_fade_ms=0,
        )

        # 不应出现 concat=n=20 的单条巨型 filter（旧超时元凶）
        for desc, cmd in self.ffmpeg_calls:
            if "-filter_complex" in cmd:
                fc = cmd[cmd.index("-filter_complex") + 1]
                # 任何一条 filter 都不应把 20 段塞进单个 concat
                self.assertNotIn(
                    "concat=n=20", fc,
                    f"回退：仍把 {20} 段塞进单条 filter_complex（超时元凶）。desc={desc}",
                )

    def test_subtitle_burns_on_single_merged_file(self):
        """带字幕时，ass overlay 应作用于单个合并文件（-i 单个 + -vf ass=），非多输入。"""
        from app.core.subtitle import composer as cp
        from app.models.subtitle import SubtitleStyle

        # 3 段不等大 + 字幕
        dims = {"a.mp4": (1920, 1080), "b.mp4": (1280, 720), "c.mp4": (1920, 1080)}
        cp.probe_video_dimensions.side_effect = lambda p, **kw: dims.get(p, (1920, 1080))
        cp.probe_audio_sample_rate.return_value = 48000
        from app.core.postprod import transitions as tr
        tr.probe_video_dimensions.side_effect = lambda p, **kw: dims.get(p, (1920, 1080))
        style = SubtitleStyle(font_size=48)
        srt = [{"start": 0.0, "end": 1.0, "text": "x"}]

        cp.compose_final_video(
            seg_paths=["a.mp4", "b.mp4", "c.mp4"],
            srt_entries=srt,
            style=style,
            fonts_dir="/fonts",
            tmp=self._tmp,
            project_name="p",
            final_render_opts={"clip_scale_width": "1920", "clip_scale_height": "1080"},
            normalize_audio=False,
            segment_transition_ins=["hard_cut", "hard_cut", "hard_cut"],
            transition_dissolve_sec=0.35,
            segment_fade_ms=0,
        )

        # 应存在一条「字幕烧录」命令：含 ass= 且输入是单个文件（-i 仅一个）
        burn_found = False
        for desc, cmd in self.ffmpeg_calls:
            has_ass = any("ass=" in str(a) for a in cmd)
            i_count = cmd.count("-i")
            if has_ass and i_count == 1:
                burn_found = True
                break
        self.assertTrue(burn_found, "应存在单文件 ass overlay 烧字幕步骤")

    def test_uniform_no_subtitle_still_concat_copy(self):
        """等大段 + 无字幕 → 仍走 concat -c copy 快路径（不受两步走重构影响）。"""
        from app.core.subtitle import composer as cp

        cp.probe_video_dimensions.return_value = (1920, 1080)
        cp.probe_audio_sample_rate.return_value = 48000

        cp.compose_final_video(
            seg_paths=["a.mp4", "b.mp4", "c.mp4"],
            srt_entries=[],
            style=None,
            fonts_dir="",
            tmp=self._tmp,
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
        copy_idx = cmd.index("-c")
        self.assertEqual(cmd[copy_idx + 1], "copy")


if __name__ == "__main__":
    unittest.main()
