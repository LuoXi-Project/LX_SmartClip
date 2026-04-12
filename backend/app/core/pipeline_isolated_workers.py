"""
流水线「可强杀」子进程任务：均为模块顶层函数，供 multiprocessing spawn 调用。

与 process_pipeline 中的重试/超时配合：超时时父进程 terminate/kill 子进程，释放占用。
"""
from __future__ import annotations

from typing import Any


def isolated_extract_frames(
    video_id: str,
    clip_path: str,
    frame_fps: float,
    frame_target_pixels: int,
) -> list[str]:
    from app.api.process_shared import get_splitter

    return list(get_splitter(video_id).extract_frames(clip_path, frame_fps, frame_target_pixels) or [])


def isolated_extract_audio(video_id: str, clip_path: str, overwrite: bool) -> str:
    from app.api.process_shared import get_splitter

    return get_splitter(video_id).extract_audio(clip_path, overwrite)


def isolated_openai_asr_clip(
    video_id: str,
    clip_path: str,
    overwrite: bool,
    base_url: str,
    api_key: str,
    model: str,
    language: str,
) -> dict[str, Any]:
    from app.api.process_shared import get_splitter
    from app.core.asr.openai_asr import OpenAIASR

    audio_path = get_splitter(video_id).extract_audio(clip_path, overwrite)
    asr = OpenAIASR(base_url, api_key, model, language)
    tr = asr.transcribe_detailed(audio_path)
    return {"text": tr.text, "segments": [s.to_dict() for s in tr.segments]}


def isolated_whisper_asr_clip(
    video_id: str,
    clip_path: str,
    overwrite: bool,
    model_size: str,
    language: str | None,
) -> dict[str, Any]:
    from app.api.process_shared import get_splitter
    from app.core.asr.whisper_asr import WhisperASR

    audio_path = get_splitter(video_id).extract_audio(clip_path, overwrite)
    lang = (language or "").strip() or None
    asr = WhisperASR(model_size, language=lang)
    tr = asr.transcribe_detailed(audio_path)
    return {"text": tr.text, "segments": [s.to_dict() for s in tr.segments]}


def isolated_vlm_generate(
    base_url: str,
    model: str,
    api_key: str,
    frame_paths: list[str],
    frame_times_sec: list[float] | None,
    max_images: int,
    context_length: int,
) -> dict[str, Any]:
    from app.core.metrics.token_usage import TokenUsage
    from app.core.vlm.openai_vlm import OpenAIVLM

    vlm = OpenAIVLM(base_url, model, api_key)
    box: dict[str, Any] = {"usage": None, "est": 0}

    def on_usage(u, est: int = 0):
        box["usage"] = u
        box["est"] = int(est or 0)

    desc = vlm.generate_description(
        list(frame_paths),
        list(frame_times_sec) if frame_times_sec is not None else None,
        max_images,
        context_length,
        on_usage=on_usage,
    )
    u = box.get("usage")
    u_dict = u.to_dict() if isinstance(u, TokenUsage) else None
    return {"description": (desc or "").strip(), "usage": u_dict, "est": int(box.get("est") or 0)}


def isolated_embed_text(base_url: str, api_key: str, model: str, text: str) -> dict[str, Any]:
    from app.core.embedder import Embedder
    from app.core.metrics.token_usage import TokenUsage

    emb = Embedder(base_url, api_key, model)
    box: dict[str, Any] = {}

    def on_usage(u):
        box["usage"] = u

    try:
        vec = emb.embed(text, on_usage=on_usage)
        u = box.get("usage")
        u_dict = u.to_dict() if isinstance(u, TokenUsage) else None
        return {"embedding": vec, "usage": u_dict}
    finally:
        # 避免短生命周期子进程在 HTTP 连接清理阶段异常挂起
        try:
            emb.close()
        except Exception:
            pass
