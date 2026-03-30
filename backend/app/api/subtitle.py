"""subtitle.py — SRT字幕生成 & 烧录 路由层（薄封装，业务逻辑见 core/subtitle）"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import List, Optional

import aiosqlite
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.db.database import DB_PATH
from app.core.subtitle.srt import build_srt, parse_srt
from app.core.subtitle.timeline import read_cfg, resolve_durations, rule_timeline, llm_timeline
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
    """生成SRT时间轴，TTS音频时长优先于视频片段时长。"""
    if not req.segments:
        raise HTTPException(400, "segments不能为空")

    ids = [s.clip_id for s in req.segments]
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        bu = await read_cfg(db, "vlm_base_url")
        ak = await read_cfg(db, "vlm_api_key")
        model = await read_cfg(db, "llm_model") or await read_cfg(db, "vlm_model")
        async with db.execute(
            f"SELECT id,duration FROM clips WHERE id IN ({','.join(['?']*len(ids))})", ids
        ) as cur:
            rows = await cur.fetchall()

    clip_dur = {r["id"]: float(r["duration"] or 5.0) for r in rows}
    max_chars = req.style.max_chars_per_line if req.style else 20

    durs, src = resolve_durations(req.segments, clip_dur, TTS_AUDIO_DIR, req.use_tts_timing)

    raw_entries: list = []
    if bu and ak and model:
        try:
            logger.info("LLM生成时间轴...")
            raw_entries = await llm_timeline(req.segments, durs, bu, ak, model)
        except Exception as e:
            logger.warning("LLM失败降级rule: %s", e)
            raw_entries = rule_timeline(req.segments, durs, max_chars)
    else:
        raw_entries = rule_timeline(req.segments, durs, max_chars)

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
    return FileResponse(
        filepath,
        media_type="video/mp4",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
