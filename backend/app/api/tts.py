import logging
import os
import uuid
from typing import Optional

import aiosqlite
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.core.tts.providers import (
    synthesize_custom_http,
    synthesize_gpt_sovits,
    synthesize_index_tts,
    synthesize_openai_like,
    synthesize_volcengine,
)
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
    """文字转语音，根据 tts_provider 配置分发到对应引擎"""
    async with aiosqlite.connect(DB_PATH) as db:
        provider      = await _read_cfg(db, "tts_provider",  "edge-tts")
        default_voice = await _read_cfg(db, "tts_voice",     "zh-CN-XiaoxiaoNeural")
        default_rate  = await _read_cfg(db, "tts_rate",      "+0%")
        default_vol   = await _read_cfg(db, "tts_volume",    "+0%")
        tts_base_url  = await _read_cfg(db, "tts_base_url",  "")
        tts_api_key   = await _read_cfg(db, "tts_api_key",   "")
        tts_model     = await _read_cfg(db, "tts_model",     "")
        tts_format    = await _read_cfg(db, "tts_format",    "mp3")
        # bailian
        bailian_app_key      = await _read_cfg(db, "bailian_app_key", "")
        # volcengine
        volc_app_id  = await _read_cfg(db, "volcengine_app_id",  "")
        volc_token   = await _read_cfg(db, "volcengine_token",   "")
        volc_cluster = await _read_cfg(db, "volcengine_cluster", "volcano_tts")
        # gpt-sovits
        gsv_ref_audio = await _read_cfg(db, "gsv_ref_audio", "")
        gsv_ref_text  = await _read_cfg(db, "gsv_ref_text",  "")
        gsv_lang      = await _read_cfg(db, "gsv_lang",      "zh")
        # index-tts
        index_ref_audio = await _read_cfg(db, "index_tts_ref_audio", "")
        # custom-http
        ch_method        = await _read_cfg(db, "custom_tts_method",        "GET")
        ch_url           = await _read_cfg(db, "custom_tts_url",           "")
        ch_headers       = await _read_cfg(db, "custom_tts_headers",       "")
        ch_body          = await _read_cfg(db, "custom_tts_body",          "")
        ch_response_type = await _read_cfg(db, "custom_tts_response_type", "binary")
        ch_audio_key     = await _read_cfg(db, "custom_tts_audio_key",     "")

    voice  = req.voice  or default_voice
    rate   = req.rate   or default_rate
    volume = req.volume or default_vol
    ext    = tts_format if tts_format in ("mp3", "wav", "ogg", "pcm") else "mp3"
    filename    = f"{uuid.uuid4().hex}.{ext}"
    output_path = os.path.join(TTS_AUDIO_DIR, filename)

    try:
        if provider == "edge-tts":
            from app.core.tts.edge_tts_impl import EdgeTTS
            tts = EdgeTTS(default_voice=voice, default_rate=rate, default_volume=volume)
            await tts.synthesize(text=req.text, output_path=output_path,
                                 voice=voice, rate=rate, volume=volume)

        elif provider in ("openai", "bailian"):
            await synthesize_openai_like(
                text=req.text,
                output_path=output_path,
                base_url=tts_base_url,
                api_key=tts_api_key,
                model=tts_model,
                voice=voice,
                response_format=ext,
                app_key=bailian_app_key if provider == "bailian" else "",
            )

        elif provider == "volcengine":
            await synthesize_volcengine(
                text=req.text,
                output_path=output_path,
                base_url=tts_base_url,
                app_id=volc_app_id,
                token=volc_token,
                cluster=volc_cluster,
                voice=voice,
                encoding=ext,
            )

        elif provider == "gpt-sovits":
            await synthesize_gpt_sovits(
                text=req.text,
                output_path=output_path,
                base_url=tts_base_url,
                ref_audio=gsv_ref_audio,
                ref_text=gsv_ref_text,
                lang=gsv_lang,
            )

        elif provider == "index-tts":
            await synthesize_index_tts(
                text=req.text,
                output_path=output_path,
                base_url=tts_base_url,
                ref_audio=index_ref_audio,
            )

        elif provider == "custom-http":
            await synthesize_custom_http(
                text=req.text, output_path=output_path,
                method=ch_method, url_template=ch_url,
                headers_raw=ch_headers, body_template=ch_body,
                response_type=ch_response_type, audio_key=ch_audio_key,
            )


        else:
            raise HTTPException(status_code=400, detail=f"未知 TTS 引擎: {provider}")

    except HTTPException:
        raise
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
