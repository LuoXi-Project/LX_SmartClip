"""Agent 制作风格 Tool：preset / 意图 / patch。"""
from __future__ import annotations

from typing import Any

from app.agent.tool_registry import AgentContext, ToolSpec, register
from app.core.postprod.intent import intent_summary, parse_production_intent
from app.core.postprod.presets import get_preset, list_preset_ids
from app.core.postprod.profile import apply_profile_patch, resolve_production_profile
from app.models.agent import ToolResult
from app.models.production import ProductionProfile, ProductionProfilePatch


def _prefs_production(ctx: AgentContext) -> ProductionProfile:
    prefs = ctx.workspace.user_preferences or {}
    return resolve_production_profile(workspace_prefs=prefs)


def _patch_workspace_profile(ctx: AgentContext, profile: ProductionProfile) -> dict[str, Any]:
    prefs = dict(ctx.workspace.user_preferences or {})
    prefs["production_profile"] = profile.model_dump()
    prefs["default_production_preset"] = profile.preset_id
    return {"user_preferences": prefs}


async def _set_production_preset(ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    preset_id = str(args.get("preset_id") or "auto").strip().lower()
    if preset_id not in list_preset_ids() and preset_id != "custom":
        return ToolResult(ok=False, summary="", error=f"未知 preset: {preset_id}")
    current = _prefs_production(ctx)
    base = get_preset(preset_id).merge(current, respect_locks=True)
    base.preset_id = preset_id  # type: ignore[assignment]
    return ToolResult(
        ok=True,
        summary=f"制作风格已设为「{preset_id}」：{base.human_summary()}",
        workspace_patch=_patch_workspace_profile(ctx, base),
        next_suggestions=["可说「按当前风格生成方案」或「直接成片」"],
    )


async def _apply_production_patch(ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    patch_raw = args.get("patch")
    if not isinstance(patch_raw, dict):
        return ToolResult(ok=False, summary="", error="patch 必须为对象")
    try:
        patch = ProductionProfilePatch.model_validate(patch_raw)
    except Exception as e:
        return ToolResult(ok=False, summary="", error=f"patch 无效: {e}")
    current = _prefs_production(ctx)
    merged = apply_profile_patch(current, patch, respect_locks=True)
    if patch.preset_id and patch.preset_id not in ("auto", "custom"):
        merged = get_preset(patch.preset_id).merge(merged, respect_locks=True)
        merged.preset_id = patch.preset_id  # type: ignore[assignment]
    return ToolResult(
        ok=True,
        summary=f"制作参数已更新：{merged.human_summary()}",
        workspace_patch=_patch_workspace_profile(ctx, merged),
    )


async def _resolve_production_intent(ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    text = (args.get("intent") or args.get("user_prompt") or "").strip()
    if not text:
        return ToolResult(ok=False, summary="", error="缺少 intent（自然语言制作诉求）")
    patch = parse_production_intent(text)
    current = _prefs_production(ctx)
    merged = apply_profile_patch(current, patch, respect_locks=True)
    if patch.preset_id and patch.preset_id not in ("auto", "custom"):
        merged = get_preset(patch.preset_id).merge(merged, respect_locks=True)
        merged.preset_id = patch.preset_id  # type: ignore[assignment]
    hint = intent_summary(text)
    return ToolResult(
        ok=True,
        summary=f"已理解制作意图（{hint}）→ {merged.human_summary()}",
        workspace_patch=_patch_workspace_profile(ctx, merged),
        next_suggestions=["确认后可 generate_auto_edit_plan / realize_plan"],
    )


async def _get_production_profile(ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    profile = _prefs_production(ctx)
    if args.get("plan_id"):
        pid = str(args["plan_id"])
        raw = next((p for p in ctx.workspace.plans if str(p.get("plan_id")) == pid), None)
        if raw and raw.get("production_profile"):
            try:
                profile = resolve_production_profile(
                    explicit=ProductionProfile.model_validate(raw["production_profile"]),
                    workspace_prefs=ctx.workspace.user_preferences or {},
                )
            except Exception:
                pass
    return ToolResult(ok=True, summary=profile.human_summary())


def register_production_tools() -> None:
    register(
        ToolSpec(
            name="set_production_preset",
            description="设置成片制作风格预设（转场/响度/ducking/字幕动效），无需手动填参数",
            parameters={
                "type": "object",
                "properties": {
                    "preset_id": {
                        "type": "string",
                        "enum": ["auto", "ecommerce", "knowledge", "cinematic", "fast_cut"],
                    }
                },
                "required": ["preset_id"],
            },
            risk="L1",
            handler=_set_production_preset,
        )
    )
    register(
        ToolSpec(
            name="apply_production_patch",
            description="结构化微调制作参数（transition/audio/bgm/subtitle_motion）",
            parameters={
                "type": "object",
                "properties": {"patch": {"type": "object"}},
                "required": ["patch"],
            },
            risk="L1",
            handler=_apply_production_patch,
        )
    )
    register(
        ToolSpec(
            name="resolve_production_intent",
            description="从自然语言解析制作诉求并写入 workspace（如：转场柔一点、BGM别抢人声、电商风）",
            parameters={
                "type": "object",
                "properties": {"intent": {"type": "string"}},
                "required": ["intent"],
            },
            risk="L1",
            handler=_resolve_production_intent,
        )
    )
    register(
        ToolSpec(
            name="get_production_profile",
            description="读取当前制作风格摘要（人类可读）",
            parameters={
                "type": "object",
                "properties": {"plan_id": {"type": "string"}},
            },
            risk="L0",
            handler=_get_production_profile,
        )
    )
