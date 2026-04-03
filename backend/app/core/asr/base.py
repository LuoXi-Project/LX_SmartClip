from abc import ABC, abstractmethod

from app.core.asr.types import ASRTranscript


class IASR(ABC):
    """ASR（自动语音识别）抽象接口"""

    def transcribe(self, audio_path: str) -> str:
        """
        转写音频文件为纯文本（等价于 transcribe_detailed().text）。
        """
        return self.transcribe_detailed(audio_path).text

    @abstractmethod
    def transcribe_detailed(self, audio_path: str) -> ASRTranscript:
        """
        转写音频，返回全文 + 带起止时间的片段（相对本段音频文件 0 秒）。

        片段粒度由底层模型决定（Whisper segment / OpenAI verbose_json），
        可用于静音区间检测、句级快剪等。
        """
        pass

    @abstractmethod
    def get_model_info(self) -> dict:
        """获取模型信息"""
        pass
