"""
浏览器录音 → ASR 写入文案；可选 LLM 根据「字段意图」润色念稿或执行口述任务后再填入。

临时文件落在 storage/_voice_input_ring/，固定槽位数循环覆盖。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Literal

import aiosqlite
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.asr import get_asr
from app.core.blocking_pool import run_heavy
from app.core.llm import LLMClient, LLMConfig
from app.db.database import DB_PATH
from app.utils.ffmpeg_utils import extract_audio_for_asr
from app.utils.paths import ensure_storage_subpath

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])

RING_SLOTS = 8
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024

_ring_dir: str | None = None
_ring_lock = asyncio.Lock()
_ring_seq = 0


def _ring_base_dir() -> str:
    global _ring_dir
    if _ring_dir is None:
        _ring_dir = ensure_storage_subpath("_voice_input_ring")
    return _ring_dir


async def _next_slot() -> int:
    global _ring_seq
    async with _ring_lock:
        s = _ring_seq % RING_SLOTS
        _ring_seq += 1
        return s


async def _read_config(db: aiosqlite.Connection, key: str, default: str = "") -> str:
    """与 `LLMConfig.read_config` 一致：默认连接未设 `row_factory` 时 `fetchone()` 为元组。"""
    cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = await cursor.fetchone()
    if not row:
        return default
    v = row[0]
    return default if v is None else str(v)


def _strip_md_fences(s: str) -> str:
    t = (s or "").strip()
    if not t.startswith("```"):
        return t
    lines = t.split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


class VoiceRefineRequest(BaseModel):
    transcript: str = Field(..., min_length=1, max_length=32000)
    intent: str = Field(..., min_length=1, max_length=2000)
    current_value: str = Field("", max_length=32000)
    mode: Literal["replace", "append"] = "replace"


@router.post("/transcribe")
async def transcribe_voice(
    file: UploadFile = File(..., description="录音文件（webm/wav/m4a 等，FFmpeg 可解码即可）"),
):
    """
    上传短录音 → 转 16k mono WAV（槽位循环覆盖）→ 使用系统 ASR 配置转写。
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="空文件")
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail=f"文件过大（>{_MAX_UPLOAD_BYTES // (1024 * 1024)}MB）")

    slot = await _next_slot()
    base = _ring_base_dir()
    raw_ext = os.path.splitext((file.filename or "").strip())[1].lower() or ".webm"
    if raw_ext not in (".webm", ".wav", ".mp3", ".m4a", ".ogg", ".opus", ".flac", ".aac"):
        raw_ext = ".webm"
    raw_path = os.path.join(base, f"slot_{slot}_raw{raw_ext}")
    wav_path = os.path.join(base, f"slot_{slot}.wav")

    def _write_raw() -> None:
        os.makedirs(os.path.dirname(raw_path), exist_ok=True)
        with open(raw_path, "wb") as f:
            f.write(raw)

    await asyncio.to_thread(_write_raw)

    try:
        await run_heavy(extract_audio_for_asr, raw_path, wav_path, overwrite=True)
    except Exception as e:
        logger.warning("语音转 WAV 失败，尝试直接用原文件 ASR: %s", e)
        wav_path = raw_path

    async with aiosqlite.connect(DB_PATH) as db:
        asr_provider = await _read_config(db, "asr_provider", "whisper")
        model_size = await _read_config(db, "asr_model", "small")
        asr_base_url = await _read_config(db, "asr_base_url", "https://api.openai.com/v1")
        asr_api_key = await _read_config(db, "asr_api_key", "")
        asr_openai_model = await _read_config(db, "asr_openai_model", "whisper-1")
        asr_language = (await _read_config(db, "asr_language", "zh") or "").strip()

    try:
        asr_instance = get_asr(
            provider=asr_provider,
            model_size=model_size,
            base_url=asr_base_url,
            api_key=asr_api_key,
            model=asr_openai_model,
            language=asr_language,
        )
    except Exception as e:
        logger.error("初始化 ASR 失败: %s", e)
        raise HTTPException(status_code=500, detail=f"ASR 初始化失败: {e}") from e

    try:
        tr = await run_heavy(asr_instance.transcribe_detailed, wav_path)
    except Exception as e:
        logger.error("语音 ASR 失败: %s", e)
        raise HTTPException(status_code=502, detail=f"语音识别失败: {e}") from e

    text = (tr.text or "").strip()
    seg_dicts: list[dict[str, Any]] = list(tr.segments_as_dicts())

    return {
        "text": text,
        "segments": seg_dicts,
        "slot": slot,
        "provider": asr_provider,
    }


