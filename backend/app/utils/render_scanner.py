"""成片文件系统扫描器（首次启动/手动触发时补录历史成片）。

覆盖 4 类成片目录（探索报告已确认）：
1. storage/<video_id>/burned_videos/*.mp4（单素材）
2. storage/cross_video_exports/burned_videos/*.mp4（跨素材混剪）
3. storage/stock_media/exports/*.mp4（文案素材）
4. storage/burned_videos/*.mp4（旧版扁平兜底）

幂等：对每个 .mp4 调 record_render_from_path（INSERT OR IGNORE）。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from app.api import renders_db
from app.utils.paths import get_storage_root

logger = logging.getLogger(__name__)


def _glob_mp4(directory: Path) -> list[Path]:
    """列出目录下所有 .mp4（不递归）。"""
    if not directory.is_dir():
        return []
    try:
        return sorted(
            [p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".mp4"],
            key=lambda p: p.stat().st_mtime if p.exists() else 0,
            reverse=True,
        )
    except OSError:
        return []


def _detect_source_and_material(rel_to_storage: str, filename: str) -> tuple[str, str | None]:
    """根据相对路径 + 文件名推断来源和素材 id。

    rel_to_storage 形如: <vid>/burned_videos/a.mp4 / cross_video_exports/burned_videos/a.mp4 / stock_media/exports/a.mp4
    """
    parts = rel_to_storage.replace("\\", "/").split("/")
    # 文案素材
    if "stock_media" in parts and "exports" in parts:
        return "script_stock_compose", None
    # 跨素材混剪
    if "cross_video_exports" in parts:
        return "realize", None
    # 单素材：第一段是 video_id
    if len(parts) >= 2 and parts[1] == "burned_videos":
        material_id = parts[0]
        # 文件名前缀细分
        if filename.startswith("film_"):
            return "film_commentary", material_id
        if filename.startswith("autoedit_"):
            return "realize", material_id
        return "burn", material_id
    # 旧版扁平
    if parts and parts[0] == "burned_videos":
        return "burn", None
    return "burn", None


async def scan_and_record(*, skip_existing: bool = True) -> dict:
    """扫描所有成片目录并入库。返回统计 {scanned, recorded, skipped, failed}。

    幂等：skip_existing=True 时，已入库的 file_path 跳过（不重复 probe_duration）。
    """
    storage = get_storage_root()
    stats = {"scanned": 0, "recorded": 0, "skipped": 0, "failed": 0}

    # 收集所有候选：[(abs_path, source, material_id), ...]
    candidates: list[tuple[str, str, str | None]] = []

    # 1. storage/<vid>/burned_videos/（遍历所有素材子目录）
    if storage.is_dir():
        for entry in storage.iterdir():
            if not entry.is_dir():
                continue
            bv = entry / "burned_videos"
            for mp4 in _glob_mp4(bv):
                rel = f"{entry.name}/burned_videos/{mp4.name}"
                source, mid = _detect_source_and_material(rel, mp4.name)
                candidates.append((str(mp4), source, mid))

    # 2. cross_video_exports/burned_videos/
    for mp4 in _glob_mp4(storage / "cross_video_exports" / "burned_videos"):
        rel = f"cross_video_exports/burned_videos/{mp4.name}"
        source, mid = _detect_source_and_material(rel, mp4.name)
        candidates.append((str(mp4), source, mid))

    # 3. stock_media/exports/
    for mp4 in _glob_mp4(storage / "stock_media" / "exports"):
        rel = f"stock_media/exports/{mp4.name}"
        source, mid = _detect_source_and_material(rel, mp4.name)
        candidates.append((str(mp4), source, mid))

    # 4. 旧版扁平 storage/burned_videos/
    for mp4 in _glob_mp4(storage / "burned_videos"):
        rel = f"burned_videos/{mp4.name}"
        source, mid = _detect_source_and_material(rel, mp4.name)
        candidates.append((str(mp4), source, mid))

    stats["scanned"] = len(candidates)
    logger.info("成片扫描: 发现 %d 个候选文件", len(candidates))

    for abs_path, source, material_id in candidates:
        try:
            if skip_existing:
                # 先查是否已入库，避免重复 probe
                from app.api.renders_db import _abs_to_storage_rel
                file_path = _abs_to_storage_rel(abs_path)
                if await renders_db.find_existing_by_path(file_path):
                    stats["skipped"] += 1
                    continue

            rid = await renders_db.record_render_from_path(
                abs_path=abs_path, source=source, material_id=material_id,
            )
            if rid:
                stats["recorded"] += 1
            else:
                stats["failed"] += 1
        except Exception as exc:
            logger.warning("扫描入库失败 %s: %s", abs_path, exc)
            stats["failed"] += 1

    logger.info("成片扫描完成: %s", stats)
    return stats
