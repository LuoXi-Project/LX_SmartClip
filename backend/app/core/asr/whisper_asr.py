import os
import logging
from app.core.asr.base import IASR
from app.core.asr.types import ASRSegment, ASRTranscript
from app.core.retry import retry_sync
from app.utils.whisper_ffmpeg import patch_whisper_ffmpeg, require_ffmpeg_executable

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


def _resolve_whisper_device(requested: str | None = None) -> str:
    """
    解析 Whisper 运行设备：默认 auto（有 CUDA 则用 GPU，否则 CPU）。
    可通过参数或环境变量 SMARTCLIP_WHISPER_DEVICE=auto|cuda|cpu 覆盖。
    """
    raw = (requested or os.environ.get("SMARTCLIP_WHISPER_DEVICE", "auto") or "auto").strip().lower()
    if raw in ("cuda", "gpu"):
        return "cuda"
    if raw == "cpu":
        return "cpu"

    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception as e:
        logger.debug("CUDA 不可用，使用 CPU: %s", e)
    return "cpu"


def _load_whisper_model(whisper_mod, model_size: str, device: str):
    try:
        return whisper_mod.load_model(model_size, device=device), device
    except Exception as e:
        if device != "cuda":
            raise
        logger.warning("Whisper CUDA 加载失败，回退 CPU: %s", e)
        return whisper_mod.load_model(model_size, device="cpu"), "cpu"


class WhisperASR(IASR):
    """Whisper 语音识别实现"""

    def __init__(self, model_size: str = "small", device: str | None = "auto", language: str | None = "zh"):
        """
        初始化 Whisper ASR

        Args:
            model_size: 模型大小（tiny, base, small, medium, large, large-v2, large-v3）
            device: 计算设备（auto, cpu, cuda）；auto 时有 GPU 用 GPU，否则 CPU
            language: Whisper 语言代码（默认 zh）；None 或空字符串表示自动检测
        """
        try:
            import whisper
        except ImportError:
            raise ImportError("请安装 openai-whisper: pip install openai-whisper")

        require_ffmpeg_executable()
        patch_whisper_ffmpeg()

        self.model_size = model_size
        self.device = _resolve_whisper_device(device)
        self._language = language
        self.whisper = whisper

        logger.info("加载 Whisper 模型: %s (device=%s)", model_size, self.device)
        self.model, self.device = _load_whisper_model(whisper, model_size, self.device)
        logger.info("Whisper 模型加载成功 (device=%s)", self.device)

    def transcribe_detailed(self, audio_path: str) -> ASRTranscript:
        """
        转写音频，返回全文与 segment 级时间轴（相对本音频文件）。
        """
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        logger.info("开始转写音频: %s", audio_path)

        def _call_whisper():
            lang = None if self._language is None else str(self._language).strip()
            kwargs: dict = {
                "fp16": self.device == "cuda",
                "temperature": 0,
                "beam_size": 5,
                "best_of": 5,
            }
            if lang:
                kwargs["language"] = lang
            return self.model.transcribe(audio_path, **kwargs)

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
            logger.error("音频转写失败: %s", e)
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
