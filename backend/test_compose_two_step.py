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
            mock.patch("app.core.subtitle.composer.probe_video_frame_rate", return_value=(30, 1)),
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


class SingleEncodeConcatBurnTest(unittest.TestCase):
    """纯硬切 + 字幕 → 单条 filter_complex 一次编码（合并 + 烧字幕合一，省双重编码）。"""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="lxtest_")
        self._patches = [
            mock.patch("app.core.subtitle.composer.probe_video_dimensions"),
            mock.patch("app.core.subtitle.composer.probe_audio_sample_rate", return_value=48000),
            mock.patch("app.core.subtitle.composer.probe_video_frame_rate", return_value=(30, 1)),
            mock.patch("app.core.subtitle.composer.run_ffmpeg"),
            mock.patch("app.core.subtitle.composer.write_concat_list"),
            mock.patch("app.core.subtitle.composer.build_ass", return_value="ASS_CONTENT"),
            mock.patch("app.core.subtitle.composer.os.path.isdir", return_value=True),
            # 拦截 _try_single_encode_concat_burn 内对 transitions 的调用
            mock.patch("app.core.postprod.transitions._resolve_target_canvas", return_value=(1920, 1080)),
            mock.patch("app.core.postprod.transitions.probe_video_dimensions"),
            mock.patch("app.core.postprod.transitions.probe_audio_sample_rate", return_value=48000),
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

    def test_hardcut_subtitle_single_encode(self):
        """纯硬切 + 混合分辨率 + 字幕 → 单条 filter_complex：scale+pad → concat → ass，1 次编码。"""
        from app.core.subtitle import composer as cp
        from app.core.postprod import transitions as tr
        from app.models.subtitle import SubtitleStyle

        dims = {"a.mp4": (1920, 1080), "b.mp4": (1280, 720), "c.mp4": (1920, 1080)}
        cp.probe_video_dimensions.side_effect = lambda p, **kw: dims.get(p, (1920, 1080))
        tr.probe_video_dimensions.side_effect = lambda p, **kw: dims.get(p, (1920, 1080))
        style = SubtitleStyle(font_size=48)
        srt = [{"start": 0.0, "end": 1.0, "text": "x"}]

        cp.compose_final_video_moviepy(
            seg_paths=["a.mp4", "b.mp4", "c.mp4"],
            srt_entries=srt,
            style=style,
            fonts_dir="/fonts",
            tmp=self._tmp,
            project_name="p",
            final_render_opts={"clip_vcodec": "h264_nvenc", "clip_preset": "p2"},
            normalize_audio=False,
            prefer_gpu=True,
            segment_transition_ins=["hard_cut", "hard_cut", "hard_cut"],
            transition_dissolve_sec=0.35,
            segment_fade_ms=0,
        )

        # 只应有一次 ffmpeg 编码调用（合并 + 烧字幕合一）
        encode_calls = [c for d, c in self.ffmpeg_calls if "-filter_complex" in c]
        self.assertEqual(
            len(encode_calls), 1,
            f"纯硬切+字幕应单次编码出片，实际 {len(encode_calls)} 次 filter_complex 调用",
        )
        cmd = encode_calls[0]
        fc = cmd[cmd.index("-filter_complex") + 1]
        # 一条链内完成：scale+pad（720p 段）+ concat=n=3 + ass 烧字幕
        self.assertIn("scale=1920:1080:force_original_aspect_ratio=decrease", fc)
        self.assertIn("concat=n=3", fc)
        self.assertIn("ass=", fc)
        # 不应有 concat demuxer + copy
        self.assertFalse(
            ("-f" in cmd and "concat" in cmd) and ("-c" in cmd and cmd[cmd.index("-c") + 1] == "copy"),
            "单次编码路径禁用 concat demuxer + copy",
        )

    def test_xfade_falls_back_to_two_step(self):
        """有 xfade 转场 → 不适用单次编码，回退两步管线。"""
        from app.core.subtitle import composer as cp
        from app.models.subtitle import SubtitleStyle

        cp.probe_video_dimensions.return_value = (1920, 1080)
        style = SubtitleStyle(font_size=48)
        srt = [{"start": 0.0, "end": 1.0, "text": "x"}]

        cp.compose_final_video_moviepy(
            seg_paths=["a.mp4", "b.mp4", "c.mp4"],
            srt_entries=srt,
            style=style,
            fonts_dir="/fonts",
            tmp=self._tmp,
            project_name="p2",
            final_render_opts={},
            normalize_audio=False,
            segment_transition_ins=["hard_cut", "cross_dissolve", "hard_cut"],
            transition_dissolve_sec=0.35,
            segment_fade_ms=0,
        )
        # 不应触发 single-encode concat+burn（有 dissolve）
        descs = [d for d, _ in self.ffmpeg_calls]
        self.assertFalse(
            any("single-encode concat+burn" in d for d in descs),
            "有 xfade 转场不应走单次编码路径",
        )

    def test_mixed_framerate_avoids_concat_demuxer(self):
        """段帧率不一致（30/25 混排）→ 必走 filter_complex，禁用 concat demuxer。

        回归场景（用户反馈，真实素材必现）：口播/TTS 段里 30fps(1/15360) 与
        25fps(1/12800) 混排时，concat demuxer 在段边界吐乱序 DTS → ffmpeg 丢帧 +
        复制上一帧 → 「部分段画面卡死、声音正常」。修复：帧率不一致时改走
        filter_complex（解码每段并 setpts 重排时间戳，drop=0，无卡死）。
        """
        from app.core.subtitle import composer as cp
        from app.core.postprod import transitions as tr
        from app.models.subtitle import SubtitleStyle

        cp.probe_video_dimensions.return_value = (1920, 1080)  # 画布统一
        tr.probe_video_dimensions.return_value = (1920, 1080)
        # 帧率混排：a/c=30fps，b=25fps（画布一致但 time_base 不同）
        fr = {"a.mp4": (30, 1), "b.mp4": (25, 1), "c.mp4": (30, 1)}
        cp.probe_video_frame_rate.side_effect = lambda p, **kw: fr.get(p, (30, 1))
        style = SubtitleStyle(font_size=48)
        srt = [{"start": 0.0, "end": 1.0, "text": "x"}]

        cp.compose_final_video_moviepy(
            seg_paths=["a.mp4", "b.mp4", "c.mp4"],
            srt_entries=srt,
            style=style,
            fonts_dir="/fonts",
            tmp=self._tmp,
            project_name="mixfr",
            final_render_opts={"clip_vcodec": "h264_nvenc", "clip_preset": "p2"},
            normalize_audio=False,
            prefer_gpu=True,
            segment_transition_ins=["hard_cut", "hard_cut", "hard_cut"],
            transition_dissolve_sec=0.35,
            segment_fade_ms=0,
        )

        descs = [d for d, _ in self.ffmpeg_calls]
        # 不能走 concat-demuxer（帧率不一致时会吐乱序 DTS → 画面卡死）
        self.assertFalse(
            any("concat-demuxer" in d for d in descs),
            "帧率不一致时禁用 concat demuxer（会卡死），应走 filter_complex",
        )
        # 应走 filter_complex（解码每段重排时间戳）
        self.assertTrue(
            any("-filter_complex" in c for _, c in self.ffmpeg_calls),
            "帧率不一致应走 filter_complex 路径",
        )


class NoConcatCopyRegressionTest(unittest.TestCase):
    """回归守卫：合并阶段绝不用 concat demuxer + copy（会卡死，多次教训）。

    无论段是否统一，合并都用 concat filter（解码→重编码一次）。copy 是字节级拼接，
    对段边界时间戳/SPS 细微差异敏感，实测会造成「部分段画面冻结、声音正常」。
    """

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="lxtest_")
        self._patches = [
            mock.patch("app.core.subtitle.composer.probe_video_dimensions"),
            mock.patch("app.core.subtitle.composer.probe_audio_sample_rate", return_value=48000),
            mock.patch("app.core.subtitle.composer.probe_video_frame_rate", return_value=(30, 1)),
            mock.patch("app.core.subtitle.composer.run_ffmpeg"),
            mock.patch("app.core.subtitle.composer.write_concat_list"),
            mock.patch("app.core.subtitle.composer.build_ass", return_value="ASS_CONTENT"),
            mock.patch("app.core.subtitle.composer.os.path.isdir", return_value=True),
            mock.patch("app.core.postprod.transitions._resolve_target_canvas", return_value=(1920, 1080)),
            mock.patch("app.core.postprod.transitions.probe_video_dimensions"),
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

    def test_uniform_segments_no_concat_copy(self):
        """段统一 → 走 concat-demuxer+burn（顺序读+重编码），不走 concat copy。"""
        from app.core.subtitle import composer as cp
        from app.core.postprod import transitions as tr
        from app.models.subtitle import SubtitleStyle

        cp.probe_video_dimensions.return_value = (1920, 1080)
        tr.probe_video_dimensions.return_value = (1920, 1080)
        style = SubtitleStyle(font_size=48)
        srt = [{"start": 0.0, "end": 1.0, "text": "x"}]

        cp.compose_final_video_moviepy(
            seg_paths=["a.mp4", "b.mp4", "c.mp4"],
            srt_entries=srt,
            style=style,
            fonts_dir="/fonts",
            tmp=self._tmp,
            project_name="p",
            final_render_opts={"clip_vcodec": "h264_nvenc", "clip_preset": "p2"},
            normalize_audio=False,
            prefer_gpu=True,
            segment_transition_ins=["hard_cut", "hard_cut", "hard_cut"],
            transition_dissolve_sec=0.35,
            segment_fade_ms=0,
        )

        for desc, cmd in self.ffmpeg_calls:
            # 绝不能出现 concat demuxer + copy（会卡死）
            has_concat_demuxer = "-f" in cmd and "concat" in cmd
            has_any_copy = (
                ("-c" in cmd and cmd[cmd.index("-c") + 1] == "copy")
                or ("-c:v" in cmd and cmd[cmd.index("-c:v") + 1] == "copy")
            )
            self.assertFalse(
                has_concat_demuxer and has_any_copy,
                f"合并阶段禁用 concat demuxer + copy（会卡死）。desc={desc}",
            )

    def test_mixed_resolution_no_concat_copy(self):
        """段画布不统一 → single-encode，同样禁用 concat copy。"""
        from app.core.subtitle import composer as cp
        from app.core.postprod import transitions as tr
        from app.models.subtitle import SubtitleStyle

        dims = {"a.mp4": (1920, 1080), "b.mp4": (1280, 720), "c.mp4": (1920, 1080)}
        cp.probe_video_dimensions.side_effect = lambda p, **kw: dims.get(p, (1920, 1080))
        tr.probe_video_dimensions.side_effect = lambda p, **kw: dims.get(p, (1920, 1080))
        style = SubtitleStyle(font_size=48)
        srt = [{"start": 0.0, "end": 1.0, "text": "x"}]

        cp.compose_final_video_moviepy(
            seg_paths=["a.mp4", "b.mp4", "c.mp4"],
            srt_entries=srt,
            style=style,
            fonts_dir="/fonts",
            tmp=self._tmp,
            project_name="p2",
            final_render_opts={"clip_vcodec": "h264_nvenc", "clip_preset": "p2"},
            normalize_audio=False,
            prefer_gpu=True,
            segment_transition_ins=["hard_cut", "hard_cut", "hard_cut"],
            transition_dissolve_sec=0.35,
            segment_fade_ms=0,
        )

        for desc, cmd in self.ffmpeg_calls:
            has_concat_demuxer = "-f" in cmd and "concat" in cmd
            has_any_copy = (
                ("-c" in cmd and cmd[cmd.index("-c") + 1] == "copy")
                or ("-c:v" in cmd and cmd[cmd.index("-c:v") + 1] == "copy")
            )
            self.assertFalse(
                has_concat_demuxer and has_any_copy,
                f"段不统一也禁用 concat demuxer + copy。desc={desc}",
            )

    def test_uniform_segments_use_concat_demuxer_reencode(self):
        """段统一画布 → 走 concat-demuxer+burn（顺序读+重编码），不用 filter_complex N输入。"""
        from app.core.subtitle import composer as cp
        from app.core.postprod import transitions as tr
        from app.models.subtitle import SubtitleStyle

        cp.probe_video_dimensions.return_value = (1920, 1080)
        tr.probe_video_dimensions.return_value = (1920, 1080)
        style = SubtitleStyle(font_size=48)
        srt = [{"start": 0.0, "end": 1.0, "text": "x"}]

        cp.compose_final_video_moviepy(
            seg_paths=["a.mp4", "b.mp4", "c.mp4"],
            srt_entries=srt,
            style=style,
            fonts_dir="/fonts",
            tmp=self._tmp,
            project_name="p3",
            final_render_opts={"clip_vcodec": "h264_nvenc", "clip_preset": "p2"},
            normalize_audio=False,
            prefer_gpu=True,
            segment_transition_ins=["hard_cut", "hard_cut", "hard_cut"],
            transition_dissolve_sec=0.35,
            segment_fade_ms=0,
        )

        descs = [d for d, _ in self.ffmpeg_calls]
        # 应走 concat-demuxer+burn（顺序读，1输入流）
        self.assertTrue(
            any("concat-demuxer" in d for d in descs),
            "段统一应走 concat-demuxer+burn 路径",
        )
        # 不应走 filter_complex N输入（demuxer 路径更快）
        filter_calls = [c for d, c in self.ffmpeg_calls if "-filter_complex" in c]
        self.assertFalse(
            filter_calls,
            "段统一时不应走 filter_complex（应走 concat-demuxer）",
        )


if __name__ == "__main__":
    unittest.main()
