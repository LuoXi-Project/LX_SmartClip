"""Agent 动效工具单元测试：注册/风险档位、预览落盘、渲染启动（mock job）、确认卡文案。"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.agent.orchestrator import _confirm_preview
from app.agent.tools import register_all_tools
from app.agent.tool_registry import REGISTRY, AgentContext, invoke, needs_confirm
from app.core.motion import runtime
from app.models.agent import WorkspaceState

_CTX = AgentContext(session_id="s", workspace=WorkspaceState(session_id="s"))

_HTML = """<!doctype html>
<html><head><meta charset="UTF-8"/></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="1"
     data-width="320" data-height="180">
  <h1 id="t" class="clip" data-start="0" data-duration="1" data-track-index="0">Hi</h1>
</div>
<script>window.__timelines = window.__timelines || {}; window.__timelines["main"] = {seek(){}};</script>
</body></html>"""


@pytest_asyncio.fixture(autouse=True)
async def _setup():
    register_all_tools()
    yield
    # 清理预览产生的合成目录
    import shutil

    for child in runtime.compositions_dir().iterdir():
        if child.is_dir() and not list(child.glob("*.lock")):
            shutil.rmtree(child, ignore_errors=True)


def test_motion_tools_registered_with_risk():
    assert REGISTRY["preview_composition"].risk == "L1"
    assert REGISTRY["render_composition"].risk == "L2"
    assert REGISTRY["get_motion_runtime_status"].risk == "L0"
    # L2 在 ask 档需确认
    assert needs_confirm(REGISTRY["render_composition"], _CTX) is True


@pytest.mark.asyncio
async def test_preview_composition_saves_and_returns_artifact():
    if not runtime.runtime_status()["ready"]:
        pytest.skip("运行时不就绪（无 Node/依赖）")
    result = await invoke("preview_composition", {"html": _HTML, "title": "测试"}, _CTX)
    assert result.ok, result.error
    assert result.artifact and result.artifact.payload["preview_url"].startswith("/api/motion/compositions/")
    comp_id = result.artifact.id
    assert (runtime.compositions_dir() / comp_id / "index.html").is_file()


@pytest.mark.asyncio
async def test_preview_rejects_empty_html():
    result = await invoke("preview_composition", {"html": "  "}, _CTX)
    assert not result.ok


@pytest.mark.asyncio
async def test_render_composition_launches_job(monkeypatch):
    from app.core.motion import renderer as renderer_mod

    async def _fake_launch(**kwargs):
        assert kwargs["html"] == _HTML
        assert kwargs["fps"] == 30
        return "job-123"

    # 跳过就绪检查：monkeypatch runtime_status
    monkeypatch.setattr(
        "app.core.motion.runtime.runtime_status",
        lambda: {"ready": True, "missing": [], "node": {"ok": True, "path": "x"},
                 "node_modules": {"ok": True}, "chromium": {"ok": True}, "ffmpeg": {"ok": True}},
    )
    monkeypatch.setattr(renderer_mod, "launch_motion_render_job", _fake_launch)
    result = await invoke(
        "render_composition", {"html": _HTML, "title": "测试渲染"}, _CTX
    )
    assert result.ok, result.error
    assert result.job_id == "job-123"
    assert result.artifact.payload["status"] == "running"
    assert "job_id=job-123" in result.summary


@pytest.mark.asyncio
async def test_get_motion_runtime_status_runs():
    result = await invoke("get_motion_runtime_status", {}, _CTX)
    assert result.ok


def test_confirm_preview_texts():
    msg = _confirm_preview(
        "render_composition", {"quality": "high", "fps": 60}, _CTX
    )
    assert "MP4" in msg and "high" in msg
