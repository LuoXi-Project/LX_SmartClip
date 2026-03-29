import os
import logging
import httpx
from app.core.asr.base import IASR
from app.core.retry import retry_sync

logger = logging.getLogger(__name__)

# 基础超时（秒）+ 每 MB 追加的秒数，确保大文件不超时
_BASE_TIMEOUT = 60
_SECONDS_PER_MB = 30


def _calc_timeout(audio_path: str) -> float:
    """根据音频文件大小动态计算超时时长（秒）"""
    try:
        size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    except OSError:
        size_mb = 0
    timeout = _BASE_TIMEOUT + size_mb * _SECONDS_PER_MB
    logger.debug("ASR 超时设置: %.1f 秒 (文件 %.2f MB)", timeout, size_mb)
    return timeout


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
        # timeout=None 让每次请求自行传入动态超时，不在客户端层面限制
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=None)
        logger.info("初始化 OpenAI ASR: base_url=%s, model=%s", base_url, model)

    def transcribe(self, audio_path: str) -> str:
        """
        通过 OpenAI Whisper API 转写音频文件，超时时长根据文件大小自动计算。

        Args:
            audio_path: 音频文件路径

        Returns:
            转写后的文本
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        timeout = _calc_timeout(audio_path)
        logger.info("开始 OpenAI ASR 转写: %s (超时 %.0fs)", audio_path, timeout)

        def _call_api():
            with open(audio_path, "rb") as f:
                return self.client.audio.transcriptions.create(
                    model=self.model,
                    file=f,
                    language=self.language,
                    timeout=httpx.Timeout(timeout, connect=10),
                )

        try:
            response = retry_sync(_call_api)
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
