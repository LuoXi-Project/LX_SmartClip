"""Agent MediaConfig Tool：字幕样式 / BGM（与 Inspector 共用 workspace.media_config）。"""
from __future__ import annotations

from typing import Any

from app.agent.tool_registry import AgentContext, ToolSpec, register
from app.models.agent import ToolResult


def _read_media(ctx: AgentContext) -> dict[str, Any]:
    prefs = ctx.workspace.user_preferences or {}
    raw = prefs.get("media_config")
    return raw if isinstance(raw, dict) else {}


def _patch_media(ctx: AgentContext, patch: dict[str, Any]) -> dict[str, Any]:
    cur = _read_media(ctx)
    merged = {**cur}
    for key in ("subtitle", "bgm"):
        if key in patch and isinstance(patch[key], dict):
            merged[key] = {**(cur.get(key) or {}), **patch[key]}
    if "subtitle" in patch and isinstance(patch.get("subtitle"), dict):
        st = patch["subtitle"].get("style")
        if isinstance(st, dict):
            merged.setdefault("subtitle", {})
            merged["subtitle"]["style"] = {
                **((cur.get("subtitle") or {}).get("style") or {}),
                **st,
            }
    prefs = dict(ctx.workspace.user_preferences or {})
    prefs["media_config"] = merged
    return {"user_preferences": prefs}


async def _get_media_config(ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    m = _read_media(ctx)
    sub = m.get("subtitle") or {}
    bgm = m.get("bgm") or {}
    summary = (
        f"字幕={'开' if sub.get('enabled', True) else '关'}"
        f"{'(锁定)' if sub.get('locked') else ''} · "
        f"BGM={'开' if bgm.get('enabled') else '关'}"
        f" mode={bgm.get('mode', 'auto')}"
        f"{'(锁定)' if bgm.get('locked') else ''}"
    )
    return ToolResult(ok=True, summary=summary or "尚未配置 media_config，使用默认")


async def _apply_media_config_patch(ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    patch = args.get("patch")
    if not isinstance(patch, dict):
        return ToolResult(ok=False, summary="", error="patch 必须为对象")
    cur = _read_media(ctx)
    sub = cur.get("subtitle") or {}
    bgm = cur.get("bgm") or {}
    if sub.get("locked") and patch.get("subtitle"):
        psub = dict(patch["subtitle"])
        psub.pop("style", None)
        patch = {**patch, "subtitle": psub}
    if bgm.get("locked") and patch.get("bgm"):
        pbgm = dict(patch["bgm"])
        for k in ("track_ids", "mode", "enabled"):
            pbgm.pop(k, None)
        patch = {**patch, "bgm": pbgm}
    return ToolResult(
        ok=True,
        summary="已更新字幕/BGM 配置（未锁定字段）",
        workspace_patch=_patch_media(ctx, patch),
    )


async def _configure_bgm(ctx: AgentContext, args: dict[str, Any]) -> ToolResult:
    bgm = _read_media(ctx).get("bgm") or {}
    if bgm.get("locked"):
        return ToolResult(ok=False, summary="", error="BGM 已由用户锁定，无法通过 Agent 修改")
    enabled = args.get("enabled")
    mode = args.get("mode")
    track_id = (args.get("track_id") or "").strip()
    volume_db = args.get("volume_db")
    patch_bgm: dict[str, Any] = {}
    if enabled is not None:
        patch_bgm["enabled"] = bool(enabled)
        if not enabled:
            patch_bgm["mode"] = "none"
    if mode in ("auto", "manual", "none"):
        patch_bgm["mode"] = mode
        if mode == "none":
            patch_bgm["enabled"] = False
    if track_id:
        patch_bgm["track_ids"] = [track_id]
        patch_bgm["mode"] = "manual"
        patch_bgm["enabled"] = True
    if volume_db is not None:
        patch_bgm["volume_db"] = float(volume_db)
    if not patch_bgm:
        return ToolResult(ok=False, summary="", error="缺少 BGM 参数")
    return ToolResult(
        ok=True,
        summary=f"BGM 已配置: enabled={patch_bgm.get('enabled')} mode={patch_bgm.get('mode')}",
        workspace_patch=_patch_media(ctx, {"bgm": patch_bgm}),
    )


def register_media_tools() -> None:
    register(
        ToolSpec(
            name="get_media_config",
            description="读取当前字幕/BGM 媒体配置摘要",
            parameters={"type": "object", "properties": {}},
            risk="L0",
            handler=_get_media_config,
        )
    )
    register(
        ToolSpec(
            name="apply_media_config_patch",
            description="更新 workspace 字幕样式或 BGM（尊重用户锁定）",
            parameters={
                "type": "object",
                "properties": {"patch": {"type": "object"}},
                "required": ["patch"],
            },
            risk="L1",
            handler=_apply_media_config_patch,
        )
    )
    register(
        ToolSpec(
            name="configure_bgm",
            description="启用/关闭 BGM、自动或手动指定曲目",
            parameters={
                "type": "object",
                "properties": {
                    "enabled": {"type": "boolean"},
                    "mode": {"type": "string", "enum": ["auto", "manual", "none"]},
                    "track_id": {"type": "string"},
                    "volume_db": {"type": "number"},
                },
            },
            risk="L1",
            handler=_configure_bgm,
        )
    )
