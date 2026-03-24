from abc import ABC, abstractmethod
from typing import Optional


class ITTS(ABC):
    """TTS（文字转语音）抽象接口"""

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        output_path: str,
        voice: Optional[str] = None,
        rate: Optional[str] = None,
        volume: Optional[str] = None,
    ) -> str:
        """
        将文本合成为语音文件

        Args:
            text:        待合成文本
            output_path: 输出文件路径（含扩展名，如 .mp3）
            voice:       语音角色，None 时使用默认值
            rate:        语速，格式如 "+0%" / "-20%"
            volume:      音量，格式如 "+0%" / "+10%"

        Returns:
            实际写出的文件路径
        """
        pass

    @abstractmethod
    async def list_voices(self, locale: Optional[str] = None) -> list[dict]:
        """
        获取可用语音列表

        Args:
            locale: 按地区过滤，如 "zh-CN"，None 表示返回全部

        Returns:
            [{ "name": str, "locale": str, "gender": str, "friendly_name": str }, ...]
        """
        pass
