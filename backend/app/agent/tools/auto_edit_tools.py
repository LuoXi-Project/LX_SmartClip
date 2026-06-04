from __future__ import annotations

import copy
from typing import Any

from app.agent.tool_registry import AgentContext, ToolSpec, register
from app.api.auto_edit import (
    export_jianying_draft_from_plan,
    generate_auto_edit_plan,
    realize_auto_edit_plan,
)
from app.models.agent import ArtifactRef, ToolResult
from app.agent.export_intent import plan_next_suggestions
from app.agent.media_merge import (
    include_subtitle_from_media,
    merge_bgm_from_media,
    subtitle_style_from_media,
)
from app.core.postprod.intent import parse_production_intent
from app.core.postprod.profile import apply_profile_patch, resolve_production_profile
from app.models.auto_edit import (
    AutoEditExportJianyingDraftRequest,
    AutoEditPlanRequest,
    AutoEditRealizeRequest,
    Plan,
)
from app.models.production import ProductionProfile


class _AgentRequestShim:
    """供 realize 路由检查断开用的最小 Request 替身。"""

    async def is_disconnected(self) -> bool:
        return False


async def _generate_plan(ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    video_ids = args.get("video_ids") or ctx.workspace.selected_video_ids
    if not video_ids:
        return ToolResult(ok=False, summary="", error="请先 set_selected_videos 或传入 video_ids")

    user_prompt = (args.get("user_prompt") or "").strip()
    if not user_prompt:
        user_prompt = (ctx.workspace.user_preferences.get("last_user_prompt") or "").strip()
    if not user_prompt:
        return ToolResult(ok=False, summary="", error="缺少 user_prompt（剪辑诉求）")

    # 用户话里若含制作诉求，自动解析到 workspace profile
    intent_patch = parse_production_intent(user_prompt)
    prefs = dict(ctx.workspace.user_preferences or {})
    if any(
        [
            intent_patch.preset_id,
            intent_patch.transition,
            intent_patch.audio,
            intent_patch.bgm,
            intent_patch.subtitle_motion,
        ]
    ):
        cur = resolve_production_profile(workspace_prefs=prefs)
        merged = apply_profile_patch(cur, intent_patch, respect_locks=True)
        prefs["production_profile"] = merged.model_dump()
        prefs["default_production_preset"] = merged.preset_id

    target = args.get("target_duration_sec")
    if target is None:
        target = ctx.workspace.user_preferences.get("target_duration_sec")

    req = AutoEditPlanRequest(
        video_ids=list(video_ids),
        user_prompt=user_prompt,
        mode=args.get("mode") or "auto",
        target_duration_sec=int(target) if target else None,
        num_plans=min(int(args.get("num_plans") or 1), 3),
    )
    try:
        resp = await generate_auto_edit_plan(req)
    except Exception as e:
        return ToolResult(ok=False, summary="", error=str(e))

    if not resp.plans:
        return ToolResult(ok=False, summary="", error="未生成任何方案")

    plan = resp.plans[0]
    plan_dict = plan.model_dump() if hasattr(plan, "model_dump") else dict(plan)
    plan_id = str(plan_dict.get("plan_id") or plan_dict.get("id") or "plan_1")

    plans_payload = [p.model_dump() if hasattr(p, "model_dump") else dict(p) for p in resp.plans]
    profile = resolve_production_profile(workspace_prefs=prefs)
    for i, p in enumerate(plans_payload):
        p["production_profile"] = profile.model_dump()
        plans_payload[i] = p

    mode = str(plan_dict.get("mode") or "auto")
    mode_cn = {"voiceover": "配音剪辑", "original": "原声剪辑", "auto": "自动混合"}.get(mode, mode)
    export_hint = {
        "voiceover": "适合「导出成片（配音版）」或剪映草稿二次精剪。",
        "original": "适合「导出成片（保留原声）」；若需 AI 配音可说「不保留原声，进行 tts 配音」。",
        "auto": "可先「导出成片」；原声诉求请说明后改用 original 或强制 TTS。",
    }.get(mode, "")
    return ToolResult(
        ok=True,
        summary=(
            f"已生成方案「{plan_dict.get('title') or plan_id}」（{mode_cn}），"
            f"约 {plan_dict.get('estimated_duration_sec', '?')} 秒。"
            f"制作：{profile.human_summary()}。{export_hint}"
        ),
        workspace_patch={
            "pipeline_phase": "plan",
            "plans": plans_payload,
            "active_plan_id": plan_id,
            "user_preferences": {**prefs, "last_user_prompt": user_prompt},
        },
        artifact=ArtifactRef(type="plan", id=plan_id, payload=plan_dict),
        next_suggestions=plan_next_suggestions(str(plan_dict.get("mode") or "auto")),
    )


async def _apply_plan_patch(ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    plan_id = (args.get("plan_id") or ctx.workspace.active_plan_id or "").strip()
    patch = args.get("patch")
    if not plan_id:
        return ToolResult(ok=False, summary="", error="缺少 plan_id")
    if not isinstance(patch, dict):
        return ToolResult(ok=False, summary="", error="patch 必须为对象")

    plans = copy.deepcopy(ctx.workspace.plans)
    idx = next((i for i, p in enumerate(plans) if str(p.get("plan_id")) == plan_id), None)
    if idx is None:
        return ToolResult(ok=False, summary="", error=f"未找到方案: {plan_id}")

    merged = copy.deepcopy(plans[idx])
    for key, val in patch.items():
        merged[key] = val
    plans[idx] = merged

    return ToolResult(
        ok=True,
        summary=f"已更新方案 {plan_id}",
        workspace_patch={"plans": plans, "active_plan_id": plan_id},
        artifact=ArtifactRef(type="plan", id=plan_id, payload=merged),
    )


async def _realize_plan(ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    plan_id = (args.get("plan_id") or ctx.workspace.active_plan_id or "").strip()
    if not plan_id:
        return ToolResult(ok=False, summary="", error="缺少 plan_id")

    raw = next((p for p in ctx.workspace.plans if str(p.get("plan_id")) == plan_id), None)
    if not raw:
        return ToolResult(ok=False, summary="", error=f"未找到方案: {plan_id}")

    try:
        plan = Plan(**raw)
    except Exception as e:
        return ToolResult(ok=False, summary="", error=f"方案结构无效: {e}")

    profile = resolve_production_profile(
        explicit=ProductionProfile.model_validate(raw["production_profile"])
        if raw.get("production_profile")
        else None,
        plan=plan,
        workspace_prefs=ctx.workspace.user_preferences or {},
    )

    prefs = ctx.workspace.user_preferences or {}
    media = prefs.get("media_config") if isinstance(prefs.get("media_config"), dict) else None
    plan = merge_bgm_from_media(plan, media)
    style = subtitle_style_from_media(media)
    include_sub = include_subtitle_from_media(
        media,
        default=bool(args.get("include_subtitle", True)),
    )

    req = AutoEditRealizeRequest(
        plan=plan,
        project_name=args.get("project_name") or plan.title or "agent_export",
        include_subtitle=include_sub,
        style=style,
        force_tts_pipeline=bool(
            args.get("force_tts_pipeline", plan.mode in ("voiceover", "auto"))
        ),
        production_profile=profile,
    )
    try:
        res = await realize_auto_edit_plan(req, _AgentRequestShim())  # type: ignore[arg-type]
    except Exception as e:
        return ToolResult(ok=False, summary="", error=str(e))

    export_entry = {
        "plan_id": plan_id,
        "filename": res.filename,
        "url": res.url,
        "mode": res.mode,
        "kind": "video",
    }
    last_exports = list(ctx.workspace.last_exports or [])
    last_exports.append(export_entry)

    return ToolResult(
        ok=True,
        summary=f"成片已生成（{profile.preset_id}）：{res.filename}。下载：{res.url}",
        workspace_patch={
            "pipeline_phase": "export",
            "last_exports": last_exports,
            "jobs": {"realize_job_id": plan_id},
        },
        artifact=ArtifactRef(type="export", id=res.filename, payload=export_entry),
        next_suggestions=["导出剪映草稿"],
    )


async def _export_jianying(ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    plan_id = (args.get("plan_id") or ctx.workspace.active_plan_id or "").strip()
    if not plan_id:
        return ToolResult(ok=False, summary="", error="缺少 plan_id")

    raw = next((p for p in ctx.workspace.plans if str(p.get("plan_id")) == plan_id), None)
    if not raw:
        return ToolResult(ok=False, summary="", error=f"未找到方案: {plan_id}")

    try:
        plan = Plan(**raw)
    except Exception as e:
        return ToolResult(ok=False, summary="", error=f"方案结构无效: {e}")

    req = AutoEditExportJianyingDraftRequest(
        plan=plan,
        project_name=args.get("project_name") or plan.title or "jianying_export",
        include_subtitle=bool(args.get("include_subtitle", True)),
        force_tts_pipeline=bool(
            args.get("force_tts_pipeline", plan.mode == "voiceover")
        ),
    )
    try:
        res = await export_jianying_draft_from_plan(req, _AgentRequestShim())  # type: ignore[arg-type]
    except Exception as e:
        return ToolResult(ok=False, summary="", error=str(e))

    export_entry = {
        "plan_id": plan_id,
        "filename": res.filename,
        "url": res.url,
        "local_path": getattr(res, "local_path", "") or "",
        "mode": getattr(res, "mode", "zip"),
        "kind": "jianying",
    }
    last_exports = list(ctx.workspace.last_exports or [])
    last_exports.append(export_entry)

    hint = (
        f"剪映草稿已导出：{res.filename}"
        + (f"（已写入 {export_entry['local_path']}）" if export_entry.get("local_path") else "，请下载 ZIP 后导入剪映")
    )

    return ToolResult(
        ok=True,
        summary=hint,
        workspace_patch={"pipeline_phase": "export", "last_exports": last_exports},
        artifact=ArtifactRef(type="export", id=res.filename, payload=export_entry),
    )


def register_auto_edit_tools() -> None:
    register(
        ToolSpec(
            name="generate_auto_edit_plan",
            description="根据选中视频与用户诉求生成自动剪辑方案（Plan）",
            parameters={
                "type": "object",
                "properties": {
                    "video_ids": {"type": "array", "items": {"type": "string"}},
                    "user_prompt": {"type": "string", "description": "剪辑诉求，如风格、时长、口播类型"},
                    "target_duration_sec": {"type": "integer"},
                    "num_plans": {"type": "integer", "description": "候选方案数，默认1"},
                    "mode": {"type": "string", "enum": ["auto", "voiceover", "original"]},
                },
                "required": ["user_prompt"],
            },
            risk="L1",
            handler=_generate_plan,
        )
    )
    register(
        ToolSpec(
            name="apply_plan_patch",
            description="对已有 Plan 应用 JSON patch（如改字幕、segments）",
            parameters={
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"},
                    "patch": {"type": "object", "description": "要合并到 plan 顶层的字段"},
                },
                "required": ["patch"],
            },
            risk="L1",
            handler=_apply_plan_patch,
        )
    )
    register(
        ToolSpec(
            name="realize_plan",
            description="将 Plan 渲染为成片视频（TTS/字幕/混音，耗时较长）",
            parameters={
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"},
                    "project_name": {"type": "string"},
                    "include_subtitle": {"type": "boolean"},
                },
            },
            risk="L2",
            handler=_realize_plan,
        )
    )
    register(
        ToolSpec(
            name="export_jianying_draft",
            description="将当前 Plan 导出为剪映草稿（ZIP 下载或直写剪映目录，取决于设置）",
            parameters={
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string"},
                    "project_name": {"type": "string"},
                    "include_subtitle": {"type": "boolean"},
                    "force_tts_pipeline": {
                        "type": "boolean",
                        "description": "口播方案建议 true",
                    },
                },
            },
            risk="L2",
            handler=_export_jianying,
        )
    )
