"""动作：Agent 动效工具——写 HyperFrames HTML 合成并渲染成 MP4（详见 motion-graphics 技能）。

- preview_composition（L1）：只落盘不渲染，工作台立刻 iframe 预览（浏览器可直接播放）
- render_composition（L2）：后台渲染成 MP4（长任务，job 进度可查）
- get_motion_runtime_status（L0）：Node/Chromium/依赖就绪态
"""

from __future__ import annotations

import logging
from typing import Any

from app.agent.tool_registry import AgentContext, ToolSpec, register
from app.models.agent import ArtifactRef, ToolResult

logger = logging.getLogger(__name__)

_HTML_CHAR_LIMIT = 200_000


def _runtime_not_ready_result() -> ToolResult | None:
    from app.core.motion.runtime import MotionRuntimeError, runtime_status

    status = runtime_status()
    if status["ready"]:
        return None
    err = MotionRuntimeError(status["missing"])
    return ToolResult(
        ok=False,
        summary="",
        error=str(err),
    )


async def _preview_composition(_ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    html = str(args.get("html") or "")
    if not html.strip():
        return ToolResult(ok=False, summary="", error="html 不能为空")
    if len(html) > _HTML_CHAR_LIMIT:
        return ToolResult(ok=False, summary="", error=f"合成 HTML 超过 {_HTML_CHAR_LIMIT} 字符上限")
    not_ready = _runtime_not_ready_result()
    if not_ready:   # 预览也需要 runtime.js（依赖已装才能注入浏览器运行时）
        return not_ready
    from app.core.motion import renderer

    comp_id = renderer.new_composition_id()
    try:
        renderer.save_composition(comp_id, html)
    except renderer.MotionRenderError as e:
        return ToolResult(ok=False, summary="", error=str(e))
    preview_url = f"/api/motion/compositions/{comp_id}/preview"
    artifact = ArtifactRef(
        type="video",
        id=comp_id,
        payload={
            "motion_kind": "preview",
            "title": str(args.get("title") or "动效合成"),
            "preview_url": preview_url,
            "video_url": None,
            "status": "preview",
        },
    )
    return ToolResult(
        ok=True,
        summary=f"合成已保存，预览：{preview_url}（工作台画布可直接播放）。确认效果后调用 render_composition 渲染成 MP4。",
        artifact=artifact,
    )


async def _render_composition(_ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    html = str(args.get("html") or "")
    if not html.strip():
        return ToolResult(ok=False, summary="", error="html 不能为空")
    if len(html) > _HTML_CHAR_LIMIT:
        return ToolResult(ok=False, summary="", error=f"合成 HTML 超过 {_HTML_CHAR_LIMIT} 字符上限")
    not_ready = _runtime_not_ready_result()
    if not_ready:
        return not_ready
    from app.core.motion import renderer

    fps = int(args.get("fps") or 30)
    if not (1 <= fps <= 60):
        return ToolResult(ok=False, summary="", error="fps 需在 1~60")
    quality = str(args.get("quality") or "standard")
    if quality not in ("draft", "standard", "high"):
        return ToolResult(ok=False, summary="", error="quality 只支持 draft/standard/high")
    try:
        job_id = await renderer.launch_motion_render_job(
            html=html,
            title=str(args.get("title") or "动效合成"),
            fps=fps,
            quality=quality,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("motion render 启动失败", exc_info=True)
        return ToolResult(ok=False, summary="", error=f"渲染任务启动失败：{str(e)[:300]}")
    # 立刻可预览：合成已落盘（job 内部会再写一份带 comp_id 的目录；这里给预览一个独立 comp）
    artifact = ArtifactRef(
        type="video",
        id=job_id,
        payload={
            "motion_kind": "render",
            "title": str(args.get("title") or "动效合成"),
            "job_id": job_id,
            "preview_url": None,   # 渲染中的合成目录由 job 管理，完成后 result 里带 preview_url
            "video_url": None,
            "status": "running",
            "fps": fps,
            "quality": quality,
        },
    )
    return ToolResult(
        ok=True,
        summary=(
            f"渲染任务已启动（job_id={job_id}，Chromium 逐帧捕获 + FFmpeg 编码，"
            f"约每 10 秒 30 帧出片）。可先告诉用户已开始；任务完成后结果含预览与成片地址。"
        ),
        artifact=artifact,
        job_id=job_id,
        next_suggestions=["渲染已在后台进行，可继续聊其他安排，稍后我汇报结果"],
    )


async def _get_motion_runtime_status(_ctx: AgentContext, _args: dict[str, Any]) -> ToolResult:
    from app.core.motion.runtime import runtime_status

    status = runtime_status()
    if status["ready"]:
        return ToolResult(ok=True, summary="动效渲染运行时就绪：\n" + "\n".join(
            f"- {k}：{status[k]['path']}" for k in ("node", "chromium", "ffmpeg") if status.get(k, {}).get("path")
        ))
    return ToolResult(
        ok=True,
        summary="动效渲染运行时不就绪：\n- " + "\n- ".join(status["missing"]),
    )


def register_motion_tools() -> None:
    register(
        ToolSpec(
            name="preview_composition",
            description=(
                "保存一个 HyperFrames HTML 合成并立即在工作台画布预览（不渲染）。"
                "用于动效迭代：先写合成→预览效果→满意后再 render_composition。"
                "合成写法见 motion-graphics 技能。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "html": {"type": "string", "description": "完整合成 HTML（含 data-* 时序属性与 GSAP 暂停时间轴）"},
                    "title": {"type": "string", "description": "显示标题"},
                },
                "required": ["html"],
            },
            risk="L1",
            handler=_preview_composition,
        )
    )
    register(
        ToolSpec(
            name="render_composition",
            description=(
                "把 HyperFrames HTML 合成渲染成 MP4 成片（后台长任务，Chromium 逐帧捕获）。"
                "标题卡/片头/VFX 短片/带动效字幕的成片都能做。先 preview_composition 预览满意后再渲染更稳。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "html": {"type": "string", "description": "完整合成 HTML"},
                    "title": {"type": "string", "description": "成片标题（入 renders 库）"},
                    "fps": {"type": "integer", "description": "帧率（默认 30，1~60）"},
                    "quality": {"type": "string", "enum": ["draft", "standard", "high"], "description": "画质（默认 standard）"},
                },
                "required": ["html"],
            },
            risk="L2",
            handler=_render_composition,
        )
    )
    register(
        ToolSpec(
            name="get_motion_runtime_status",
            description="查动效渲染运行时就绪态（Node/Chromium/FFmpeg/渲染依赖）。",
            parameters={"type": "object", "properties": {}, "required": []},
            risk="L0",
            handler=_get_motion_runtime_status,
        )
    )
