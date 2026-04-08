import os
import logging
from app.core.asr.base import IASR
from app.core.asr.types import ASRSegment, ASRTranscript
from app.core.retry import retry_sync

logger = logging.getLogger(__name__)


def _segments_from_whisper_result(result: dict) -> tuple[ASRSegment, ...]:
    raw = result.get("segments") or []
    out: list[ASRSegment] = []
    for seg in raw:
        try:
            t = (seg.get("text") or "").strip()
            if not t:
                continue
            out.append(
                ASRSegment(
                    start=float(seg["start"]),
                    end=float(seg["end"]),
                    text=t,
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.debug("跳过异常 segment 项: %s", e)
            continue
    return tuple(out)


class WhisperASR(IASR):
    """Whisper 语音识别实现"""

    def __init__(self, model_size: str = "base", device: str = "cpu", language: str | None = "zh"):
        """
        初始化 Whisper ASR

        Args:
            model_size: 模型大小（tiny, base, small, medium, large）
            device: 计算设备（cpu, cuda）
            language: Whisper 语言代码（默认 zh）；None 或空字符串表示自动检测
        """
        try:
            import whisper
        except ImportError:
            raise ImportError("请安装 openai-whisper: pip install openai-whisper")

        self.model_size = model_size
        self.device = device
        self._language = language
        self.whisper = whisper

        logger.info(f"加载 Whisper 模型: {model_size} (device={device})")
        self.model = whisper.load_model(model_size, device=device)
        logger.info("Whisper 模型加载成功")

    def transcribe_detailed(self, audio_path: str) -> ASRTranscript:
        """
        转写音频，返回全文与 segment 级时间轴（相对本音频文件）。
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        logger.info(f"开始转写音频: {audio_path}")

        def _call_whisper():
            lang = None if self._language is None else str(self._language).strip()
            if not lang:
                return self.model.transcribe(audio_path)
            return self.model.transcribe(audio_path, language=lang)

        try:
            result = retry_sync(_call_whisper)
            text = (result.get("text") or "").strip()
            segments = _segments_from_whisper_result(result)
            logger.info(
                "音频转写成功: %d 字, %d 个时间片段",
                len(text),
                len(segments),
            )
            return ASRTranscript(text=text, segments=segments)
        except Exception as e:
            logger.error(f"音频转写失败: {e}")
            raise RuntimeError(f"音频转写失败: {str(e)}")

    def get_model_info(self) -> dict:
        """获取模型信息"""
        lang_out = None if self._language is None else str(self._language).strip()
        return {
            "provider": "openai-whisper",
            "model_size": self.model_size,
            "device": self.device,
            "language": lang_out or None,
        }
