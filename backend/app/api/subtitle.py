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
    SRTEntry,
    SubtitleSegmentInput,
    SubtitleStyle,  # noqa: F401 - 用于模块级 re-export
)

from app.core.blocking_pool import run_heavy
from app.db.database import DB_PATH
from app.core.subtitle.srt import build_srt, parse_srt
from app.core.subtitle.timeline import resolve_durations, rule_timeline, rule_timeline_equal_units
from app.core.subtitle.burn import burn_to_mp4

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/subtitle", tags=["subtitle"])

TTS_AUDIO_DIR = os.path.abspath(os.path.join(os.path.dirname(DB_PATH), "tts_audio"))
# 目录常量（统一以 backend/ 为根）
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_FONTS_DIR = os.path.join(_BACKEND_DIR, "fonts")

# 持久化存储：烧录成品统一放 backend/storage/burned_videos/
_BURNED_VIDEOS_DIR = os.path.join(_BACKEND_DIR, "storage", "burned_videos")
os.makedirs(_BURNED_VIDEOS_DIR, exist_ok=True)


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
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT id,duration FROM clips WHERE id IN ({','.join(['?']*len(ids))})", ids
        ) as cur:
            rows = await cur.fetchall()

    clip_dur = {r["id"]: float(r["duration"] or 5.0) for r in rows}
    max_chars = req.style.max_chars_per_line if req.style else 20

    durs, src = resolve_durations(req.segments, clip_dur, TTS_AUDIO_DIR, req.use_tts_timing)

    # 一键成片默认走规则法，确保字幕与配音时长完全可控，避免 LLM 对齐偏差。
    raw_entries = rule_timeline(req.segments, durs, max_chars)

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
        async with db.execute(
            f"SELECT id,clip_path,duration FROM clips WHERE id IN ({','.join(['?']*len(ids))})",
            ids,
        ) as cur:
            rows = await cur.fetchall()
        render_opts = await _load_render_opts(db)
        export_render_opts = await _load_export_render_opts(db)
        export_backend_cfg = await _load_export_backend(db)

    clip_map = {
        r["id"]: {"path": r["clip_path"], "dur": float(r["duration"] or 5)}
        for r in rows
    }
    clip_dur = {cid: float(info.get("dur") or 5.0) for cid, info in clip_map.items()}

    # 兜底一致性：一键成片场景下，字幕应与 TTS 音频“强绑定”。
    # 若前端传来的 srt_content 与当前 segments 的 TTS 总时长明显不一致，说明可能拿错/过期/被编辑过，
    # 此时在烧录阶段按 TTS 时长重新生成时间轴，避免“语音正常但字幕漂移/错内容”。
    srt_entries = parse_srt(req.srt_content or "")
    try:
        tts_durs, _src = resolve_durations(req.segments, clip_dur, TTS_AUDIO_DIR, use_tts=True)
        expected_total = float(sum(float(x or 0.0) for x in tts_durs) or 0.0)
        srt_total = float(max((e.get("end", 0.0) for e in srt_entries), default=0.0) or 0.0)
        # 允许少量误差（毫秒级 rounding、编码容器差异），超过阈值则重建
        if expected_total > 0.1 and abs(expected_total - srt_total) > 0.35:
            max_chars = req.style.max_chars_per_line if req.style else 20
            rebuilt_entries = rule_timeline(req.segments, tts_durs, max_chars)
            rebuilt_srt = build_srt([{"start": e["start"], "end": e["end"], "text": e["text"]} for e in rebuilt_entries])
            logger.warning(
                "检测到 srt_content 与 TTS 总时长不一致，烧录阶段已按 TTS 重新生成时间轴: srt=%.3fs expected_tts=%.3fs",
                srt_total,
                expected_total,
            )
            srt_entries = parse_srt(rebuilt_srt)
    except Exception as e:
        logger.warning("烧录阶段校验/重建字幕时间轴失败，继续使用原 srt_content: %s", e)

    logger.info("烧录: %d 段, %d 条字幕", len(req.segments), len(srt_entries))

    # 生成唯一的项目名，避免文件覆盖
    unique_project_name = f"{req.project_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    _, saved_path = await run_heavy(
        burn_to_mp4,
        segments=req.segments,
        srt_entries=srt_entries,
        clip_map=clip_map,
        style=req.style,
        project_name=unique_project_name,
        tts_audio_dir=TTS_AUDIO_DIR,
        fonts_dir=_FONTS_DIR,
        render_opts=render_opts,
        export_render_opts=export_render_opts,
        render_mode="tts",
        export_backend=(req.export_backend or export_backend_cfg),
        output_dir=_BURNED_VIDEOS_DIR,
    )

    if not saved_path or not os.path.exists(saved_path):
        raise HTTPException(500, "字幕烧录失败")

    filename = os.path.basename(saved_path)
    logger.info("烧录完成，已保存: %s", saved_path)
    return {
        "filename": filename,
        "url": f"/storage/burned_videos/{filename}",
    }


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
        async with db.execute(
            f"SELECT id,clip_path,duration FROM clips WHERE id IN ({','.join(['?']*len(ids))})",
            ids,
        ) as cur:
            rows = await cur.fetchall()
        render_opts = await _load_render_opts(db)
        export_render_opts = await _load_export_render_opts(db)
        export_backend_cfg = await _load_export_backend(db)

    clip_map = {
        r["id"]: {"path": r["clip_path"], "dur": float(r["duration"] or 5)}
        for r in rows
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
        output_dir=_BURNED_VIDEOS_DIR,
        normalize_audio=req.normalize_audio,
        export_backend=(req.export_backend or export_backend_cfg),
    )

    if not saved_path or not os.path.exists(saved_path):
        raise HTTPException(500, "原声导出失败")

    filename = os.path.basename(saved_path)
    logger.info("原声导出完成，已保存: %s", saved_path)
    return {
        "filename": filename,
        "url": f"/storage/burned_videos/{filename}",
    }


# ---------------------------------------------------------------------------
# Route: 烧录字幕
# ---------------------------------------------------------------------------

@router.post("/burn")
async def burn_subtitle(req: BurnSubtitleRequest, request: Request):
    """合并视频 + 替换TTS音轨 + 硬烧字幕，保存到静态目录，返回可访问的 URL。"""
    if await request.is_disconnected():
        raise HTTPException(400, "客户端已断开连接")
    return await execute_burn_subtitle(req)


# ---------------------------------------------------------------------------
# Route: 原声导出（保留原音 + 可选字幕）
# ---------------------------------------------------------------------------
@router.post("/export_original", response_model=BurnSubtitleResponse)
async def export_original(req: ExportOriginalRequest, request: Request):
    """
    根据原始素材（不使用 TTS）拼接视频：
    - 音频：保留原声，并对最终结果做归一化/限幅（可选）
    - 字幕：可选；字幕内容取文案，时间轴按“句子/换行等分”映射到每段总时长
    """
    if await request.is_disconnected():
        raise HTTPException(400, "客户端已断开连接")
    return await execute_export_original(req)


# ---------------------------------------------------------------------------
# Route: 下载视频
# ---------------------------------------------------------------------------

@router.get("/download/{filename}")
async def download_video(filename: str):
    """下载烧录后的视频文件"""
    filepath = os.path.join(_BURNED_VIDEOS_DIR, filename)
    if not os.path.exists(filepath):
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
