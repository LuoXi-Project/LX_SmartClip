"""成片后处理管线入口。"""
from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

from app.core.postprod.audio_master import apply_audio_master
from app.core.postprod.profile import resolve_production_profile
from app.models.auto_edit import Plan
from app.models.production import ProductionProfile

logger = logging.getLogger(__name__)


def _resolve_video_path(filename: str, url: str) -> Optional[str]:
    from app.utils.paths import ensure_storage_subpath, resolve_burned_videos_dir_from_public_url

    if (url or "").strip():
        burn_dir = resolve_burned_videos_dir_from_public_url(url)
    else:
        burn_dir = ensure_storage_subpath("burned_videos")
    path = os.path.join(burn_dir, filename)
    return path if os.path.isfile(path) else None


def apply_postprod_master_if_needed(
    *,
    plan: Plan,
    filename: str,
    url: str,
    production_profile: Optional[ProductionProfile] = None,
    workspace_prefs: Optional[dict] = None,
) -> Tuple[str, str]:
    """
    BGM 混音前做人声母带（loudnorm）。
    返回 (filename, url)。
    """
    profile = resolve_production_profile(
        explicit=production_profile,
        plan=plan,
        workspace_prefs=workspace_prefs,
    )
    if profile.audio.loudnorm == "off" and not profile.audio.limiter:
        return filename, url

    src = _resolve_video_path(filename, url)
    if not src:
        return filename, url

    try:
        out = apply_audio_master(src, profile.audio)
    except Exception as e:
        logger.error("postprod master 失败: %s", e)
        return filename, url

    if out == src:
        return filename, url

    from app.utils.paths import storage_public_url_for_file

    new_name = os.path.basename(out)
    return new_name, storage_public_url_for_file(out)


def snapshot_production_on_plan(plan: Plan, profile: ProductionProfile) -> Plan:
    """realize 时把生效的 Profile 快照到 Plan，便于复现与分享。"""
    data = plan.model_dump()
    data["production_profile"] = profile.model_dump()
    return Plan.model_validate(data)
