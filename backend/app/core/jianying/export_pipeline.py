"""
剪映草稿导出管线：与 FFmpeg 成片解耦，仅负责素材时间轴 + ZIP。

供 subtitle HTTP、`auto_edit` 方案导出等入口复用。
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Dict, List, Literal

import aiosqlite
from fastapi import HTTPException

from app.core.blocking_pool import run_heavy
from app.core.jianying.draft_export import build_jianying_draft_zip
from app.db.database import DB_PATH
from app.models.subtitle import JianYingDraftExportResponse
from app.utils.paths import ensure_storage_subpath, normalize_jianying_parent_dir, storage_public_url_for_file

logger = logging.getLogger(__name__)

# 与 app.api.subtitle._load_render_opts / _load_export_render_opts 键表一致（用于剪映草稿按成片参数压制）
_JY_CLIP_RENDER_KEYS = (
    "clip_vcodec",
    "clip_acodec",
    "clip_preset",
    "clip_crf",
    "clip_video_bitrate_kbps",
    "clip_audio_bitrate_kbps",
    "clip_g",
    "clip_keyint_min",
    "clip_sc_threshold",
    "clip_fps",
    "clip_scale_width",
    "clip_scale_height",
    "clip_pix_fmt",
    "clip_container",
)
_JY_EXPORT_RENDER_KEYS = (
    "export_vcodec",
    "export_acodec",
    "export_preset",
    "export_crf",
    "export_video_bitrate_kbps",
    "export_audio_bitrate_kbps",
    "export_g",
    "export_keyint_min",
    "export_sc_threshold",
    "export_fps",
    "export_scale_width",
    "export_scale_height",
    "export_pix_fmt",
    "export_container",
    "export_gpu",
)


async def _get_jianying_draft_parent_dir() -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT value FROM config WHERE key = ?", ("jianying_draft_parent_dir",))
        row = await cur.fetchone()
        if not row or row["value"] is None:
            return ""
        return normalize_jianying_parent_dir(str(row["value"]))


async def load_jianying_export_segment_opts() -> Dict[str, str]:
    """
    读取 DB 中与成片导出一致的 clip_* 形编码参数（含 export→clip 合并）。

    剪映草稿导出已不再使用本结果；保留函数供其它需要「成片同款 merged opts」的逻辑复用。
    """
    from app.core.subtitle.render_opts import (
        export_resolution_fully_unspecified,
        final_render_opts_from_export,
        sanitize_no_stream_copy,
    )

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async def _gv(key: str) -> str:
            cur = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
            row = await cur.fetchone()
            return row["value"] if row and row["value"] is not None else ""

        clip_opts = {k: await _gv(k) for k in _JY_CLIP_RENDER_KEYS}
        export_opts = {k: await _gv(k) for k in _JY_EXPORT_RENDER_KEYS}

    merged = final_render_opts_from_export(export_opts, clip_opts)
    # 成片 export_scale 全未指定时，不得沿用 clip_scale（切片预览），否则与「原视频宽高」语义冲突。
    if export_resolution_fully_unspecified(export_opts):
        merged["clip_scale_width"] = "0"
        merged["clip_scale_height"] = "0"

    return sanitize_no_stream_copy(merged)


def _collect_clip_ids_from_segments(segments: List) -> List[str]:
    ids: List[str] = []
    for seg in segments:
        if getattr(seg, "clip_id", None):
            ids.append(str(seg.clip_id))
        clip_ids = getattr(seg, "clip_ids", None) or []
        ids.extend([str(cid) for cid in clip_ids if cid])
    return list(dict.fromkeys(ids))


def _rows_to_clip_map(rows: list) -> Dict[str, dict]:
    from app.utils.paths import resolve_stored_path

    clip_map: Dict[str, dict] = {}
    for r in rows:
        vfp = (r.get("video_file_path") or "").strip()
        clip_map[str(r["id"])] = {
            "path": resolve_stored_path(str(r.get("clip_path") or "")),
            "dur": float(r.get("duration") or 5),
            "src_video_path": resolve_stored_path(vfp) if vfp else "",
            "src_start": float(r.get("start_time") or 0.0),
            "src_end": float(r.get("end_time") or 0.0),
        }
    return clip_map


async def _load_clip_map_for_segments(segments: List) -> Dict[str, dict]:
    from app.api.subtitle import _load_clip_rows_with_raw_fallback

    ids = _collect_clip_ids_from_segments(segments)
    if not ids:
        raise HTTPException(400, "segments 缺少 clip_id/clip_ids")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await _load_clip_rows_with_raw_fallback(db, ids)

    if not rows:
        raise HTTPException(400, "未找到片段数据，请检查 clip_id 是否有效")
    return _rows_to_clip_map(rows)


def _prepare_srt_entries_tts(
    *,
    segments: List,
    clip_dur: Dict[str, float],
    style,
    client_srt_raw: str,
    strict_use_client_srt: bool,
    tts_audio_dir: str,
) -> list:
    """与 execute_burn_subtitle 中字幕时间轴逻辑对齐。"""
    from app.core.subtitle.srt import build_srt, parse_srt
    from app.core.subtitle.timeline import (
        resolve_durations,
        rule_timeline_weighted_chars,
        sanitize_subtitle_entries,
        srt_entries_exceed_max_chars,
    )

    srt_entries = parse_srt((client_srt_raw or "").strip())
    # 与 execute_burn_subtitle 一致：清理前端传入 SRT 的纯标点条/头尾悬挂标点
    srt_entries = sanitize_subtitle_entries(srt_entries)
    subtitle_enabled = bool((client_srt_raw or "").strip())
    try:
        if strict_use_client_srt:
            raise RuntimeError("strict_use_client_srt")
        if not subtitle_enabled:
            raise RuntimeError("no srt")

        tts_durs, _src = resolve_durations(segments, clip_dur, tts_audio_dir, use_tts=True)
        expected_total = float(sum(float(x or 0.0) for x in tts_durs) or 0.0)

        def _needs_rebuild(entries: list, *, expected_total_sec: float) -> bool:
            if expected_total_sec <= 0.1:
                return False
            if not entries:
                return True
            last_end = 0.0
            for e in entries:
                try:
                    st = float(e.get("start", 0.0) or 0.0)
                    ed = float(e.get("end", 0.0) or 0.0)
                except Exception:
                    return True
                if st < -0.001 or ed <= st:
                    return True
                if st + 0.001 < last_end:
                    return True
                last_end = max(last_end, ed)
            srt_total = float(max((e.get("end", 0.0) for e in entries), default=0.0) or 0.0)
            if abs(expected_total_sec - srt_total) > 0.15:
                return True
            if srt_total + 0.10 < expected_total_sec:
                return True
            if srt_total - expected_total_sec > 0.20:
                return True
            return False

        max_chars = style.max_chars_per_line if style else 20
        if _needs_rebuild(srt_entries, expected_total_sec=expected_total) or srt_entries_exceed_max_chars(
            srt_entries, max_chars
        ):
            rebuilt_entries = rule_timeline_weighted_chars(segments, tts_durs, max_chars)
            rebuilt_srt = build_srt(
                [{"start": e["start"], "end": e["end"], "text": e["text"]} for e in rebuilt_entries]
            )
            srt_entries = parse_srt(rebuilt_srt)
    except Exception:
        pass
    return srt_entries


def _segments_without_tts(segments: List):
    """原声草稿：忽略 tts_filename（与 export_original 一致）。"""
    from app.models.subtitle import SubtitleSegmentInput

    out: List[SubtitleSegmentInput] = []
    for seg in segments:
        out.append(
            SubtitleSegmentInput(
                copy_text=seg.copy_text,
                clip_id=seg.clip_id,
                clip_ids=seg.clip_ids,
                duration_sec=getattr(seg, "duration_sec", None),
                clip_start_sec=getattr(seg, "clip_start_sec", None),
                clip_trims=getattr(seg, "clip_trims", None),
                tts_filename=None,
            )
        )
    return out


def _prepare_srt_entries_original(
    *,
    segments_no_tts: List,
    clip_map: Dict[str, dict],
    include_subtitle: bool,
    style,
) -> list:
    from app.core.subtitle.timeline import rule_timeline_equal_units

    clip_dur = {cid: float(info.get("dur") or 5) for cid, info in clip_map.items()}
    seg_durs: List[float] = []
    for seg in segments_no_tts:
        manual_dur = getattr(seg, "duration_sec", None)
        try:
            manual_dur_v = float(manual_dur) if manual_dur is not None else None
        except Exception:
            manual_dur_v = None
        if manual_dur_v is not None and manual_dur_v > 0:
            seg_durs.append(manual_dur_v)
            continue
        raw_ids = list(getattr(seg, "clip_ids", None) or [])
        if not raw_ids and getattr(seg, "clip_id", None):
            raw_ids = [seg.clip_id]
        group_ids = list(dict.fromkeys([cid for cid in raw_ids if cid]))
        trims = getattr(seg, "clip_trims", None)
        if trims and group_ids:
            by_cid: dict[str, float] = {}
            for t in trims:
                try:
                    by_cid[str(t.clip_id)] = float(t.duration_sec)
                except Exception:
                    continue
            total_tr = 0.0
            for cid in group_ids:
                total_tr += float(by_cid.get(cid, clip_dur.get(cid, 5.0)))
            if total_tr > 0:
                seg_durs.append(total_tr)
                continue
        total = sum(clip_dur.get(cid, 5.0) for cid in group_ids)
        if total <= 0:
            total = 5.0
        seg_durs.append(total)

    max_chars = style.max_chars_per_line if style else 20
    return rule_timeline_equal_units(segments_no_tts, seg_durs, max_chars=max_chars) if include_subtitle else []


async def export_jianying_draft_zip_async(
    *,
    segments: List,
    mode: Literal["tts", "original"],
    project_name_base: str,
    tts_audio_dir: str,
    style,
    # tts
    client_srt_content: str = "",
    strict_use_client_srt: bool = False,
    # original
    include_subtitle: bool = True,
) -> JianYingDraftExportResponse:
    """
    生成剪映草稿：配置本地父目录时直接写入该目录，否则生成 ZIP 并提供下载 URL。

    :param segments: SubtitleSegmentInput 列表；original 模式内部会清除 tts_filename。
    """
    if not segments:
        raise HTTPException(400, "segments不能为空")

    clip_map = await _load_clip_map_for_segments(segments)
    clip_dur = {cid: float(info.get("dur") or 5.0) for cid, info in clip_map.items()}

    if mode == "tts":
        segs_for_draft = segments
        srt_entries = _prepare_srt_entries_tts(
            segments=segments,
            clip_dur=clip_dur,
            style=style,
            client_srt_raw=client_srt_content or "",
            strict_use_client_srt=strict_use_client_srt,
            tts_audio_dir=tts_audio_dir,
        )
    else:
        segs_for_draft = _segments_without_tts(segments)
        srt_entries = _prepare_srt_entries_original(
            segments_no_tts=segs_for_draft,
            clip_map=clip_map,
            include_subtitle=include_subtitle,
            style=style,
        )

    unique_project_name = f"{project_name_base}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    jy_dir = ensure_storage_subpath("jianying_drafts")
    jy_zip = os.path.join(jy_dir, f"{unique_project_name}_jianying.zip")

    jy_parent = await _get_jianying_draft_parent_dir()

    out_path, out_mode = await run_heavy(
        build_jianying_draft_zip,
        segments=segs_for_draft,
        clip_map=clip_map,
        mode=mode,
        srt_entries=srt_entries,
        tts_audio_dir=tts_audio_dir,
        project_name=unique_project_name,
        output_zip_path=jy_zip,
        jianying_draft_parent_dir=jy_parent or None,
        subtitle_style=style,
    )

    if out_mode == "direct":
        return JianYingDraftExportResponse(
            mode="direct",
            filename="",
            url="",
            local_path=out_path,
        )
    return JianYingDraftExportResponse(
        mode="zip",
        filename=os.path.basename(out_path),
        url=storage_public_url_for_file(out_path),
        local_path="",
    )
