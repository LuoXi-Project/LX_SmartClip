"""渲染编排：组合 HTML 落盘 → node 渲染桥子进程 → job 进度 → renders 库。

用法（与 _launch_burn_job 同构）：
    job_id = await launch_motion_render_job(html=..., title=..., fps=30)
内部：
    ensure_ready() → compositions/<rid>/index.html → node render.mjs
    → stdout JSON 行解析为进度 → 成片落 storage/motion/<rid>.mp4 → renders 入库
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from app.core.motion import runtime
from app.utils.paths import ensure_storage_subpath

logger = logging.getLogger(__name__)

_COMP_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{6,64}$")
DEFAULT_FPS = 30
_ALLOWED_QUALITY = ("draft", "standard", "high")


class MotionRenderError(RuntimeError):
    pass


def new_composition_id() -> str:
    return uuid.uuid4().hex[:12]


def composition_dir(comp_id: str) -> Path:
    if not _COMP_ID_RE.match(comp_id):
        raise MotionRenderError(f"非法合成 ID：{comp_id}")
    return runtime.compositions_dir() / comp_id


def save_composition(comp_id: str, html: str, *, assets: dict[str, str] | None = None) -> Path:
    """落盘一个合成（index.html + 可选静态资源 {相对路径: 内容}）。"""
    d = composition_dir(comp_id)
    d.mkdir(parents=True, exist_ok=True)
    for rel, content in (assets or {}).items():
        # 防路径穿越：相对路径不允许 .. 与绝对路径
        if not rel or rel.startswith(("/", "\\")) or ".." in Path(rel).parts:
            raise MotionRenderError(f"非法资源路径：{rel}")
        target = d / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    entry = d / "index.html"
    entry.write_text(html, encoding="utf-8")
    return entry


def _bridge_env() -> dict[str, str]:
    """渲染桥子进程环境：浏览器/ffmpeg/producer 入口全部显式注入。"""
    from app.utils.bin_paths import apply_default_ffmpeg_environment

    apply_default_ffmpeg_environment()
    env = os.environ.copy()
    chrome = runtime.chromium_executable()
    if chrome:
        env["HF_CHROME_PATH"] = chrome
    env["HYPERFRAMES_FFMPEG_PATH"] = os.environ.get("FFMPEG_BIN") or ""
    env["HYPERFRAMES_FFPROBE_PATH"] = os.environ.get("FFPROBE_BIN") or ""
    entry = runtime.producer_entry()
    if entry:
        env["HF_PRODUCER_ENTRY"] = str(entry)
    return env


async def run_render_bridge(
    project_dir: Path,
    output_path: Path,
    *,
    fps: int = DEFAULT_FPS,
    quality: str = "standard",
    on_event: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> dict[str, Any]:
    """执行渲染桥，逐行回传事件；返回 done 事件。"""
    runtime.ensure_ready()
    if quality not in _ALLOWED_QUALITY:
        raise MotionRenderError(f"quality 只支持 {_ALLOWED_QUALITY}")
    env = _bridge_env()
    node = runtime.node_bin()
    bridge = runtime.render_bridge_path()
    proc = await asyncio.create_subprocess_exec(
        node, str(bridge),
        "--project", str(project_dir),
        "--output", str(output_path),
        "--fps", str(int(fps)),
        "--quality", quality,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(runtime.workspace_dir()),
    )
    assert proc.stdout is not None
    last_event: dict[str, Any] = {"t": "error", "error": "渲染桥无输出"}
    cancelled = False
    try:
        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            # 渲染桥 stdout 夹带 producer 的 [INFO] 人类可读日志，只认 JSON 行
            if not line.startswith("{"):
                logger.debug("[motion-render] %s", line[:200])
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            last_event = event
            if on_event:
                await on_event(event)
            if should_cancel and should_cancel():
                cancelled = True
                proc.kill()
                break
    finally:
        await proc.wait()
    if cancelled:
        raise MotionRenderError("渲染已取消")
    return last_event


async def render_composition_html(
    html: str,
    *,
    title: str = "动效合成",
    fps: int = DEFAULT_FPS,
    quality: str = "standard",
    assets: dict[str, str] | None = None,
    on_event: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> dict[str, Any]:
    """高层入口：写合成 → 渲染 → 入库，返回产物信息（含预览与成片地址）。"""
    from app.api.renders_db import record_render_from_path
    from app.utils.paths import storage_public_url_for_file

    comp_id = new_composition_id()
    entry_path = save_composition(comp_id, html, assets=assets)
    out_dir = ensure_storage_subpath("motion")
    output_path = Path(out_dir) / f"{comp_id}.mp4"

    async def _forward(event: dict[str, Any]) -> None:
        if on_event:
            await on_event({**event, "composition_id": comp_id})

    final = await run_render_bridge(
        entry_path.parent,   # 渲染桥的 projectDir = 含 index.html 的目录
        output_path,
        fps=fps,
        quality=quality,
        on_event=_forward,
        should_cancel=should_cancel,
    )
    if final.get("t") != "done":
        raise MotionRenderError(
            f"渲染失败：{str(final.get('error') or final)[:500]}"
            f"（stage={final.get('failedStage') or final.get('status') or 'unknown'}）"
        )
    if not output_path.is_file():
        raise MotionRenderError(f"渲染声称成功但产物不存在：{output_path}")

    render_id = await record_render_from_path(
        abs_path=str(output_path), source="motion", title=title or "动效合成"
    )
    return {
        "composition_id": comp_id,
        "output_path": str(output_path),
        "video_url": storage_public_url_for_file(str(output_path)),
        "preview_url": f"/api/motion/compositions/{comp_id}/preview",
        "renders_id": render_id,
        "duration": final.get("duration"),
        "total_frames": final.get("totalFrames"),
        "warnings": final.get("warnings") or [],
    }


# ── Job 包装（对齐 _launch_burn_job 模式）────────────────────────────────────


async def launch_motion_render_job(
    *,
    html: str,
    title: str = "动效合成",
    fps: int = DEFAULT_FPS,
    quality: str = "standard",
    assets: dict[str, str] | None = None,
) -> str:
    """后台渲染一个合成，返回 job_id（kind=motion_render，SSE/WS 可订阅）。"""
    from app.jobs import JobReporter, create_job, launch_job, update_job_status
    from app.jobs.runtime import check_cancel, is_cancelled

    job = await create_job(kind="motion_render", initial_step="render", ref_name=title)
    job_id = job["id"]

    async def _run() -> None:
        reporter = JobReporter(job_id)
        await reporter.send("render", "running", "动效渲染启动（Chromium 逐帧捕获 + FFmpeg 编码）…")

        async def _on_event(event: dict[str, Any]) -> None:
            await check_cancel(job_id)
            t = event.get("t")
            if t == "start":
                total = event.get("totalFrames")
                await reporter.send(
                    "render", "running", "开始捕获…",
                    {"composition_id": event.get("composition_id"), "total_frames": total},
                )
            elif t == "progress":
                frames = event.get("framesRendered")
                total = event.get("totalFrames")
                msg = event.get("message") or event.get("status") or "渲染中"
                detail = {"composition_id": event.get("composition_id")}
                if frames is not None and total:
                    detail["frames"] = frames
                    detail["total_frames"] = total
                    msg = f"{msg}（{frames}/{total} 帧）"
                await reporter.send("render", "running", msg, detail)

        try:
            result = await render_composition_html(
                html, title=title, fps=fps, quality=quality, assets=assets,
                on_event=_on_event, should_cancel=lambda: is_cancelled(job_id),
            )
            await update_job_status(job_id, "done", result=result)
            await reporter.send("done", "done", "动效渲染完成", {"result": result})
        except Exception as e:  # noqa: BLE001
            logger.exception("motion render job %s failed", job_id)
            await reporter.send("error", "error", f"动效渲染失败: {e}")
            await update_job_status(job_id, "error", error_message=str(e)[:500])

    launch_job(job_id, _run())
    return job_id
