from __future__ import annotations

from app.models.agent import WorkspaceState


def build_workspace_summary(ws: WorkspaceState) -> str:
    lines = [
        f"- 会话: {ws.session_id}",
        f"- 标题: {ws.title}",
        f"- 阶段: {ws.pipeline_phase}",
        f"- 选中视频数: {len(ws.selected_video_ids)}",
    ]
    if ws.selected_video_ids:
        ids = ", ".join(ws.selected_video_ids[:8])
        if len(ws.selected_video_ids) > 8:
            ids += " …"
        lines.append(f"- 视频 ID: {ids}")
    lines.append(f"- 方案数: {len(ws.plans)}")
    if ws.active_plan_id:
        lines.append(f"- 当前方案: {ws.active_plan_id}")
    jobs = ws.jobs or {}
    pt = jobs.get("process_task_ids") or []
    if pt:
        lines.append(f"- 处理任务: {', '.join(str(x) for x in pt[-3:])}")
    if ws.last_exports:
        lines.append(f"- 最近导出: {len(ws.last_exports)} 个")
    prefs = ws.user_preferences or {}
    if prefs.get("last_user_prompt"):
        prompt = str(prefs["last_user_prompt"])[:120]
        lines.append(f"- 上次诉求: {prompt}")
    try:
        from app.core.postprod.profile import resolve_production_profile

        prof = resolve_production_profile(workspace_prefs=prefs)
        lines.append(f"- 制作风格: {prof.human_summary()}")
        media = prefs.get("media_config")
        if isinstance(media, dict):
            sub = media.get("subtitle") or {}
            bgm = media.get("bgm") or {}
            lines.append(
                f"- 媒体: 字幕={'开' if sub.get('enabled', True) else '关'}"
                f"{'🔒' if sub.get('locked') else ''} · "
                f"BGM={'开' if bgm.get('enabled') else '关'}"
                f"({bgm.get('mode', 'auto')})"
                f"{'🔒' if bgm.get('locked') else ''}"
            )
    except Exception:
        pass
    return "\n".join(lines)
