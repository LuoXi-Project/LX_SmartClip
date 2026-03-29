import os
import logging
from typing import Optional
from app.core.asr.base import IASR
from app.core.retry import retry_sync

logger = logging.getLogger(__name__)


class WhisperASR(IASR):
    """Whisper 语音识别实现"""

    def __init__(self, model_size: str = "base", device: str = "cpu"):
        """
        初始化 Whisper ASR

        Args:
            model_size: 模型大小（tiny, base, small, medium, large）
            device: 计算设备（cpu, cuda）
        """
        try:
            import whisper
        except ImportError:
            raise ImportError("请安装 openai-whisper: pip install openai-whisper")

        self.model_size = model_size
        self.device = device
        self.whisper = whisper

        logger.info(f"加载 Whisper 模型: {model_size} (device={device})")
        self.model = whisper.load_model(model_size, device=device)
        logger.info("Whisper 模型加载成功")

    def transcribe(self, audio_path: str) -> str:
        """
        转写音频文件为文本

        Args:
            audio_path: 音频文件路径

        Returns:
            转写后的文本
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        logger.info(f"开始转写音频: {audio_path}")

        def _call_whisper():
            result = self.model.transcribe(audio_path, language="zh")
            return result["text"].strip()

        try:
            text = retry_sync(_call_whisper)
            logger.info(f"音频转写成功: {len(text)} 个字符")
            return text
        except Exception as e:
            logger.error(f"音频转写失败: {e}")
            raise RuntimeError(f"音频转写失败: {str(e)}")

    def get_model_info(self) -> dict:
        """获取模型信息"""
        return {
            "provider": "openai-whisper",
            "model_size": self.model_size,
            "device": self.device,
            "language": "zh",
        }
