from __future__ import annotations

_tools_registered = False


def register_all_tools() -> None:
    global _tools_registered
    if _tools_registered:
        return
    from app.agent.tools.videos import register_video_tools
    from app.agent.tools.workspace_tools import register_workspace_tools
    from app.agent.tools.process_tool import register_process_tools
    from app.agent.tools.auto_edit_tools import register_auto_edit_tools
    from app.agent.tools.select_videos import register_select_video_tools

    register_video_tools()
    register_workspace_tools()
    register_select_video_tools()
    register_process_tools()
    register_auto_edit_tools()
    _tools_registered = True
