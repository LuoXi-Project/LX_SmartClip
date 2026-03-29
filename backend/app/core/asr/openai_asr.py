import os
import logging
import tempfile
from app.core.asr.base import IASR

logger = logging.getLogger(__name__)


class OpenAIASR(IASR):
    """OpenAI 兼容语音识别实现（支持 Whisper API 及兼容接口）"""

    def __init__(self, base_url: str, api_key: str, model: str = "whisper-1", language: str = "zh"):
        """
        初始化 OpenAI ASR
        
        Args:
            base_url: API 地址（如 https://api.openai.com/v1）
            api_key:  API 密钥
            model:    模型名称（默认 whisper-1）
            language: 语言代码（默认 zh）
        """
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("请安装 openai: pip install openai")

        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.language = language
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        logger.info("初始化 OpenAI ASR: base_url=%s, model=%s", base_url, model)

    def transcribe(self, audio_path: str) -> str:
        """
        通过 OpenAI Whisper API 转写音频文件
        
        Args:
            audio_path: 音频文件路径
            
        Returns:
            转写后的文本
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        logger.info("开始 OpenAI ASR 转写: %s", audio_path)
        try:
            with open(audio_path, "rb") as f:
                response = self.client.audio.transcriptions.create(
                    model=self.model,
                    file=f,
                    language=self.language,
                )
            text = response.text.strip()
            logger.info("OpenAI ASR 转写成功: %d 个字符", len(text))
            return text
        except Exception as e:
            logger.error("OpenAI ASR 转写失败: %s", e)
            raise RuntimeError(f"OpenAI ASR 转写失败: {e}")

    def get_model_info(self) -> dict:
        """获取模型信息"""
        return {
            "provider": "openai-asr",
            "base_url": self.base_url,
            "model": self.model,
            "language": self.language,
        }
