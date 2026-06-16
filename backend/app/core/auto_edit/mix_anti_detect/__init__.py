"""混剪成片防检测管线入口。"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Optional, Tuple

from app.core.auto_edit.mix_anti_detect.pipeline import run_anti_detect_pipeline
from app.models.auto_edit import MixAntiDetectConfig, Plan

logger = logging.getLogger(__name__)


def _resolve_video_path(filename: str, url: str) -> Optional[str]:
    from app.utils.paths import ensure_storage_subpath, resolve_burned_videos_dir_from_public_url

    if (url or "").strip():
        burn_dir = resolve_burned_videos_dir_from_public_url(url)
    else:
        burn_dir = ensure_storage_subpath("burned_videos")
    path = os.path.join(burn_dir, filename)
    return path if os.path.isfile(path) else None


def apply_mix_anti_detect_if_needed(
    plan: Plan,
    filename: str,
    url: str,
) -> Tuple[str, str]:
    """
    若 plan.postprocess.anti_detect.enabled，对成片执行防检测管线并输出 MKV/MP4。
    返回 (filename, url)。
    """
    pp = getattr(plan, "postprocess", None)
    cfg: MixAntiDetectConfig | None = getattr(pp, "anti_detect", None) if pp else None
    if not cfg or not cfg.enabled:
        return filename, url

    src = _resolve_video_path(filename, url)
    if not src:
        logger.warning("防检测跳过：成片不存在 %s", filename)
        return filename, url

    job_id = uuid.uuid4().hex[:10]
    try:
        out_path, log_path = run_anti_detect_pipeline(src, cfg, job_id=job_id)
    except Exception as e:
        logger.error("混剪防检测失败，回退原成片 job=%s: %s", job_id, e)
        return filename, url

    from app.utils.paths import storage_public_url_for_file

    new_name = os.path.basename(out_path)
    logger.info(
        "混剪防检测完成 job=%s out=%s log=%s",
        job_id,
        new_name,
        log_path,
    )
    return new_name, storage_public_url_for_file(out_path)
