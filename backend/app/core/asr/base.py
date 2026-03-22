from abc import ABC, abstractmethod
from typing import Optional


class IASR(ABC):
    """ASR（自动语音识别）抽象接口"""

    @abstractmethod
    def transcribe(self, audio_path: str) -> str:
        """
        转写音频文件为文本
        
        Args:
            audio_path: 音频文件路径
            
        Returns:
            转写后的文本
        """
        pass

    @abstractmethod
    def get_model_info(self) -> dict:
        """获取模型信息"""
        pass
