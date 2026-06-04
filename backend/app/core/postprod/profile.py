"""Production Profile 解析：Workspace → Plan → Request 优先级合并。"""
from __future__ import annotations

from typing import Any, Optional

from app.core.postprod.presets import get_preset
from app.models.auto_edit import Plan
from app.models.production import ProductionProfile, ProductionProfilePatch


def _profile_from_dict(raw: Any) -> Optional[ProductionProfile]:
    if not raw or not isinstance(raw, dict):
        return None
    try:
        return ProductionProfile.model_validate(raw)
    except Exception:
        return None


def infer_preset_from_plan(plan: Optional[Plan]) -> str:
    if not plan:
        return "auto"
    mode = (plan.mode or "auto").lower()
    summary = f"{plan.title or ''} {plan.summary or ''}".lower()
    if any(k in summary for k in ("电商", "带货", "爆款", "种草")):
        return "ecommerce"
    if any(k in summary for k in ("知识", "科普", "教程", "讲解")):
        return "knowledge"
    if any(k in summary for k in ("纪录片", "电影", "叙事", "文艺")):
        return "cinematic"
    if any(k in summary for k in ("卡点", "快剪", "混剪", "节奏")):
        return "fast_cut"
    if mode == "voiceover":
        return "ecommerce"
    return "auto"


def resolve_production_profile(
    *,
    explicit: Optional[ProductionProfile] = None,
    plan: Optional[Plan] = None,
    workspace_prefs: Optional[dict[str, Any]] = None,
) -> ProductionProfile:
    """
    优先级：explicit > plan.production_profile > workspace.production_profile
            > workspace.default_production_preset > plan 推断 auto preset
    """
    prefs = workspace_prefs or {}
    preset_key = str(prefs.get("default_production_preset") or "auto")
    ws_raw = prefs.get("production_profile")
    ws_profile = _profile_from_dict(ws_raw)

    if ws_profile and ws_profile.preset_id != "custom":
        base = get_preset(ws_profile.preset_id)
    elif ws_profile and ws_profile.preset_id == "custom":
        base = get_preset("auto").merge(ws_profile)
    else:
        base = get_preset(preset_key)

    if ws_profile:
        base = base.merge(ws_profile)

    if plan is not None:
        plan_raw = getattr(plan, "production_profile", None)
        plan_profile = (
            plan_raw
            if isinstance(plan_raw, ProductionProfile)
            else _profile_from_dict(plan_raw)
        )
        if plan_profile:
            if plan_profile.preset_id != "custom" and plan_profile.preset_id != base.preset_id:
                base = get_preset(plan_profile.preset_id).merge(base)
            base = base.merge(plan_profile)

        if base.preset_id == "auto":
            inferred = infer_preset_from_plan(plan)
            base = get_preset(inferred).merge(base)
            base.preset_id = inferred

    if explicit:
        if explicit.preset_id not in ("auto", "custom"):
            base = get_preset(explicit.preset_id).merge(base)
        base = base.merge(explicit)
        if explicit.preset_id == "custom":
            base.preset_id = "custom"

    return base


def apply_profile_patch(
    current: ProductionProfile,
    patch: ProductionProfilePatch | ProductionProfile,
    *,
    respect_locks: bool = True,
) -> ProductionProfile:
    if isinstance(patch, ProductionProfilePatch):
        delta = patch.to_profile()
    else:
        delta = patch
    if delta.preset_id not in ("auto", "custom"):
        base = get_preset(delta.preset_id).merge(current, respect_locks=respect_locks)
        return base.merge(delta, respect_locks=respect_locks)
    return current.merge(delta, respect_locks=respect_locks)


def style_with_production(style, profile: ProductionProfile):
    """将字幕动效写入 SubtitleStyle。"""
    from app.models.subtitle import SubtitleStyle

    base = style if style is not None else SubtitleStyle()
    motion = profile.subtitle_motion
    return base.model_copy(
        update={
            "motion_template": motion.template,
            "motion_fade_ms": motion.fade_ms,
        }
    )