@router.post("/refine")
async def refine_transcript(req: VoiceRefineRequest):
    """
    将 ASR 原文与「该输入框用途」交给 LLM，产出应写入框内的最终文案：
    口述为念稿时做润色与纠错；口述为任务指令（如「帮我写个故事」）时直接生成成果正文。
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cfg = await LLMConfig.get_llm_params_with_defaults(
                db,
                base_url_key="llm_base_url",
                api_key_key="llm_api_key",
                model_key="llm_model",
                fallback_model_key="vlm_model",
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    cur = (req.current_value or "").strip()
    mode_hint = (
        "若 mode=append：在保留「当前框内已有内容」的前提下，只输出要追加写入的一段；不要重复已有全文。"
        "若口述是在下任务（续写、扩写、翻译、总结等），只输出新增片段本身。"
        if req.mode == "append"
        else "输出应写入输入框的完整最终文案（可覆盖「当前框内已有内容」）。"
        "若口述是在下任务（创作故事、写标题、总结、翻译、改写语气等），输出任务完成后的正文，而不是复述任务句。"
    )
    user_block = (
        f"【该输入框用途说明】\n{req.intent.strip()}\n\n"
        f"【ASR 口述原文】\n{req.transcript.strip()}\n\n"
        f"【当前框内已有内容】\n{cur or '（空）'}\n\n"
        f"【填入策略】\nmode={req.mode}\n{mode_hint}\n\n"
        "请先判断：口述更像「用户念出要放进框里的字」还是「让用户完成任务的一句话/一段指令」。\n"
        "- 念稿：去口头禅与重复、修正明显口误与 ASR 错字，使表述贴合该输入框用途；对用户陈述的事实勿编造、勿杜撰。\n"
        "- 任务指令：直接生成应出现在框内的成果（例如「帮我写个故事」→输出故事正文；「用三句话概括」→输出概括）。\n"
        "长度与体裁以该输入框用途为准，避免冗长到不像表单填写。\n\n"
        "请只输出要填入输入框的纯文本，不要解释、不要前后缀、不要用 Markdown 代码块包裹。"
    )

    llm = LLMClient(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        temperature=min(0.65, float(cfg.get("temperature", 0.7) or 0.7)),
        max_tokens=min(65536, int(cfg.get("max_tokens", 2048) or 2048)),
        timeout=600.0,
    )
    messages = [
        {
            "role": "system",
            "content": (
                "你是中文界面里的「语音填表助手」。用户通过麦克风口述，系统先做语音识别得到一段文字。"
                "你要结合「该输入框用途」理解这段文字：它可能是用户念出的稿，也可能是让用户完成某件事的指令。"
                "若是念稿：整理成适合该控件的文案，去口头禅与重复、修正口误与识别错字；对用户当作事实陈述的内容不要捏造。"
                "若是指令（如创作、续写、总结、翻译、改写、起名等）：直接产出应写入输入框的成果正文，不要只复述任务句、不要把「帮我写…」原样当作最终内容。"
                "输出只能是最终填入框内的文本本身。"
            ),
        },
        {"role": "user", "content": user_block},
    ]
    try:
        raw = await llm.chat(
            messages,
            temperature=min(0.55, float(cfg.get("temperature", 0.7) or 0.7)),
            max_tokens=min(65536, int(cfg.get("max_tokens", 2048) or 2048)),
        )
    except Exception as e:
        logger.error("voice refine LLM 失败: %s", e)
        raise HTTPException(status_code=502, detail=f"LLM 整理失败: {e}") from e

    out = _strip_md_fences(raw).strip()
    if not out:
        raise HTTPException(status_code=502, detail="LLM 返回为空")
    return {"text": out}
