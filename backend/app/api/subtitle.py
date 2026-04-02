"""subtitle.py — SRT字幕生成 & 烧录 路由层（薄封装，业务逻辑见 core/subtitle）"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote

import aiosqlite
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

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
    """读取烧录渲染参数（来源 config 表，不在路由层硬编码默认值）。"""
    keys = [
        "clip_vcodec",
        "clip_acodec",
        "clip_preset",
        "clip_crf",
        "clip_video_bitrate_kbps",
        "clip_audio_bitrate_kbps",
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


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SubtitleSegmentInput(BaseModel):
    copy_text: str
    clip_id: str
    clip_ids: Optional[List[str]] = None
    tts_filename: Optional[str] = None


class SubtitleStyle(BaseModel):
    font_name: str = "Arial"
    font_size: int = 24
    font_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_width: float = 2.0
    shadow: float = 1.0
    bold: bool = False
    italic: bool = False
    position: str = "bottom"   # bottom | center | top
    margin_v: int = 20
    pos_x_pct: float = 50.0
    pos_y_pct: float = 90.0
    background: bool = False
    max_chars_per_line: int = 20


class GenerateSRTRequest(BaseModel):
    segments: List[SubtitleSegmentInput]
    style: Optional[SubtitleStyle] = None
    use_tts_timing: bool = True


class SRTEntry(BaseModel):
    index: int
    start: float
    end: float
    text: str
    clip_id: str


class GenerateSRTResponse(BaseModel):
    srt_content: str
    entries: List[SRTEntry]
    total_duration: float
    timing_source: str


class BurnSubtitleResponse(BaseModel):
    filename: str
    url: str


class BurnSubtitleRequest(BaseModel):
    segments: List[SubtitleSegmentInput]
    srt_content: str
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    project_name: Optional[str] = "smartclip_subtitled"


class ExportOriginalRequest(BaseModel):
    """
    原声导出：
    - 不使用 TTS（忽略 tts_filename）
    - 段落（segments 内每一段）的总时长 = 该段选中 clip 组的时长之和
    - 可选：按“句子/换行”切分文案，并在该段总时长内等分
    - 可选：对最终音频做归一化/限幅
    """

    segments: List[SubtitleSegmentInput]
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    project_name: Optional[str] = "smartclip_original"
    include_subtitle: bool = True
    normalize_audio: bool = True


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

    clip_map = {
        r["id"]: {"path": r["clip_path"], "dur": float(r["duration"] or 5)}
        for r in rows
    }
    srt_entries = parse_srt(req.srt_content)
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

    clip_map = {
        r["id"]: {"path": r["clip_path"], "dur": float(r["duration"] or 5)}
        for r in rows
    }
    clip_dur = {cid: float(info["dur"] or 5) for cid, info in clip_map.items()}

    # 每段（segments 内每个 seg 对应的“段落”）总时长 = 该段选中 clip 组时长之和
    seg_durs: List[float] = []
    for seg in req.segments:
        raw_ids = list(getattr(seg, "clip_ids", None) or [])
        if not raw_ids and getattr(seg, "clip_id", None):
            raw_ids = [seg.clip_id]
        group_ids = list(dict.fromkeys([cid for cid in raw_ids if cid]))
        total = sum(clip_dur.get(cid, 5.0) for cid in group_ids)
        if total <= 0:
            total = 5.0
        seg_durs.append(total)

    srt_entries = (
        rule_timeline_equal_units(req.segments, seg_durs) if req.include_subtitle else []
    )

    # 显式忽略 tts_filename，确保 burn_to_mp4 走“保留原声/拼接”的分支。
    segments_for_burn: List[SubtitleSegmentInput] = []
    for seg in req.segments:
        segments_for_burn.append(
            SubtitleSegmentInput(
                copy_text=seg.copy_text,
                clip_id=seg.clip_id,
                clip_ids=seg.clip_ids,
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
        output_dir=_BURNED_VIDEOS_DIR,
        normalize_audio=req.normalize_audio,
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
