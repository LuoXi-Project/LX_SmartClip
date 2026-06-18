"""subtitle.py — SRT字幕生成 & 烧录 路由层（薄封装，业务逻辑见 core/subtitle）"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import List
from urllib.parse import quote

import aiosqlite
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.models.subtitle import (
    BurnSubtitleRequest,
    BurnSubtitleResponse,
    ExportOriginalRequest,
    GenerateSRTRequest,
    GenerateSRTResponse,
    JianYingDraftExportRequest,
    JianYingDraftExportResponse,
    SRTEntry,
    SubtitleSegmentInput,
    SubtitleStyle,  # noqa: F401 - 用于模块级 re-export
)

from app.core.blocking_pool import run_heavy
from app.jobs import create_job, JobReporter, launch_job, update_job_status
from app.db.database import DB_PATH
from app.utils.ffprobe_utils import probe_duration
from app.utils.paths import ensure_storage_subpath, get_fonts_dir, get_storage_root, resolve_stored_path, storage_public_url_for_file
from app.core.subtitle.srt import build_srt, parse_srt
from app.core.subtitle.timeline import (
    resolve_durations,
    rule_timeline,
    rule_timeline_equal_units,
    rule_timeline_weighted_chars,
    srt_entries_exceed_max_chars,
)
from app.core.subtitle.burn import burn_to_mp4
from app.core.subtitle.tts_align import apply_timeline_duration_overrides
from app.core.jianying.export_pipeline import export_jianying_draft_zip_async
from app.core.bgm.auto_bgm import apply_bgm_config_postprocess

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/subtitle", tags=["subtitle"])

TTS_AUDIO_DIR = os.path.abspath(os.path.join(os.path.dirname(DB_PATH), "tts_audio"))

_FONTS_DIR = get_fonts_dir()

def _burned_output_dir_for_clip_rows(rows: list) -> str:
    """
    由 clips 行得到烧录/原声导出输出目录。
    - 单素材：``storage/<video_id>/burned_videos/``（与手动匹配一致）
    - 跨素材混剪：``storage/cross_video_exports/burned_videos/``
    """
    video_ids = {str(r["video_id"]) for r in rows if r.get("video_id")}
    if not video_ids:
        raise HTTPException(400, "segments 缺少有效的 video_id")
    if len(video_ids) == 1:
        material_id = next(iter(video_ids))
        return ensure_storage_subpath(material_id, "burned_videos")
    return ensure_storage_subpath("cross_video_exports", "burned_videos")


async def _load_clip_rows_with_raw_fallback(
    db: aiosqlite.Connection,
    ids: List[str],
) -> list[dict]:
    """
    读取 clip 元数据；兼容 raw_<video_id> 这种“未预处理视频”虚拟片段。
    返回字段与 clips join videos 查询一致：id/video_id/clip_path/duration/start_time/end_time/video_file_path。
    """
    if not ids:
        return []

    normal_ids = [cid for cid in ids if not str(cid).startswith("raw_")]
    raw_ids = [cid for cid in ids if str(cid).startswith("raw_")]

    out: list[dict] = []

    if normal_ids:
        async with db.execute(
            f"""
            SELECT c.id AS id, c.video_id AS video_id, c.clip_path AS clip_path, c.duration AS duration,
                   c.start_time AS start_time, c.end_time AS end_time, v.file_path AS video_file_path
            FROM clips c
            LEFT JOIN videos v ON v.id = c.video_id
            WHERE c.id IN ({','.join(['?'] * len(normal_ids))})
            """,
            normal_ids,
        ) as cur:
            rows = await cur.fetchall()
        for r in rows:
            out.append(
                {
                    "id": str(r["id"]),
                    "video_id": str(r["video_id"]),
                    "clip_path": str(r["clip_path"] or ""),
                    "duration": float(r["duration"] or 0.0),
                    "start_time": float(r["start_time"] or 0.0),
                    "end_time": float(r["end_time"] or 0.0),
                    "video_file_path": str(r["video_file_path"] or ""),
                }
            )

    if raw_ids:
        raw_video_ids = list(
            dict.fromkeys(
                [
                    rid[len("raw_") :]
                    for rid in raw_ids
                    if len(rid) > len("raw_") and rid[len("raw_") :]
                ]
            )
        )
        video_map: dict[str, dict] = {}
        if raw_video_ids:
            async with db.execute(
                f"SELECT id, file_path, duration FROM videos WHERE id IN ({','.join(['?'] * len(raw_video_ids))})",
                raw_video_ids,
            ) as cur:
                vrows = await cur.fetchall()
            for v in vrows:
                video_map[str(v["id"])] = {
                    "file_path": str(v["file_path"] or ""),
                    "duration": float(v["duration"] or 0.0),
                }

        for rid in raw_ids:
            vid = rid[len("raw_") :]
            v = video_map.get(vid)
            if not v:
                continue
            src_path = resolve_stored_path(v["file_path"])
            dur = float(v["duration"] or 0.0)
            if dur <= 0:
                dur = float(probe_duration(src_path, log_on_failure=True) or 0.0)
            out.append(
                {
                    "id": rid,
                    "video_id": vid,
                    # raw 片段直接指向原视频文件，后续按 clip_start_sec/duration_sec 裁剪
                    "clip_path": v["file_path"],
                    "duration": dur,
                    "start_time": 0.0,
                    "end_time": max(0.0, dur),
                    "video_file_path": v["file_path"],
                }
            )

    return out


async def _get_config_value(db, key: str, default: str) -> str:
    cur = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = await cur.fetchone()
    return row["value"] if row and row["value"] is not None else default


async def _load_render_opts(db) -> dict:
    """读取切片/预处理用 FFmpeg 参数（可含 copy，追求速度）。"""
    keys = [
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
    ]
    opts = {}
    for key in keys:
        opts[key] = await _get_config_value(db, key, "")
    return opts


async def _load_export_render_opts(db) -> dict:
    """读取成片导出专用参数（最终 concat+烧录；与切片分离）。"""
    keys = [
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
    ]
    opts = {}
    for key in keys:
        opts[key] = await _get_config_value(db, key, "")
    return opts


async def _load_export_backend(db) -> str:
    v = (await _get_config_value(db, "export_backend", "moviepy")) or "moviepy"
    v = v.strip().lower()
    return v if v in ("ffmpeg", "moviepy") else "moviepy"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
#
# 注：Pydantic 模型已拆到 `app.models.subtitle`，此处通过 import
# 进行模块级 re-export，避免破坏其它代码的导入路径。

# ---------------------------------------------------------------------------
# Route: 生成 SRT 时间轴
# ---------------------------------------------------------------------------

@router.post("/generate", response_model=GenerateSRTResponse)
async def generate_srt(req: GenerateSRTRequest):
    """生成SRT时间轴，按TTS音频时长严格切分并对齐。"""
    if not req.segments:
        raise HTTPException(400, "segments不能为空")

    ids: List[str] = []
    for seg in req.segments:
        if seg.clip_id:
            ids.append(seg.clip_id)
        if seg.clip_ids:
            ids.extend([cid for cid in seg.clip_ids if cid])
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise HTTPException(400, "segments 缺少 clip_id/clip_ids")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await _load_clip_rows_with_raw_fallback(db, ids)

    clip_dur = {str(r["id"]): float(r.get("duration") or 5.0) for r in rows}
    max_chars = req.style.max_chars_per_line if req.style else 20

    durs, src = resolve_durations(req.segments, clip_dur, TTS_AUDIO_DIR, req.use_tts_timing)

    # 一键成片默认走规则法，确保字幕与配音时长完全可控，避免 LLM 对齐偏差。
    # 启用 TTS timing 时：段内按字数权重分配时长，更贴近匀速配音。
    # True=按逗号/短句拆条；False=仅句号/换行（默认）
    fine_grain = bool(req.split_narration_by_sentence)
    if req.use_tts_timing:
        raw_entries = rule_timeline_weighted_chars(
            req.segments, durs, max_chars, fine_grain_split=fine_grain
        )
    else:
        raw_entries = rule_timeline(req.segments, durs, max_chars, fine_grain_split=fine_grain)

    logger.warning(f"raw_entries: {raw_entries}")

    out = [
        SRTEntry(
            index=i,
            start=float(e.get("start", 0)),
            end=float(e.get("end", 1)),
            text=str(e.get("text", "")),
            clip_id=str(e.get("clip_id", "")),
        )
        for i, e in enumerate(raw_entries, 1)
    ]
    srt = build_srt([{"start": e.start, "end": e.end, "text": e.text} for e in out])
    return GenerateSRTResponse(
        srt_content=srt,
        entries=out,
        total_duration=max((e.end for e in out), default=0.0),
        timing_source=src,
    )


# ---------------------------------------------------------------------------
# 烧录 / 原声导出 · 可执行体（供 HTTP 路由与 auto_edit 等内部调用）
# ---------------------------------------------------------------------------


async def execute_burn_subtitle(req: BurnSubtitleRequest) -> dict:
    """合并视频 + 替换 TTS 音轨 + 硬烧字幕；重 CPU/ffmpeg 走专用线程池。"""
    if not req.segments:
        raise HTTPException(400, "segments不能为空")

    ids: List[str] = []
    for seg in req.segments:
        if seg.clip_id:
            ids.append(seg.clip_id)
        if seg.clip_ids:
            ids.extend([cid for cid in seg.clip_ids if cid])
    ids = list(dict.fromkeys(ids))
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await _load_clip_rows_with_raw_fallback(db, ids)
        render_opts = await _load_render_opts(db)
        export_render_opts = await _load_export_render_opts(db)
        export_backend_cfg = await _load_export_backend(db)

    if not rows:
        raise HTTPException(400, "未找到片段数据，请检查 clip_id 是否有效")

    burn_output_dir = _burned_output_dir_for_clip_rows(list(rows))

    clip_map = {}
    for r in rows:
        vfp = (r.get("video_file_path") or "").strip()
        clip_map[str(r["id"])] = {
            "path": resolve_stored_path(str(r.get("clip_path") or "")),
            "dur": float(r.get("duration") or 5),
            "src_video_path": resolve_stored_path(vfp) if vfp else "",
            "src_start": float(r.get("start_time") or 0.0),
            "src_end": float(r.get("end_time") or 0.0),
        }
    clip_dur = {cid: float(info.get("dur") or 5.0) for cid, info in clip_map.items()}

    from app.core.subtitle.burn import prepare_tts_burn_segments

    burn_segments, burn_tts_align = prepare_tts_burn_segments(
        req.segments,
        TTS_AUDIO_DIR,
        getattr(req, "tts_align", None),
    )

    # 兜底一致性：一键成片场景下，字幕默认与 TTS 音频“强绑定”。
    # 若前端传来的 srt_content 与当前 segments 的 TTS 时长/结构不一致（过期/编辑导致），
    # 则在烧录阶段按 TTS 时长重新生成时间轴，确保最终成片字幕对齐配音。
    #
    # 若 strict_use_client_srt=True：完全按传入 SRT 烧录（不做任何校验/重建）。
    client_srt_raw = (req.srt_content or "").strip()
    srt_entries = parse_srt(client_srt_raw)
    subtitle_enabled = bool(client_srt_raw)
    try:
        if getattr(req, "strict_use_client_srt", False):
            raise RuntimeError("严格使用客户端SRT功能；跳过重建")
        if not subtitle_enabled:
            raise RuntimeError("由于srt_content为空，字幕已禁用；跳过重建")

        tts_durs, _src = resolve_durations(burn_segments, clip_dur, TTS_AUDIO_DIR, use_tts=True)
        expected_total = float(sum(float(x or 0.0) for x in tts_durs) or 0.0)

        def _needs_rebuild(entries: list, *, expected_total_sec: float) -> bool:
            if expected_total_sec <= 0.1:
                return False
            if not entries:
                return True

            # 基础合法性检查
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
            # 更严格的阈值：生成/烧录两端都按 ffprobe(TTS) 取时长，理论上差值应很小
            if abs(expected_total_sec - srt_total) > 0.15:
                return True
            # 覆盖不足也重建（避免字幕提前结束）
            if srt_total + 0.10 < expected_total_sec:
                return True
            # 若字幕明显超出音频，也重建（避免尾部“空字幕”）
            if srt_total - expected_total_sec > 0.20:
                return True
            return False

        max_chars = req.style.max_chars_per_line if req.style else 20
        fine_grain = bool(burn_tts_align.split_narration_by_sentence) if burn_tts_align else False
        timing_rebuild = _needs_rebuild(srt_entries, expected_total_sec=expected_total)
        chars_rebuild = srt_entries_exceed_max_chars(srt_entries, max_chars)
        if timing_rebuild or chars_rebuild:
            rebuilt_entries = rule_timeline_weighted_chars(
                burn_segments, tts_durs, max_chars, fine_grain_split=fine_grain
            )
            rebuilt_srt = build_srt(
                [{"start": e["start"], "end": e["end"], "text": e["text"]} for e in rebuilt_entries]
            )
            if timing_rebuild:
                logger.warning(
                    "烧录阶段已按 TTS 重建时间轴: srt=%.3fs expected_tts=%.3fs",
                    float(max((e.get("end", 0.0) for e in srt_entries), default=0.0) or 0.0),
                    expected_total,
                )
            if chars_rebuild:
                logger.warning(
                    "烧录阶段已按每行字数(%d)重建字幕切分: %d -> %d 条",
                    max_chars,
                    len(srt_entries),
                    len(rebuilt_entries),
                )
            srt_entries = parse_srt(rebuilt_srt)
    except Exception as e:
        # strict_use_client_srt 会主动走到这里：属于预期行为，不输出 warning 降噪。
        if getattr(req, "strict_use_client_srt", False):
            logger.info("strict_use_client_srt=True，烧录阶段跳过字幕时间轴校验/重建")
        elif not subtitle_enabled:
            logger.info("srt_content 为空，视为未启用字幕；烧录阶段跳过字幕时间轴校验/重建")
        else:
            logger.warning("烧录阶段校验/重建字幕时间轴失败，继续使用原 srt_content: %s", e)

    logger.info("烧录: %d 段, %d 条字幕", len(burn_segments), len(srt_entries))

    # 生成唯一的项目名，避免文件覆盖
    unique_project_name = f"{req.project_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    _, saved_path = await run_heavy(
        burn_to_mp4,
        segments=burn_segments,
        srt_entries=srt_entries,
        clip_map=clip_map,
        style=req.style,
        project_name=unique_project_name,
        tts_audio_dir=TTS_AUDIO_DIR,
        fonts_dir=_FONTS_DIR,
        render_opts=render_opts,
        export_render_opts=export_render_opts,
        render_mode="auto",
        export_backend=(req.export_backend or export_backend_cfg),
        output_dir=burn_output_dir,
        normalize_audio=False,
        materialize_from_source=req.materialize_from_source,
        tts_align=burn_tts_align,
        require_tts_audio=bool(getattr(req, "require_tts_audio", False)),
        production_profile=getattr(req, "production_profile", None),
    )

    if not saved_path or not os.path.exists(saved_path):
        raise HTTPException(500, "字幕烧录失败")

    filename = os.path.basename(saved_path)
    logger.info("烧录完成，已保存: %s", saved_path)
    result = {
        "filename": filename,
        "url": storage_public_url_for_file(saved_path),
    }
    if req.bgm and req.bgm.enabled:
        mixed_filename, mixed_url = await run_heavy(
            apply_bgm_config_postprocess,
            result["filename"],
            result["url"],
            req.bgm.model_dump(),
        )
        result["filename"] = mixed_filename
        result["url"] = mixed_url
    return result


async def execute_export_original(req: ExportOriginalRequest) -> dict:
    """
    原声拼接导出（可选字幕）；ffmpeg 走专用线程池。
    """
    if not req.segments:
        raise HTTPException(400, "segments不能为空")

    ids: List[str] = []
    for seg in req.segments:
        if seg.clip_id:
            ids.append(seg.clip_id)
        if seg.clip_ids:
            ids.extend([cid for cid in seg.clip_ids if cid])
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise HTTPException(400, "segments 缺少 clip_id/clip_ids")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await _load_clip_rows_with_raw_fallback(db, ids)
        render_opts = await _load_render_opts(db)
        export_render_opts = await _load_export_render_opts(db)
        export_backend_cfg = await _load_export_backend(db)

    if not rows:
        raise HTTPException(400, "未找到片段数据，请检查 clip_id 是否有效")

    burn_output_dir = _burned_output_dir_for_clip_rows(list(rows))

    clip_map = {}
    for r in rows:
        vfp = (r.get("video_file_path") or "").strip()
        clip_map[str(r["id"])] = {
            "path": resolve_stored_path(str(r.get("clip_path") or "")),
            "dur": float(r.get("duration") or 5),
            "src_video_path": resolve_stored_path(vfp) if vfp else "",
            "src_start": float(r.get("start_time") or 0.0),
            "src_end": float(r.get("end_time") or 0.0),
        }
    clip_dur = {cid: float(info["dur"] or 5) for cid, info in clip_map.items()}

    # 每段（segments 内每个 seg 对应的“段落”）总时长 = 该段选中 clip 组时长之和
    seg_durs: List[float] = []
    for seg in req.segments:
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

    max_chars = req.style.max_chars_per_line if req.style else 20
    srt_entries = rule_timeline_equal_units(req.segments, seg_durs, max_chars=max_chars) if req.include_subtitle else []

    # 显式忽略 tts_filename，确保 burn_to_mp4 走“保留原声/拼接”的分支。
    segments_for_burn: List[SubtitleSegmentInput] = []
    for seg in req.segments:
        segments_for_burn.append(
            SubtitleSegmentInput(
                copy_text=seg.copy_text,
                clip_id=seg.clip_id,
                clip_ids=seg.clip_ids,
                # 原声导出时也需要把用户/规划阶段的时长与裁剪偏移传给 burn_to_mp4
                duration_sec=getattr(seg, "duration_sec", None),
                clip_start_sec=getattr(seg, "clip_start_sec", None),
                clip_trims=getattr(seg, "clip_trims", None),
                tts_filename=None,
                mute_audio=bool(getattr(seg, "mute_audio", False)),
                transition_in=getattr(seg, "transition_in", None),
            )
        )

    unique_project_name = f"{req.project_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    _, saved_path = await run_heavy(
        burn_to_mp4,
        segments=segments_for_burn,
        srt_entries=srt_entries,
        clip_map=clip_map,
        style=req.style,
        project_name=unique_project_name,
        tts_audio_dir=TTS_AUDIO_DIR,
        fonts_dir=_FONTS_DIR,
        render_opts=render_opts,
        export_render_opts=export_render_opts,
        render_mode="original",
        output_dir=burn_output_dir,
        normalize_audio=req.normalize_audio,
        export_backend=(req.export_backend or export_backend_cfg),
        materialize_from_source=req.materialize_from_source,
        production_profile=getattr(req, "production_profile", None),
    )

    if not saved_path or not os.path.exists(saved_path):
        raise HTTPException(500, "原声导出失败")

    filename = os.path.basename(saved_path)
    logger.info("原声导出完成，已保存: %s", saved_path)
    result = {
        "filename": filename,
        "url": storage_public_url_for_file(saved_path),
    }
    if req.bgm and req.bgm.enabled:
        mixed_filename, mixed_url = await run_heavy(
            apply_bgm_config_postprocess,
            result["filename"],
            result["url"],
            req.bgm.model_dump(),
        )
        result["filename"] = mixed_filename
        result["url"] = mixed_url
    return result


# ---------------------------------------------------------------------------
# Route: 烧录字幕
# ---------------------------------------------------------------------------

@router.post("/burn")
async def burn_subtitle(req: BurnSubtitleRequest, request: Request):
    """合并视频 + 替换TTS音轨 + 硬烧字幕 -> 后台任务，返回 job_id。"""
    job = await create_job(kind="burn", initial_step="render")
    job_id = job["id"]

    async def _run():
        reporter = JobReporter(job_id)
        await reporter.send("render", "running", "正在渲染成片...")
        try:
            result = await execute_burn_subtitle(req)
            await update_job_status(job_id, "done", result=result)
            await reporter.send("done", "done", "成片渲染完成", {"result": result})
        except Exception as e:
            logger.exception("burn job %s failed", job_id)
            await reporter.send("error", "error", f"成片渲染失败: {e}")
            await update_job_status(job_id, "error", error_message=str(e))

    launch_job(job_id, _run())
    return {
        "job_id": job_id,
        "status": "running",
        "stream_url": f"/api/jobs/{job_id}/stream",
        "ws_url": f"/api/jobs/{job_id}/ws",
    }


# ---------------------------------------------------------------------------
# Route: 原声导出（保留原音 + 可选字幕）
# ---------------------------------------------------------------------------
@router.post("/export_original")
async def export_original(req: ExportOriginalRequest, request: Request):
    """
    根据原始素材（不使用 TTS）拼接视频：
    - 音频：保留原声，并对最终结果做归一化/限幅（可选）
    - 字幕：可选；字幕内容取文案，时间轴按“句子/换行等分”映射到每段总时长
    """
    if await request.is_disconnected():
        raise HTTPException(400, "客户端已断开连接")
    job = await create_job(kind="export_original", initial_step="render")
    job_id = job["id"]

    async def _run():
        reporter = JobReporter(job_id)
        await reporter.send("render", "running", "正在导出原声成片...")
        try:
            result = await execute_export_original(req)
            await update_job_status(job_id, "done", result=result)
            await reporter.send("done", "done", "原声导出完成", {"result": result})
        except Exception as e:
            logger.exception("export_original job %s failed", job_id)
            await update_job_status(job_id, "error", error_message=str(e))
            await reporter.send("error", "error", "原声导出失败: " + str(e))

    launch_job(job_id, _run())
    return {
        "job_id": job_id,
        "status": "running",
        "stream_url": "/api/jobs/" + job_id + "/stream",
        "ws_url": "/api/jobs/" + job_id + "/ws",
    }


# ---------------------------------------------------------------------------
# Route: 仅导出剪映草稿 ZIP（不渲染成片）
# ---------------------------------------------------------------------------
@router.post("/export_jianying_draft", response_model=JianYingDraftExportResponse)
async def export_jianying_draft(req: JianYingDraftExportRequest, request: Request):
    """生成剪映草稿（ZIP 下载或按设置直写目录），不与 burn / export_original 并行。"""
    if await request.is_disconnected():
        raise HTTPException(400, "客户端已断开连接")
    segs = list(req.segments)
    if req.tts_align is not None and req.mode == "tts":
        apply_timeline_duration_overrides(segs, req.tts_align, TTS_AUDIO_DIR)
    return await export_jianying_draft_zip_async(
        segments=segs,
        mode=req.mode,
        project_name_base=(req.project_name or "smartclip_jianying").strip(),
        tts_audio_dir=TTS_AUDIO_DIR,
        style=req.style,
        client_srt_content=req.srt_content if req.mode == "tts" else "",
        strict_use_client_srt=req.strict_use_client_srt if req.mode == "tts" else False,
        include_subtitle=req.include_subtitle if req.mode == "original" else True,
    )


# ---------------------------------------------------------------------------
# Route: 下载视频
# ---------------------------------------------------------------------------

def _find_jianying_zip_file(filename: str) -> str | None:
    """查找 ``storage/jianying_drafts/<filename>.zip``。"""
    base = os.path.basename(filename)
    direct = os.path.join(ensure_storage_subpath("jianying_drafts"), base)
    if os.path.isfile(direct):
        return direct
    return None


def _find_burned_export_file(filename: str) -> str | None:
    """在旧版扁平目录或各素材 ``storage/<id>/burned_videos/`` 下查找成片。"""
    base = os.path.basename(filename)
    legacy = os.path.join(ensure_storage_subpath("burned_videos"), base)
    if os.path.isfile(legacy):
        return legacy
    root = get_storage_root()
    try:
        for mid in os.listdir(root):
            candidate = os.path.join(str(root), mid, "burned_videos", base)
            if os.path.isfile(candidate):
                return candidate
    except Exception:
        pass
    return None


@router.get("/download_jianying/{filename}")
async def download_jianying_zip(filename: str):
    """下载剪映草稿 ZIP"""
    filepath = _find_jianying_zip_file(filename)
    if not filepath:
        raise HTTPException(404, "文件不存在")
    encoded_filename = quote(filename)
    content_disposition = (
        'attachment; filename="jianying_draft.zip"; '
        f"filename*=UTF-8''{encoded_filename}"
    )
    return FileResponse(
        filepath,
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition},
    )


@router.get("/download/{filename}")
async def download_video(filename: str):
    """下载烧录后的视频文件"""
    filepath = _find_burned_export_file(filename)
    if not filepath:
        raise HTTPException(404, "文件不存在")
    # 避免中文文件名导致 latin-1 编码报错：使用 RFC 5987 filename*
    encoded_filename = quote(filename)
    content_disposition = (
        'attachment; filename="smartclip_subtitled.mp4"; '
        f"filename*=UTF-8''{encoded_filename}"
    )
    return FileResponse(
        filepath,
        media_type="video/mp4",
        headers={"Content-Disposition": content_disposition}
    )
