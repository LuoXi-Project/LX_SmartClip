"""
上传已配音音频 → ASR 文案与时间轴 → 按段切片到 tts_audio，供手动匹配同款成片管线使用。
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any

import aiosqlite
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.asr import get_asr
from app.api.tts import TTS_AUDIO_DIR
from app.core.blocking_pool import run_heavy
from app.db.database import DB_PATH
from app.models.audio_match import AudioMatchSliceRequest, AudioMatchSliceResponse
from app.utils.ffmpeg_utils import extract_audio_for_asr, run_ffmpeg
from app.utils.ffprobe_utils import probe_duration
from app.utils.paths import ensure_storage_subpath

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/audio-match", tags=["audio-match"])

_MAX_UPLOAD_BYTES = 120 * 1024 * 1024
_AUDIO_MATCH_DIR: str | None = None


def _audio_match_dir() -> str:
    global _AUDIO_MATCH_DIR
    if _AUDIO_MATCH_DIR is None:
        _AUDIO_MATCH_DIR = ensure_storage_subpath("audio_match")
    return _AUDIO_MATCH_DIR


async def _read_config(db: aiosqlite.Connection, key: str, default: str = "") -> str:
    cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = await cursor.fetchone()
    if not row:
        return default
    v = row[0]
    return default if v is None else str(v)


def _safe_basename(name: str) -> str:
    return os.path.basename((name or "").strip())


def _resolve_source_path(source_filename: str) -> str:
    safe = _safe_basename(source_filename)
    if not safe.startswith("src_"):
        raise HTTPException(status_code=400, detail="无效的 source_filename")
    path = os.path.join(_audio_match_dir(), safe)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="源音频不存在，请重新上传识别")
    return path


def _slice_audio_sync(source_path: str, start_sec: float, end_sec: float, out_path: str) -> None:
    start = max(0.0, float(start_sec))
    end = max(start + 0.05, float(end_sec))
    dur = end - start
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    run_ffmpeg(
        [
            "-ss",
            f"{start:.3f}",
            "-i",
            source_path,
            "-t",
            f"{dur:.3f}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            out_path,
        ],
        desc="audio-match-slice",
    )


@router.post("/transcribe")
async def transcribe_narration(
    file: UploadFile = File(..., description="已配音音频（mp3/wav/m4a 等）"),
):
    """
    上传配音文件 → 转 WAV → ASR 带时间轴 → 返回全文与句级 segments。
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="空文件")
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"文件过大（>{_MAX_UPLOAD_BYTES // (1024 * 1024)}MB）",
        )

    uid = uuid.uuid4().hex[:12]
    base = _audio_match_dir()
    raw_ext = os.path.splitext((file.filename or "").strip())[1].lower() or ".mp3"
    if raw_ext not in (".webm", ".wav", ".mp3", ".m4a", ".ogg", ".opus", ".flac", ".aac"):
        raw_ext = ".mp3"
    source_filename = f"src_{uid}{raw_ext}"
    wav_filename = f"src_{uid}.wav"
    raw_path = os.path.join(base, source_filename)
    wav_path = os.path.join(base, wav_filename)

    def _write_raw() -> None:
        os.makedirs(base, exist_ok=True)
        with open(raw_path, "wb") as f:
            f.write(raw)

    await asyncio.to_thread(_write_raw)

    try:
        await run_heavy(extract_audio_for_asr, raw_path, wav_path, overwrite=True)
        asr_input = wav_path
    except Exception as e:
        logger.warning("配音转 WAV 失败，尝试原文件 ASR: %s", e)
        asr_input = raw_path

    async with aiosqlite.connect(DB_PATH) as db:
        asr_provider = await _read_config(db, "asr_provider", "whisper")
        model_size = await _read_config(db, "asr_model", "small")
        asr_base_url = await _read_config(db, "asr_base_url", "https://api.openai.com/v1")
        asr_api_key = await _read_config(db, "asr_api_key", "")
        asr_openai_model = await _read_config(db, "asr_openai_model", "whisper-1")
        asr_language = (await _read_config(db, "asr_language", "zh") or "").strip()

    try:
        asr_instance = get_asr(
            provider=asr_provider,
            model_size=model_size,
            base_url=asr_base_url,
            api_key=asr_api_key,
            model=asr_openai_model,
            language=asr_language,
        )
    except Exception as e:
        logger.error("ASR 初始化失败: %s", e)
        raise HTTPException(status_code=500, detail=f"ASR 初始化失败: {e}") from e

    try:
        tr = await run_heavy(asr_instance.transcribe_detailed, asr_input)
    except Exception as e:
        logger.error("配音 ASR 失败: %s", e)
        raise HTTPException(status_code=502, detail=f"语音识别失败: {e}") from e

    duration = probe_duration(asr_input) or probe_duration(wav_path) or 0.0
    segments: list[dict[str, Any]] = []
    for s in tr.segments or ():
        text = (s.text or "").strip()
        if not text:
            continue
        st = max(0.0, float(s.start))
        ed = max(st + 0.05, float(s.end))
        segments.append({"start": st, "end": ed, "text": text})

    if not segments and (tr.text or "").strip():
        segments.append({"start": 0.0, "end": max(duration, 0.5), "text": tr.text.strip()})

    return {
        "source_filename": source_filename,
        "wav_filename": wav_filename if os.path.isfile(wav_path) else None,
        "text": (tr.text or "").strip(),
        "segments": segments,
        "duration_sec": duration,
        "provider": asr_provider,
    }


@router.post("/slice", response_model=AudioMatchSliceResponse)
async def slice_narration(req: AudioMatchSliceRequest):
    """按时间轴将源配音切成多段，写入 tts_audio 目录（供 subtitle 成片当作 tts_filename 使用）。"""
    source_path = _resolve_source_path(req.source_filename)
    # 优先用 16k wav（与 ASR 一致），否则用上传的原始文件
    wav_name = os.path.splitext(_safe_basename(req.source_filename))[0] + ".wav"
    wav_path = os.path.join(_audio_match_dir(), wav_name)
    slice_from = wav_path if os.path.isfile(wav_path) else source_path

    filenames: list[str] = []
    for item in req.slices:
        if item.end_sec <= item.start_sec:
            raise HTTPException(status_code=400, detail="切片 end_sec 须大于 start_sec")
        out_name = f"am_{uuid.uuid4().hex[:10]}.wav"
        out_path = os.path.join(TTS_AUDIO_DIR, out_name)
        await run_heavy(_slice_audio_sync, slice_from, item.start_sec, item.end_sec, out_path)
        filenames.append(out_name)

    return AudioMatchSliceResponse(filenames=filenames)


@router.get("/source/{filename}")
async def stream_source_audio(filename: str):
    """播放/预览上传的源配音（原始上传文件）。"""
    path = _resolve_source_path(filename)
    ext = os.path.splitext(path)[1].lower()
    media = "audio/wav" if ext == ".wav" else "audio/mpeg"
    return FileResponse(path, media_type=media, filename=_safe_basename(filename))
