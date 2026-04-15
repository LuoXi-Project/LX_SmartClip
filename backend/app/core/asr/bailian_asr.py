import logging
import os
from typing import Any

import requests

from app.core.asr.base import IASR
from app.core.asr.types import ASRSegment, ASRTranscript
from app.core.retry import retry_sync

logger = logging.getLogger(__name__)


def _ms_to_sec(v: Any) -> float | None:
    try:
        return float(v) / 1000.0
    except (TypeError, ValueError):
        return None


def _extract_sentences(item: dict[str, Any]) -> list[ASRSegment]:
    out: list[ASRSegment] = []
    for s in item.get("sentences") or []:
        t = (s.get("text") or "").strip()
        if not t:
            continue
        st = _ms_to_sec(s.get("begin_time"))
        ed = _ms_to_sec(s.get("end_time"))
        if st is None or ed is None:
            continue
        out.append(ASRSegment(start=st, end=ed, text=t))
    return out


def _collect_items(result_json: dict[str, Any]) -> list[dict[str, Any]]:
    # 常见返回：{"transcripts":[...]}；也兼容扁平结构
    trs = result_json.get("transcripts")
    if isinstance(trs, list) and trs:
        return [x for x in trs if isinstance(x, dict)]
    return [result_json]


def _merge_text(items: list[dict[str, Any]], fallback_segments: list[ASRSegment]) -> str:
    texts: list[str] = []
    for it in items:
        t = (it.get("transcript") or "").strip()
        if t:
            texts.append(t)
    if texts:
        return "\n".join(texts)
    if fallback_segments:
        return " ".join(s.text for s in fallback_segments).strip()
    return ""


class BailianASR(IASR):
    """阿里云百炼 DashScope 异步转写实现（fun-asr 等）。"""

    def __init__(
        self,
        base_url: str = "https://dashscope.aliyuncs.com/api/v1",
        api_key: str = "",
        model: str = "fun-asr",
        language: str = "",
    ):
        self.base_url = (base_url or "").strip() or "https://dashscope.aliyuncs.com/api/v1"
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip() or "fun-asr"
        self.language = (language or "").strip()
        if not self.api_key:
            raise ValueError("百炼 ASR 需要配置 API Key")
        logger.info("初始化百炼 ASR: base_url=%s, model=%s", self.base_url, self.model)

    def transcribe_detailed(self, audio_path: str) -> ASRTranscript:
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")
        try:
            import dashscope
            from dashscope.audio.asr import Transcription
        except ImportError as e:
            raise ImportError("请安装 dashscope: pip install dashscope") from e

        dashscope.base_http_api_url = self.base_url
        dashscope.api_key = self.api_key

        language_hints = [self.language] if self.language else None
        logger.info("开始百炼 ASR 转写: %s", audio_path)

        def _run_task():
            kwargs: dict[str, Any] = {
                "model": self.model,
                "file_urls": [f"file://{os.path.abspath(audio_path)}"],
            }
            if language_hints:
                kwargs["language_hints"] = language_hints

            task_resp = Transcription.async_call(**kwargs)
            task_id = (getattr(task_resp, "output", {}) or {}).get("task_id")
            if not task_id:
                raise RuntimeError(f"创建百炼转写任务失败: {task_resp}")
            resp = Transcription.wait(task=task_id)
            status_code = getattr(resp, "status_code", None)
            if status_code != 200:
                msg = (getattr(resp, "output", {}) or {}).get("message") or getattr(resp, "message", "")
                raise RuntimeError(f"百炼转写任务失败: status={status_code}, msg={msg}")
            return resp

        resp = retry_sync(_run_task)
        output = getattr(resp, "output", {}) or {}
        results = output.get("results") or []
        if not results:
            return ASRTranscript(text="", segments=())

        all_segments: list[ASRSegment] = []
        text_parts: list[str] = []
        for r in results:
            if (r or {}).get("subtask_status") != "SUCCEEDED":
                code = (r or {}).get("code")
                msg = (r or {}).get("message") or "subtask failed"
                logger.warning("百炼子任务失败: code=%s, msg=%s", code, msg)
                continue
            tr_url = (r or {}).get("transcription_url")
            if not tr_url:
                continue

            def _fetch():
                rs = requests.get(tr_url, timeout=60)
                rs.raise_for_status()
                return rs.json()

            data = retry_sync(_fetch)
            items = _collect_items(data if isinstance(data, dict) else {})
            segs_for_file: list[ASRSegment] = []
            for item in items:
                segs_for_file.extend(_extract_sentences(item))
            merged_text = _merge_text(items, segs_for_file)
            if merged_text:
                text_parts.append(merged_text)
            all_segments.extend(segs_for_file)

        text = "\n".join(t for t in text_parts if t).strip()
        logger.info("百炼 ASR 转写成功: %d 字, %d 个时间片段", len(text), len(all_segments))
        return ASRTranscript(text=text, segments=tuple(all_segments))

    def get_model_info(self) -> dict:
        return {
            "provider": "bailian-asr",
            "base_url": self.base_url,
            "model": self.model,
            "language": self.language or None,
        }
