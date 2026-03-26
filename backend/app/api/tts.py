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


def _get_nested(data: dict, path: str):
    """按点号路径取嵌套值，支持数字索引，如 data.result.0.url"""
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if cur is None:
            return None
    return cur


async def _synthesize_custom_get(
    text: str, output_path: str,
    url_template: str, response_type: str, audio_key: str,
) -> str:
    """自定义 GET TTS：直接响应音频(binary) 或 JSON 中取 URL 再下载"""
    import httpx
    url = url_template.replace("{text}", text)
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url)
    if resp.status_code != 200:
        raise RuntimeError(f"自定义 GET 请求失败: HTTP {resp.status_code}")

    content_type = resp.headers.get("content-type", "")

    if response_type == "binary" or "audio" in content_type or "octet-stream" in content_type:
        # 直接写入音频字节
        with open(output_path, "wb") as f:
            f.write(resp.content)
        return output_path

    # JSON 模式：解析后按路径取音频 URL 再下载
    try:
        data = resp.json()
    except Exception:
        # 解析失败时降级为 binary
        with open(output_path, "wb") as f:
            f.write(resp.content)
        return output_path

    audio_url = _get_nested(data, audio_key) if audio_key else None
    if not audio_url:
        raise RuntimeError(f"JSON 响应中未找到路径 '{audio_key}'，响应体: {str(data)[:200]}")

    async with httpx.AsyncClient(timeout=60) as client:
        audio_resp = await client.get(audio_url)
    if audio_resp.status_code != 200:
        raise RuntimeError(f"下载音频 URL 失败: HTTP {audio_resp.status_code}")
    with open(output_path, "wb") as f:
        f.write(audio_resp.content)
    return output_path



async def _do_custom_http(
    text: str,
    output_path: str,
    method: str,
    url_template: str,
    headers_raw: str,
    body_template: str,
    response_type: str,
    audio_key: str,
) -> str:
    """
    Custom HTTP TTS:
    - GET or POST
    - {text} placeholder in URL and body
    - Headers as JSON string
    - Response: binary (direct audio) or json (extract URL by dot-path then download)
    """
    import httpx
    import json as _json

    url = url_template.replace("{text}", text)

    headers: dict = {}
    if headers_raw.strip():
        try:
            headers = _json.loads(headers_raw)
        except Exception:
            raise RuntimeError(f"请求头 JSON 解析失败: {headers_raw[:200]}")

    async with httpx.AsyncClient(timeout=60) as client:
        if method.upper() == "POST":
            body_str = body_template.replace("{text}", text) if body_template.strip() else None
            body_data = None
            if body_str:
                try:
                    body_data = _json.loads(body_str)
                except Exception:
                    raise RuntimeError(f"请求体 JSON 解析失败: {body_str[:200]}")
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"
            resp = await client.post(url, headers=headers, json=body_data)
        else:
            resp = await client.get(url, headers=headers)

    if resp.status_code != 200:
        raise RuntimeError(f"自定义 HTTP TTS 请求失败: HTTP {resp.status_code} {resp.text[:200]}")

    content_type = resp.headers.get("content-type", "")
    if response_type == "binary" or "audio" in content_type or "octet-stream" in content_type:
        with open(output_path, "wb") as f:
            f.write(resp.content)
        return output_path

    # json mode
    try:
        data = resp.json()
    except Exception:
        with open(output_path, "wb") as f:
            f.write(resp.content)
        return output_path

    audio_url = _get_nested(data, audio_key) if audio_key else None
    if not audio_url:
        raise RuntimeError(f"JSON 响应中未找到路径 '{audio_key}'，响应体: {str(data)[:300]}")

    async with httpx.AsyncClient(timeout=60) as client:
        audio_resp = await client.get(str(audio_url))
    if audio_resp.status_code != 200:
        raise RuntimeError(f"下载音频 URL 失败: HTTP {audio_resp.status_code}")
    with open(output_path, "wb") as f:
        f.write(audio_resp.content)
    return output_path

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
            import httpx
            base = tts_base_url.rstrip("/")
            endpoint = f"{base}/audio/speech"
            headers = {"Authorization": f"Bearer {tts_api_key}", "Content-Type": "application/json"}
            if provider == "bailian" and bailian_app_key:
                headers["X-DashScope-AppId"] = bailian_app_key
            body = {"model": tts_model or "tts-1", "input": req.text,
                    "voice": voice, "response_format": ext}
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(endpoint, headers=headers, json=body)
            if resp.status_code != 200:
                raise RuntimeError(f"OpenAI TTS 请求失败: HTTP {resp.status_code} {resp.text[:200]}")
            with open(output_path, "wb") as f:
                f.write(resp.content)

        elif provider == "volcengine":
            import httpx, json as _json
            endpoint = f"{tts_base_url.rstrip('/')}/api/v1/tts"
            headers = {"Authorization": f"Bearer;{volc_token}", "Content-Type": "application/json"}
            body = {
                "app": {"appid": volc_app_id, "token": volc_token, "cluster": volc_cluster},
                "user": {"uid": "smartclip"},
                "audio": {"voice_type": voice, "encoding": ext, "rate": 24000},
                "request": {"reqid": uuid.uuid4().hex, "text": req.text,
                             "text_type": "plain", "operation": "query"}
            }
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(endpoint, headers=headers, json=body)
            data = resp.json()
            audio_b64 = _get_nested(data, "data")
            if not audio_b64:
                raise RuntimeError(f"火山引擎 TTS 响应异常: {str(data)[:300]}")
            import base64
            with open(output_path, "wb") as f:
                f.write(base64.b64decode(audio_b64))

        elif provider == "gpt-sovits":
            import httpx
            params = {
                "refer_wav_path": gsv_ref_audio,
                "prompt_text": gsv_ref_text,
                "prompt_language": gsv_lang,
                "text": req.text,
                "text_language": gsv_lang,
            }
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.get(tts_base_url.rstrip("/"), params=params)
            if resp.status_code != 200:
                raise RuntimeError(f"GPT-SoVITS 请求失败: HTTP {resp.status_code}")
            with open(output_path, "wb") as f:
                f.write(resp.content)

        elif provider == "index-tts":
            import httpx
            endpoint = f"{tts_base_url.rstrip('/')}/run/predict"
            body = {"data": [req.text, index_ref_audio]}
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(endpoint, json=body)
            data = resp.json()
            # Gradio 返回 {"data": [{"url": "..."}]} 或 {"data": ["http://..."]}
            audio_url = _get_nested(data, "data.0.url") or _get_nested(data, "data.0")
            if not audio_url:
                raise RuntimeError(f"IndexTTS 响应异常: {str(data)[:300]}")
            async with httpx.AsyncClient(timeout=60) as client:
                audio_resp = await client.get(audio_url)
            with open(output_path, "wb") as f:
                f.write(audio_resp.content)

        elif provider == "custom-http":
            await _do_custom_http(
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
