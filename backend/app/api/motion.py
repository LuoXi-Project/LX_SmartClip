"""动效渲染 API：运行时就绪态/自举、渲染任务（job）、合成预览与静态文件。"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app.core.motion import renderer, runtime
from app.core.motion.runtime import MotionRuntimeError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/motion", tags=["motion"])

_RUNTIME_SCRIPT_TAG = '<script src="/api/motion/runtime.js"></script>'


# ── 运行时 ──────────────────────────────────────────────────────────────────


@router.get("/runtime/status")
async def motion_runtime_status():
    return runtime.runtime_status()


@router.post("/runtime/bootstrap")
async def motion_runtime_bootstrap():
    """开发环境自装渲染依赖（npm install，打包版无需）。"""
    from app.jobs import JobReporter, create_job, launch_job, update_job_status

    job = await create_job(kind="motion_bootstrap", initial_step="install")
    job_id = job["id"]

    async def _run() -> None:
        reporter = JobReporter(job_id)
        await reporter.send("install", "running", "安装动效渲染依赖（npm install）…")
        try:
            status = await runtime.bootstrap_runtime(
                on_log=lambda line: None,   # npm 输出太碎，不逐行刷库；失败信息在异常里
            )
            await update_job_status(job_id, "done", result=status)
            await reporter.send("done", "done", "渲染依赖就绪", {"result": status})
        except Exception as e:  # noqa: BLE001
            logger.exception("motion bootstrap job failed")
            await reporter.send("error", "error", f"依赖安装失败: {e}")
            await update_job_status(job_id, "error", error_message=str(e)[:500])

    launch_job(job_id, _run())
    return {"ok": True, "job_id": job_id}


# ── 渲染任务 ────────────────────────────────────────────────────────────────


class MotionRenderRequest(BaseModel):
    html: str
    title: str = "动效合成"
    fps: int = 30
    quality: str = "standard"
    assets: dict[str, str] | None = None


@router.post("/render")
async def motion_render(req: MotionRenderRequest):
    """后台渲染一个 HyperFrames 合成（返回 job_id，SSE/WS 订阅进度）。"""
    if not req.html.strip():
        raise HTTPException(status_code=400, detail="html 不能为空")
    if not (1 <= req.fps <= 60):
        raise HTTPException(status_code=400, detail="fps 需在 1~60")
    status = runtime.runtime_status()
    if not status["ready"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "动效渲染运行时不就绪",
                "missing": status["missing"],
                "bootstrap": "/api/motion/runtime/bootstrap" if status["node"]["ok"] else None,
            },
        )
    try:
        job_id = await renderer.launch_motion_render_job(
            html=req.html,
            title=req.title,
            fps=req.fps,
            quality=req.quality,
            assets=req.assets,
        )
    except MotionRuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"ok": True, "job_id": job_id}


# ── 合成文件与预览 ──────────────────────────────────────────────────────────


def _safe_composition_file(comp_id: str, rel: str) -> Path:
    try:
        base = renderer.composition_dir(comp_id).resolve()
    except renderer.MotionRenderError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    target = (base / rel).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=403, detail="禁止访问合成目录之外的路径")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return target


@router.get("/compositions/{comp_id}/preview")
async def composition_preview(comp_id: str):
    """预览页：index.html 注入 HyperFrames 浏览器 runtime（iframe 直接可播）。"""
    entry = _safe_composition_file(comp_id, "index.html")
    html = entry.read_text(encoding="utf-8", errors="replace")
    if _RUNTIME_SCRIPT_TAG not in html:
        if "<head>" in html:
            html = html.replace("<head>", f"<head>{_RUNTIME_SCRIPT_TAG}", 1)
        elif "<html" in html:
            html = html.replace("<html", f"{_RUNTIME_SCRIPT_TAG}<html", 1)
        else:
            html = _RUNTIME_SCRIPT_TAG + html
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.get("/compositions/{comp_id}/files/{file_path:path}")
async def composition_file(comp_id: str, file_path: str):
    """合成静态资源（组合内相对路径引用的 js/css/json 等）。"""
    target = _safe_composition_file(comp_id, file_path)
    return FileResponse(target)


@router.get("/runtime.js")
async def runtime_js():
    """HyperFrames 浏览器 runtime IIFE（预览注入用）。"""
    path = runtime.runtime_iife_path()
    if not path:
        raise HTTPException(status_code=404, detail="渲染依赖未安装，无法提供预览 runtime")
    return FileResponse(path, media_type="application/javascript")
