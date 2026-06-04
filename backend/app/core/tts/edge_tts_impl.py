import logging
import os
from typing import Optional

import edge_tts

from .base import ITTS
from app.core.retry import retry_async

logger = logging.getLogger(__name__)

# 默认中文女声
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
_EDGE_CONNECT_TIMEOUT = 30
_EDGE_RECEIVE_TIMEOUT = 120
_EDGE_RETRIES = 5


def _edge_tts_proxy() -> Optional[str]:
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    return None


class EdgeTTS(ITTS):
    """基于 edge-tts 的 TTS 实现（微软 Edge 在线 TTS）"""

    def __init__(
        self,
        default_voice: str = DEFAULT_VOICE,
        default_rate: str = "+0%",
        default_volume: str = "+0%",
    ):
        self.default_voice = default_voice
        self.default_rate = default_rate
        self.default_volume = default_volume

    async def synthesize(
        self,
        text: str,
        output_path: str,
        voice: Optional[str] = None,
        rate: Optional[str] = None,
        volume: Optional[str] = None,
    ) -> str:
        _voice = voice or self.default_voice
        _rate = rate or self.default_rate
        _volume = volume or self.default_volume

        logger.info("TTS 合成: 说话人=%s 语速=%s 音量=%s 合成文本长度=%d 合成内容: %s", _voice, _rate, _volume, len(text), text[:100])

        proxy = _edge_tts_proxy()

        async def _call_tts():
            communicate = edge_tts.Communicate(
                text=text,
                voice=_voice,
                rate=_rate,
                volume=_volume,
                proxy=proxy,
                connect_timeout=_EDGE_CONNECT_TIMEOUT,
                receive_timeout=_EDGE_RECEIVE_TIMEOUT,
            )
            await communicate.save(output_path)

        await retry_async(_call_tts, retries=_EDGE_RETRIES)
        logger.info("TTS 完成: %s", output_path)
        return output_path

    async def list_voices(self, locale: Optional[str] = None) -> list[dict]:
        async def _fetch():
            return await edge_tts.list_voices()

        voices_raw = await retry_async(_fetch)
        result = []
        for v in voices_raw:
            if locale and not v["Locale"].startswith(locale):
                continue
            result.append(
                {
                    "name": v["ShortName"],
                    "locale": v["Locale"],
                    "gender": v["Gender"],
                    "friendly_name": v.get("FriendlyName", v["ShortName"]),
                }
            )
        return result
