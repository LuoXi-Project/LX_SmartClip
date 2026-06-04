"""将 workspace media_config 合并进 Plan / Realize 请求。"""
from __future__ import annotations

from typing import Any, Optional

from app.models.auto_edit import BGMPlan, Plan
from app.models.subtitle import SubtitleStyle


def merge_bgm_from_media(plan: Plan, media: Optional[dict[str, Any]]) -> Plan:
    if not media:
        return plan
    bgm_cfg = media.get("bgm") or {}
    if not bgm_cfg.get("enabled") or bgm_cfg.get("mode") == "none":
        if plan.bgm:
            return plan.model_copy(update={"bgm": plan.bgm.model_copy(update={"enabled": False})})
        return plan

    pb = plan.bgm
    vol = float(bgm_cfg.get("volume_db") if bgm_cfg.get("volume_db") is not None else (pb.volume_db if pb else -12))

    track_ids = bgm_cfg.get("track_ids") or []
    if bgm_cfg.get("mode") == "manual" and track_ids:
        tid = str(track_ids[0])
        return plan.model_copy(
            update={
                "bgm": BGMPlan(
                    enabled=True,
                    source="user",
                    track_id=tid,
                    track_ids=[str(x) for x in track_ids],
                    volume_db=vol,
                    loop=pb.loop if pb else True,
                    fade_in_sec=pb.fade_in_sec if pb else 0.8,
                    fade_out_sec=pb.fade_out_sec if pb else 1.0,
                )
            }
        )

    return plan.model_copy(
        update={
            "bgm": BGMPlan(
                enabled=True,
                source=pb.source if pb else "library",
                track_id=pb.track_id if pb else None,
                track_ids=pb.track_ids if pb and pb.track_ids else None,
                volume_db=vol,
                loop=pb.loop if pb else True,
                fade_in_sec=pb.fade_in_sec if pb else 0.8,
                fade_out_sec=pb.fade_out_sec if pb else 1.0,
            )
        }
    )


def subtitle_style_from_media(media: Optional[dict[str, Any]]) -> Optional[SubtitleStyle]:
    if not media:
        return None
    sub = media.get("subtitle") or {}
    raw = sub.get("style")
    if not isinstance(raw, dict):
        return None
    try:
        return SubtitleStyle.model_validate(raw)
    except Exception:
        return None


def include_subtitle_from_media(media: Optional[dict[str, Any]], default: bool = True) -> bool:
    if not media:
        return default
    sub = media.get("subtitle") or {}
    if "enabled" in sub:
        return bool(sub.get("enabled"))
    return default
