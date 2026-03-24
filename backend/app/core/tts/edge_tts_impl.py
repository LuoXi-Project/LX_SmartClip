import asyncio
import logging
from typing import Optional

import edge_tts

from .base import ITTS

logger = logging.getLogger(__name__)

# 默认中文女声
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"


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

        logger.info("TTS 合成: voice=%s rate=%s volume=%s text_len=%d", _voice, _rate, _volume, len(text))

        communicate = edge_tts.Communicate(text=text, voice=_voice, rate=_rate, volume=_volume)
        await communicate.save(output_path)
        logger.info("TTS 完成: %s", output_path)
        return output_path

    async def list_voices(self, locale: Optional[str] = None) -> list[dict]:
        voices_raw = await edge_tts.list_voices()
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
