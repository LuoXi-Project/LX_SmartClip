"""动作：剪辑方案生成（混剪）与成片落地。

- mix_edit_plan：直调 /api/auto-edit/mix-edit-plan 的编排函数（同步返回 Plan）
- realize_plan：通过 _launch_realize_job 启动 realize 后台 job 并等待成片
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from . import WorkflowActionError, action

if TYPE_CHECKING:
    from ..context import WorkflowContext


@action(
    "mix_edit_plan",
    title="混剪方案生成",
    description=(
        "基于已预处理素材生成混剪方案（Plan）。默认「关闭全部原声 + AI 生成旁白文案再 TTS」"
        "（mute_all_original / ai_tts_llm），适合文案驱动的成片；也可切回保留原声模式。"
    ),
    input_schema={
        "video_ids": {"type": "string[]", "required": True, "description": "参与剪辑的素材 ID（需已完成预处理）"},
        "user_prompt": {"type": "string", "required": False, "description": "剪辑诉求/文案；ai_tts_llm 模式必填，用于 AI 生成旁白"},
        "mix_audio_mode": {"type": "string", "required": False, "description": "keep_original=保留原声；mute_all_original=关闭全部原声（默认）", "enum": ["keep_original", "mute_all_original"]},
        "mute_audio_track": {"type": "string", "required": False, "description": "关闭原声时的音轨：ai_tts_llm=AI 旁白（默认）/ ai_tts_asr=原话 TTS / bgm_only=仅 BGM", "enum": ["ai_tts_llm", "ai_tts_asr", "bgm_only"]},
        "target_duration_sec": {"type": "number", "required": False, "description": "目标成片时长（秒），超长自动裁剪"},
    },
    output_schema={
        "plan": "剪辑方案（Plan JSON，供 realize_plan 使用）",
        "estimated_duration_sec": "预计成片时长",
        "summary": "方案摘要",
    },
    example={
        "video_ids": "${steps.wait_process.video_ids}",
        "user_prompt": "${inputs.copy_text}",
        "mix_audio_mode": "mute_all_original",
        "mute_audio_track": "ai_tts_llm",
    },
)
async def run_mix_edit_plan(ctx: "WorkflowContext", params: dict) -> dict:
    from app.api.auto_edit import mix_edit_plan
    from app.models.auto_edit import MixEditPlanRequest

    video_ids = [str(v) for v in (params.get("video_ids") or []) if str(v)]
    if not video_ids:
        raise WorkflowActionError("mix_edit_plan 需要 video_ids（非空）")

    mix_audio_mode = str(params.get("mix_audio_mode") or "mute_all_original")
    mute_audio_track = str(params.get("mute_audio_track") or "ai_tts_llm")
    user_prompt = str(params.get("user_prompt") or params.get("copy_text") or "").strip() or None

    req = MixEditPlanRequest(
        video_ids=video_ids,
        mix_audio_mode=mix_audio_mode,
        mute_audio_track=mute_audio_track,
        target_duration_sec=params.get("target_duration_sec") or None,
        user_prompt=user_prompt,
    )
    try:
        resp = await mix_edit_plan(req)
    except HTTPException as exc:
        raise WorkflowActionError(f"混剪方案生成失败：{exc.detail}") from exc

    if not resp.plans:
        raise WorkflowActionError("混剪方案为空：请确认素材已预处理且有可用画面")
    plan = resp.plans[0]
    return {
        "plan": plan.model_dump(mode="json"),
        "plan_id": getattr(plan, "plan_id", None),
        "estimated_duration_sec": getattr(plan, "estimated_duration_sec", None),
        "summary": getattr(plan, "summary", None) or "",
    }


@action(
    "realize_plan",
    title="渲染成片",
    description=(
        "把剪辑方案（Plan）落地为成片视频：TTS 配音、字幕烧录、后期母版处理，"
        "完成后自动记录到成片库。为后台渲染任务，动作会等待其完成。"
    ),
    input_schema={
        "plan": {"type": "object", "required": True, "description": "剪辑方案 JSON（来自 mix_edit_plan 输出）"},
        "include_subtitle": {"type": "boolean", "required": False, "description": "是否烧录字幕，默认 true"},
        "force_tts_pipeline": {"type": "boolean", "required": False, "description": "强制走 TTS 成片管线（旁白方案建议 true）"},
        "project_name": {"type": "string", "required": False, "description": "成片项目名（默认自动生成）"},
    },
    output_schema={
        "url": "成片文件 URL（/storage/...，可直接下载）",
        "filename": "成片文件名",
        "job_id": "渲染子任务 ID",
    },
    example={
        "plan": "${steps.plan.plan}",
        "include_subtitle": True,
        "force_tts_pipeline": True,
    },
)
async def run_realize_plan(ctx: "WorkflowContext", params: dict) -> dict:
    from app.api.auto_edit import _launch_realize_job
    from app.models.auto_edit import AutoEditRealizeRequest, Plan

    plan_raw = params.get("plan")
    if not isinstance(plan_raw, dict) or not plan_raw:
        raise WorkflowActionError("realize_plan 需要 plan 对象（来自 mix_edit_plan 输出）")
    try:
        plan = Plan(**plan_raw)
    except Exception as exc:
        raise WorkflowActionError(f"plan 结构不合法：{str(exc)[:200]}") from exc

    req = AutoEditRealizeRequest(
        plan=plan,
        include_subtitle=bool(params.get("include_subtitle", True)),
        force_tts_pipeline=bool(params.get("force_tts_pipeline", False)),
        project_name=params.get("project_name") or None,
    )
    try:
        job_id = await _launch_realize_job(req)
    except HTTPException as exc:
        raise WorkflowActionError(f"成片任务启动失败：{exc.detail}") from exc

    ctx.child_job_ids.append(job_id)   # realize 自建 job，手动登记以便级联取消
    result = await ctx.wait_job(job_id, title="渲染成片")

    url = str(result.get("url") or "")
    if not url:
        raise WorkflowActionError(f"渲染完成但未返回成片地址（result={str(result)[:200]}）")
    return {
        "url": url,
        "filename": result.get("filename") or "",
        "job_id": job_id,
    }
