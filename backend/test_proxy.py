# -*- coding: utf-8 -*-
"""代理剪辑（proxy）单元测试：配置解析、缓存判定、needs_proxy、clip_map 接入。

不依赖真实 ffmpeg：mock probe_* 与 generate_proxy，断言逻辑分支。
真实转码 + 时间轴对齐由单独的 smoke 脚本验证。
"""
import os
import unittest
from unittest import mock


class ProxyConfigTest(unittest.TestCase):
    """代理配置解析（proxy_enabled / proxy_max_height）。"""

    def test_enabled_default_on(self):
        from app.core.material.proxy import _proxy_enabled_from_opts
        self.assertTrue(_proxy_enabled_from_opts({}))  # 默认启用
        self.assertTrue(_proxy_enabled_from_opts({"proxy_enabled": "on"}))
        self.assertTrue(_proxy_enabled_from_opts({"proxy_enabled": "1"}))

    def test_disabled(self):
        from app.core.material.proxy import _proxy_enabled_from_opts
        self.assertFalse(_proxy_enabled_from_opts({"proxy_enabled": "off"}))
        self.assertFalse(_proxy_enabled_from_opts({"proxy_enabled": "false"}))
        self.assertFalse(_proxy_enabled_from_opts({"proxy_enabled": "0"}))

    def test_max_height_default(self):
        from app.core.material.proxy import _proxy_max_height_from_opts
        self.assertEqual(_proxy_max_height_from_opts({}), 1080)
        self.assertEqual(_proxy_max_height_from_opts({"proxy_max_height": "720"}), 720)
        # 下限保护：过小无意义（0 → 下限 360）
        self.assertEqual(_proxy_max_height_from_opts({"proxy_max_height": "0"}), 360)
        self.assertEqual(_proxy_max_height_from_opts({"proxy_max_height": "100"}), 360)


class NeedsProxyTest(unittest.TestCase):
    """_needs_proxy：仅 >目标高度 才需代理。"""

    def setUp(self):
        self._p = mock.patch("app.core.material.proxy.probe_video_dimensions")
        self.mock_dims = self._p.start()

    def tearDown(self):
        mock.patch.stopall()

    def test_higher_than_target_needs_proxy(self):
        from app.core.material.proxy import _needs_proxy
        self.mock_dims.return_value = (3840, 2160)
        self.assertTrue(_needs_proxy("4k.mp4", 1080))

    def test_equal_target_no_proxy(self):
        from app.core.material.proxy import _needs_proxy
        self.mock_dims.return_value = (1920, 1080)
        self.assertFalse(_needs_proxy("1080p.mp4", 1080))

    def test_lower_than_target_no_proxy(self):
        from app.core.material.proxy import _needs_proxy
        self.mock_dims.return_value = (1280, 720)
        self.assertFalse(_needs_proxy("720p.mp4", 1080))


class ProxyCacheTest(unittest.TestCase):
    """_proxy_valid：文件存在性 + 时长对齐校验。"""

    def test_missing_file_invalid(self):
        from app.core.material.proxy import _proxy_valid
        self.assertFalse(_proxy_valid("/nonexistent/proxy.mp4", 10.0))

    def test_duration_mismatch_invalid(self):
        """代理时长与原片差异过大 → 无效（时间轴错位风险）。"""
        from app.core.material.proxy import _proxy_valid
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"x" * 100)
            path = f.name
        try:
            with mock.patch("app.core.material.proxy.probe_duration", return_value=5.0):
                # 原片 10s，代理 5s → 差 5s > tol(max(0.5, 0.1)) → 无效
                self.assertFalse(_proxy_valid(path, 10.0))
        finally:
            os.remove(path)

    def test_duration_match_valid(self):
        from app.core.material.proxy import _proxy_valid
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"x" * 100)
            path = f.name
        try:
            with mock.patch("app.core.material.proxy.probe_duration", return_value=10.0):
                self.assertTrue(_proxy_valid(path, 10.0))
        finally:
            os.remove(path)


