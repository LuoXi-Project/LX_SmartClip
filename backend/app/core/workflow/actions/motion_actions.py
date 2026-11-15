"""动作：动效渲染（HyperFrames HTML 合成 → MP4）。

render_composition：同步执行渲染（内部走 motion_render job 的执行体，不另起子任务），
                    输出成片路径/URL 与预览地址，供后续发布等步骤引用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.jobs import check_cancel

from . import WorkflowActionError, action

if TYPE_CHECKING:
    from ..context import WorkflowContext


@action(
    "render_composition",
    title="动效渲染",
    description=(
        "把 HyperFrames HTML 合成渲染成 MP4 成片（标题卡/片头/VFX/带动效字幕）。"
        "html 为完整合成文档（data-* 时序 + GSAP 暂停时间轴）。"
        "渲染耗时与时长×分辨率成正比，1080p 约 1 秒成片需 1~3 分钟。"
    ),
    input_schema={
        "html": {"type": "string", "required": True, "description": "完整合成 HTML"},
        "title": {"type": "string", "required": False, "description": "成片标题（入 renders 库）"},
        "fps": {"type": "integer", "required": False, "description": "帧率，默认 30"},
        "quality": {"type": "string", "required": False, "description": "draft / standard / high，默认 standard"},
    },
    output_schema={
        "video_url": "成片访问 URL",
        "output_path": "成片绝对路径",
        "preview_url": "合成预览 URL（浏览器可播）",
        "renders_id": "renders 库记录 ID",
        "duration": "成片时长（秒）",
    },
    example={"html": "<!doctype html>…合成…", "title": "片头", "fps": 30},
)
async def run_render_composition(ctx: "WorkflowContext", params: dict) -> dict:
    from app.core.motion import renderer
    from app.core.motion.runtime import MotionRuntimeError

    html = str(params.get("html") or "")
    if not html.strip():
        raise WorkflowActionError("render_composition 需要 html（非空）")

    async def _on_event(event: dict) -> None:
        await check_cancel(ctx.job_id)
        if event.get("t") == "progress":
            frames = event.get("framesRendered")
            total = event.get("totalFrames")
            msg = f"动效渲染：{event.get('message') or '进行中'}"
            if frames is not None and total:
                msg += f"（{frames}/{total} 帧）"
            await ctx.reporter.send(ctx.current_step, "running", msg, {})

    try:
        result = await renderer.render_composition_html(
            html,
            title=str(params.get("title") or "动效合成"),
            fps=int(params.get("fps") or 30),
            quality=str(params.get("quality") or "standard"),
            on_event=_on_event,
        )
    except MotionRuntimeError as e:
        raise WorkflowActionError(str(e)) from e
    except renderer.MotionRenderError as e:
        raise WorkflowActionError(str(e)[:400]) from e
    return {
        "video_url": result["video_url"],
        "output_path": result["output_path"],
        "preview_url": result["preview_url"],
        "renders_id": result.get("renders_id"),
        "duration": result.get("duration"),
    }
