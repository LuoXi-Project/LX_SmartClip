"""动效运行时/渲染器单元测试：路径解析、就绪态、合成落盘防穿越、渲染桥文件。

依赖本机真实环境（Node/Chromium/FFmpeg）的断言在缺环境时自动跳过；
node_modules 已 bootstrap 的开发机上走全量断言。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.motion import renderer, runtime


def test_bridge_files_shipped():
    pkg = runtime.BRIDGE_DIR / "package.json"
    assert pkg.is_file(), "渲染桥 package.json 应随代码分发"
    deps = json.loads(pkg.read_text(encoding="utf-8"))["dependencies"]
    assert deps["@hyperframes/producer"] == runtime.PRODUCER_TESTED_VERSION
    assert (runtime.BRIDGE_DIR / "render.mjs").is_file()


def test_runtime_status_shape():
    status = runtime.runtime_status()
    for key in ("ready", "missing", "node", "node_modules", "chromium", "ffmpeg"):
        assert key in status
    assert isinstance(status["missing"], list)
    if status["ready"]:
        assert runtime.node_modules_dir() is not None
        assert runtime.producer_entry() is not None
        assert runtime.chromium_executable()
        assert status["node_modules"]["source"] in ("workspace", "bundled")


def test_chromium_resolution_on_dev_machine():
    """开发仓库自带 ms-playwright：chromium-1228 全量版应被解析出来。"""
    chrome = runtime.chromium_executable()
    if not chrome:
        pytest.skip("本机无 Chromium（非开发仓库环境）")
    assert chrome.lower().endswith(".exe") or Path(chrome).exists()


def test_save_composition_and_traversal_guard(tmp_path):
    comp_id = renderer.new_composition_id()
    assert len(comp_id) == 12
    entry = renderer.save_composition(
        comp_id,
        "<!doctype html><html>ok</html>",
        assets={"style/main.css": "body{}"},
    )
    assert entry.is_file() and entry.parent.name == comp_id
    assert (entry.parent / "style" / "main.css").is_file()
    # 路径穿越拒绝
    with pytest.raises(renderer.MotionRenderError):
        renderer.save_composition("x" * 12, "<html></html>", assets={"../evil.txt": "x"})
    with pytest.raises(renderer.MotionRenderError):
        renderer.save_composition("x" * 12, "<html></html>", assets={"/abs/evil.txt": "x"})
    # 非法合成 ID
    with pytest.raises(renderer.MotionRenderError):
        renderer.composition_dir("../etc")


def test_bridge_env_points_to_bundled_binaries():
    env = renderer._bridge_env()
    if runtime.chromium_executable():
        assert Path(env["HF_CHROME_PATH"]).is_file()
    if runtime.node_modules_dir():
        assert env.get("HF_PRODUCER_ENTRY")
    # ffmpeg/ffprobe 注入（缺省取 FF*_BIN；空串不影响渲染桥，producer 会跳过空值）
    assert "HYPERFRAMES_FFMPEG_PATH" in env and "HYPERFRAMES_FFPROBE_PATH" in env


@pytest.mark.asyncio
async def test_run_render_bridge_rejects_bad_quality(tmp_path):
    with pytest.raises(renderer.MotionRenderError):
        await renderer.run_render_bridge(tmp_path, tmp_path / "o.mp4", quality="ultra")