class EnsureProxiesTest(unittest.TestCase):
    """ensure_proxies_for_clips：去重、缓存命中、失败回退、禁用时不生成。"""

    def test_disabled_returns_empty(self):
        from app.core.material.proxy import ensure_proxies_for_clips
        with mock.patch("app.core.material.proxy.generate_proxy") as gen:
            result = ensure_proxies_for_clips(
                [{"video_id": "v1", "video_file_path": "a.mp4"}],
                {"proxy_enabled": "off"},
            )
        self.assertEqual(result, {})
        gen.assert_not_called()

    def test_cache_hit_skips_generation(self):
        """已有有效代理 → 直接复用，不重新生成。"""
        from app.core.material.proxy import ensure_proxies_for_clips
        import tempfile
        tmpd = tempfile.mkdtemp()
        proxy_path = os.path.join(tmpd, "proxy.mp4")
        with open(proxy_path, "wb") as f:
            f.write(b"x" * 100)
        with mock.patch("app.core.material.proxy._proxy_path_for", return_value=proxy_path), \
             mock.patch("app.core.material.proxy._proxy_valid", return_value=True), \
             mock.patch("app.core.material.proxy.probe_video_dimensions", return_value=(3840, 2160)), \
             mock.patch("app.core.material.proxy.probe_duration", return_value=10.0), \
             mock.patch("app.core.material.proxy.generate_proxy") as gen, \
             mock.patch("app.utils.paths.resolve_stored_path", side_effect=lambda p: p), \
             mock.patch("os.path.isfile", return_value=True):
            result = ensure_proxies_for_clips(
                [{"video_id": "v1", "video_file_path": "4k.mp4"}],
                {"proxy_enabled": "on", "proxy_max_height": "1080"},
            )
        self.assertEqual(result, {"v1": proxy_path})
        gen.assert_not_called()  # 缓存命中，未重新生成

    def test_generation_failure_falls_back(self):
        """代理生成失败 → 不进返回表（调用方用原片），不抛异常。"""
        from app.core.material.proxy import ensure_proxies_for_clips
        with mock.patch("app.core.material.proxy._proxy_path_for", return_value="/tmp/p.mp4"), \
             mock.patch("app.core.material.proxy._proxy_valid", return_value=False), \
             mock.patch("app.core.material.proxy._needs_proxy", return_value=True), \
             mock.patch("app.core.material.proxy.probe_duration", return_value=10.0), \
             mock.patch("app.core.material.proxy.generate_proxy", side_effect=RuntimeError("fail")), \
             mock.patch("app.utils.paths.resolve_stored_path", side_effect=lambda p: p), \
             mock.patch("os.path.isfile", return_value=True):
            result = ensure_proxies_for_clips(
                [{"video_id": "v1", "video_file_path": "4k.mp4"}],
                {"proxy_enabled": "on"},
            )
        self.assertEqual(result, {})  # 失败，无代理

    def test_dedup_multiple_clips_same_video(self):
        """同一素材的多切片只生成一次代理。"""
        from app.core.material.proxy import ensure_proxies_for_clips
        import tempfile
        tmpd = tempfile.mkdtemp()
        gen_calls = []

        def _fake_gen(**kw):
            gen_calls.append(kw["src_path"])
            os.makedirs(os.path.dirname(kw["out_path"]), exist_ok=True)
            with open(kw["out_path"], "wb") as f:
                f.write(b"x" * 100)
            return kw["out_path"]

        # _proxy_valid：缓存检查（文件不存在）→False 触发生成；生成后校验 →True。
        # _fake_gen 会写入真实文件，按 os.path.isfile 判定生成与否。
        real_isfile = os.path.isfile

        def _valid_side_effect(path, ref_dur):
            return real_isfile(path)

        with mock.patch("app.core.material.proxy._proxy_path_for",
                        side_effect=lambda vid: os.path.join(tmpd, f"{vid}_proxy.mp4")), \
             mock.patch("app.core.material.proxy._proxy_valid", side_effect=_valid_side_effect), \
             mock.patch("app.core.material.proxy._needs_proxy", return_value=True), \
             mock.patch("app.core.material.proxy.probe_duration", return_value=10.0), \
             mock.patch("app.core.material.proxy.generate_proxy", side_effect=_fake_gen), \
             mock.patch("app.utils.paths.resolve_stored_path", side_effect=lambda p: p), \
             mock.patch("os.path.isfile", return_value=True):
            result = ensure_proxies_for_clips(
                [
                    {"id": "c1", "video_id": "v1", "video_file_path": "4k.mp4"},
                    {"id": "c2", "video_id": "v1", "video_file_path": "4k.mp4"},  # 同一素材
                    {"id": "c3", "video_id": "v2", "video_file_path": "4k2.mp4"},
                ],
                {"proxy_enabled": "on"},
            )
        self.assertEqual(len(gen_calls), 2)  # v1、v2 各一次，v1 的两个切片合并
        self.assertIn("v1", result)
        self.assertIn("v2", result)


class ClipMapWithProxyTest(unittest.TestCase):
    """_build_clip_map_with_proxy：代理替代 src_video_path，时间轴偏移复用。"""

    def test_proxy_replaces_src_path(self):
        from app.api.subtitle import _build_clip_map_with_proxy
        rows = [{"id": "c1", "video_id": "v1", "video_file_path": "4k.mp4",
                 "clip_path": "clip.mp4", "duration": 5.0,
                 "start_time": 2.0, "end_time": 7.0}]
        with mock.patch("app.api.subtitle.ensure_proxies_for_clips",
                        return_value={"v1": "/storage/v1/proxy_1080p.mp4"}):
            clip_map = _build_clip_map_with_proxy(
                rows, export_render_opts={}, proxy_opts={"proxy_enabled": "on"}
            )
        # src_video_path 应指向代理（而非原片 4k.mp4）
        self.assertEqual(clip_map["c1"]["src_video_path"], "/storage/v1/proxy_1080p.mp4")
        # src_start/src_end 直接复用（代理时间轴与原片对齐）
        self.assertEqual(clip_map["c1"]["src_start"], 2.0)
        self.assertEqual(clip_map["c1"]["src_end"], 7.0)

    def test_no_proxy_keeps_original_path(self):
        """无代理（≤目标分辨率或禁用）→ 保持原片路径。"""
        from app.api.subtitle import _build_clip_map_with_proxy
        rows = [{"id": "c1", "video_id": "v1", "video_file_path": "1080p.mp4",
                 "clip_path": "clip.mp4", "duration": 5.0,
                 "start_time": 0.0, "end_time": 5.0}]
        with mock.patch("app.api.subtitle.ensure_proxies_for_clips", return_value={}):
            clip_map = _build_clip_map_with_proxy(
                rows, export_render_opts={}, proxy_opts={"proxy_enabled": "on"}
            )
        # 无代理 → src_video_path 仍指向原片（resolve_stored_path 解析原片路径）
        self.assertTrue(clip_map["c1"]["src_video_path"].endswith("1080p.mp4"))


if __name__ == "__main__":
    unittest.main()
