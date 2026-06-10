"""auto_edit — 自动一键成片 · Plan 规划接口（聚合路由）。"""
from app.api.auto_edit_shared import router

# 注册各子模块路由（side-effect import）
import app.api.auto_edit_plan  # noqa: F401,E402
import app.api.auto_edit_variants  # noqa: F401,E402
import app.api.auto_edit_realize  # noqa: F401,E402

from app.api.auto_edit_plan import (
    create_auto_edit_plan_session,
    generate_auto_edit_plan,
    list_auto_edit_templates,
    stream_auto_edit_plan,
)
from app.api.auto_edit_realize import (
    _prepare_auto_edit_segments_from_plan,
    export_jianying_draft_from_plan,
    prepare_auto_edit_segments_from_plan,
    realize_auto_edit_plan,
)
from app.api.auto_edit_variants import (
    mix_edit_plan,
    mix_upload_asset,
    video_dub_plan,
    voiceover_quick_cut_plan,
)

__all__ = [
    "router",
    "generate_auto_edit_plan",
    "list_auto_edit_templates",
    "create_auto_edit_plan_session",
    "stream_auto_edit_plan",
    "voiceover_quick_cut_plan",
    "mix_edit_plan",
    "mix_upload_asset",
    "video_dub_plan",
    "realize_auto_edit_plan",
    "export_jianying_draft_from_plan",
    "prepare_auto_edit_segments_from_plan",
    "_prepare_auto_edit_segments_from_plan",
]
