import logging
import os
import uuid
from typing import Optional

import aiosqlite
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.db.database import DB_PATH

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tts", tags=["tts"])

# TTS 音频输出目录（与 DB 同级的 data/tts_audio/）
TTS_AUDIO_DIR = os.path.abspath(
    os.path.join(os.path.dirname(DB_PATH), "tts_audio")
)
os.makedirs(TTS_AUDIO_DIR, exist_ok=True)


# ──────────────────────────── 请求 / 响应模型 ──────────────────────────── #

class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000, description="待合成文本")
    voice: Optional[str] = Field(None, description="语音角色（可选，不填用配置默认值）")
    rate: Optional[str] = Field(None, description="语速，如 +0%/-20%（可选）")
    volume: Optional[str] = Field(None, description="音量，如 +0%/+10%（可选）")


class SynthesizeResponse(BaseModel):
    filename: str
    url: str
    voice: str
    rate: str
    volume: str
    text_length: int


class VoiceInfo(BaseModel):
    name: str
    locale: str
    gender: str
    friendly_name: str


# ──────────────────────────── 辅助函数 ──────────────────────────── #

async def _read_cfg(db: aiosqlite.Connection, key: str, default: str = "") -> str:
    async with db.execute("SELECT value FROM config WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
    return row[0] if row else default


# ──────────────────────────── 路由 ──────────────────────────── #

@router.post("/synthesize", response_model=SynthesizeResponse)
async def synthesize(req: SynthesizeRequest):
    """文字转语音，返回可直接播放的音频文件 URL"""
    async with aiosqlite.connect(DB_PATH) as db:
        default_voice  = await _read_cfg(db, "tts_voice",  "zh-CN-XiaoxiaoNeural")
        default_rate   = await _read_cfg(db, "tts_rate",   "+0%")
        default_volume = await _read_cfg(db, "tts_volume", "+0%")

    voice  = req.voice  or default_voice
    rate   = req.rate   or default_rate
    volume = req.volume or default_volume

    filename = f"{uuid.uuid4().hex}.mp3"
    output_path = os.path.join(TTS_AUDIO_DIR, filename)

    try:
        from app.core.tts.edge_tts_impl import EdgeTTS
        tts = EdgeTTS(default_voice=voice, default_rate=rate, default_volume=volume)
        await tts.synthesize(text=req.text, output_path=output_path, voice=voice, rate=rate, volume=volume)
    except Exception as e:
        logger.error("TTS 合成失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"TTS 合成失败: {str(e)}")

    return SynthesizeResponse(
        filename=filename,
        url=f"/api/tts/audio/{filename}",
        voice=voice,
        rate=rate,
        volume=volume,
        text_length=len(req.text),
    )


@router.get("/voices", response_model=list[VoiceInfo])
async def list_voices(locale: Optional[str] = None):
    """获取可用语音列表，locale 示例：zh-CN、en-US"""
    try:
        from app.core.tts.edge_tts_impl import EdgeTTS
        tts = EdgeTTS()
        voices = await tts.list_voices(locale=locale)
        return voices
    except Exception as e:
        logger.error("获取语音列表失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取语音列表失败: {str(e)}")


@router.get("/audio/{filename}")
async def get_audio(filename: str):
    """下载 / 播放已合成的音频文件"""
    # 安全：只允许访问 TTS_AUDIO_DIR 内的文件
    safe_name = os.path.basename(filename)
    file_path = os.path.join(TTS_AUDIO_DIR, safe_name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="音频文件不存在")
    return FileResponse(file_path, media_type="audio/mpeg", filename=safe_name)
