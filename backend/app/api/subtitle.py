"""subtitle.py — SRT字幕生成 & 烧录 路由层（薄封装，业务逻辑见 core/subtitle）"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote

import aiosqlite
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.db.database import DB_PATH
from app.core.subtitle.srt import build_srt, parse_srt
from app.core.subtitle.timeline import resolve_durations, rule_timeline
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


class BurnSubtitleRequest(BaseModel):
    segments: List[SubtitleSegmentInput]
    srt_content: str
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    project_name: Optional[str] = "smartclip_subtitled"


# ---------------------------------------------------------------------------
# Route: 生成 SRT 时间轴
# ---------------------------------------------------------------------------

@router.post("/generate", response_model=GenerateSRTResponse)
async def generate_srt(req: GenerateSRTRequest):
    """生成SRT时间轴，按TTS音频时长严格切分并对齐。"""
    if not req.segments:
        raise HTTPException(400, "segments不能为空")

    ids = [s.clip_id for s in req.segments]
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
# Route: 烧录字幕
# ---------------------------------------------------------------------------

@router.post("/burn")
async def burn_subtitle(req: BurnSubtitleRequest):
    """合并视频 + 替换TTS音轨 + 硬烧字幕，保存到静态目录，返回可访问的 URL。"""
    if not req.segments:
        raise HTTPException(400, "segments不能为空")

    ids = [s.clip_id for s in req.segments]
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

    _, saved_path = burn_to_mp4(
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
