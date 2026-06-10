"""素材处理流水线：ASR / VLM / Embedding 服务初始化。"""
from __future__ import annotations

from app.core.embedder import Embedder
from app.core.vector_db.faiss_db import FaissVectorDB
from app.db.database import DB_PATH

from .process_pipeline_context import PipelineContext
from .process_shared import logger


async def init_pipeline_services(ctx: PipelineContext) -> None:
    """初始化 ASR / VLM / Embedding 实例，并更新 ctx.do_* 开关。"""
    loop = ctx.loop
    reporter = ctx.reporter

    if ctx.do_asr:
        try:
            if ctx.asr_provider in ("openai", "bailian"):
                provider_name = "OpenAI ASR" if ctx.asr_provider == "openai" else "百炼 ASR"
                await reporter.send(
                    "asr",
                    "running",
                    f"使用 {provider_name} ({ctx.asr_openai_model}) 开始语音识别（子进程，可强杀超时）...",
                )
                if not (ctx.asr_api_key or "").strip():
                    ctx.do_asr = False
                    await reporter.send("asr", "error", f"{provider_name} 未配置 API Key")
                else:
                    ctx.asr_instance = None
            else:
                if ctx.whisper_inprocess_transcribe:
                    await reporter.send(
                        "asr",
                        "running",
                        f"加载 Whisper ({ctx.asr_model}) 主进程线程识别（仅提音频走可杀子进程）...",
                    )
                    from app.core.asr.whisper_asr import WhisperASR

                    ctx.asr_instance = await loop.run_in_executor(
                        None,
                        lambda: WhisperASR(ctx.asr_model, language=ctx.asr_language or None),
                    )
                    logger.warning(
                        "SMARTCLIP_WHISPER_INPROCESS_TRANSCRIBE=1：Whisper 转写在主进程线程中执行，wait_for 超时后仍可能长期占用线程"
                    )
                else:
                    await reporter.send(
                        "asr",
                        "running",
                        f"使用 Whisper ({ctx.asr_model}) 子进程识别（可强杀超时，每片段会加载模型）...",
                    )
                    ctx.asr_instance = None
                    logger.info(
                        "本地 Whisper 每片段在独立子进程中识别；若需单进程复用模型可设 SMARTCLIP_WHISPER_INPROCESS_TRANSCRIBE=1（更快但超时有线程滞留风险）"
                    )
        except Exception as e:
            ctx.do_asr = False
            await reporter.send("asr", "error", f"ASR 初始化失败: {e}")
    else:
        await reporter.send("asr", "skip", "跳过语音识别")

    if ctx.do_vlm:
        if not ctx.vlm_api_key:
            ctx.do_vlm = False
            await reporter.send("vlm", "skip", "VLM API Key 未配置，跳过")
        else:
            await reporter.send("vlm", "running", f"使用 {ctx.vlm_model} 生成视觉描述...")
            try:
                from app.core.vlm.openai_vlm import OpenAIVLM

                ctx.vlm_instance = OpenAIVLM(
                    base_url=ctx.vlm_base_url,
                    model=ctx.vlm_model,
                    api_key=ctx.vlm_api_key,
                )
            except Exception as e:
                ctx.do_vlm = False
                await reporter.send("vlm", "error", f"VLM 初始化失败: {e}")
    else:
        await reporter.send("vlm", "skip", "跳过视觉描述")

    if ctx.do_embed:
        if not ctx.embedding_api_key:
            ctx.do_embed = False
            await reporter.send("embed", "skip", "Embedding API Key 未配置，跳过向量入库")
        else:
            mode = "主进程线程" if ctx.embed_inprocess else "子进程"
            await reporter.send(
                "embed",
                "running",
                f"开始生成 Embedding 并入库（{mode}，单片段超时 {int(ctx.embedding_timeout_sec)}s）...",
            )
            try:
                ctx.embedder = Embedder(
                    base_url=ctx.embedding_base_url,
                    api_key=ctx.embedding_api_key,
                    model=ctx.embedding_model,
                    request_timeout_sec=ctx.embedding_timeout_sec,
                    volc_output_dimensions=ctx.vector_dim,
                )
                ctx.vector_db = FaissVectorDB(db_path=DB_PATH, vector_dimension=ctx.vector_dim)
                if ctx.embed_inprocess:
                    logger.warning(
                        "SMARTCLIP_EMBED_INPROCESS=1：Embedding 在主进程线程执行；超时后线程可能继续运行直至底层请求返回"
                    )
            except Exception as e:
                ctx.do_embed = False
                await reporter.send("embed", "error", f"Embedding 初始化失败: {e}")
    else:
        await reporter.send("embed", "skip", "跳过向量入库")
