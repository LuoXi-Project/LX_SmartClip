from __future__ import annotations

from app.models.agent import WorkspaceState


async def _video_status_lines(video_ids: list[str]) -> list[str]:
    if not video_ids:
        return []
    try:
        from app.agent.tools.videos import _get_video_status
        from app.agent.tool_registry import AgentContext

        ctx = AgentContext(session_id="", workspace=WorkspaceState(session_id=""))
        lines: list[str] = []
        for vid in video_ids[:6]:
            res = await _get_video_status(ctx, {"video_id": vid})
            if res.ok:
                lines.append(f"  · {res.summary}")
            else:
                lines.append(f"  · {vid}: 查询失败")
        if len(video_ids) > 6:
            lines.append(f"  · …共 {len(video_ids)} 个")
        return lines
    except Exception:
        return []


def _active_plan_summary(ws: WorkspaceState) -> str | None:
    if not ws.plans:
        return None
    pid = ws.active_plan_id or str(ws.plans[0].get("plan_id") or "")
    raw = next((p for p in ws.plans if str(p.get("plan_id")) == pid), ws.plans[0])
    mode = str(raw.get("mode") or "auto")
    title = str(raw.get("title") or pid)
    dur = raw.get("estimated_duration_sec") or raw.get("target_duration_sec") or "?"
    q = raw.get("quality") or {}
    grade = q.get("grade") if isinstance(q, dict) else None
    extra = f"，质量 {grade}" if grade else ""
    return f"「{title}」mode={mode}，约 {dur}s{extra}"


async def build_workspace_summary(ws: WorkspaceState) -> str:
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
        status_lines = await _video_status_lines(ws.selected_video_ids)
        if status_lines:
            lines.append("- 视频状态:")
            lines.extend(status_lines)
    lines.append(f"- 方案数: {len(ws.plans)}")
    plan_sum = _active_plan_summary(ws)
    if plan_sum:
        lines.append(f"- 当前方案: {plan_sum}")
    elif ws.active_plan_id:
        lines.append(f"- 当前方案 ID: {ws.active_plan_id}")
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
    if prefs.get("target_duration_sec"):
        lines.append(f"- 目标时长: {prefs['target_duration_sec']} 秒")
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
