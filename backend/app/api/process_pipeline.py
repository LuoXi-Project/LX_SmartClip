import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from fastapi import HTTPException
from app.core.asr.types import ASRSegment, ASRTranscript
from app.core.asr.corrector import correct_transcript
from app.core.blocking_pool import run_heavy
from app.core.embedder import Embedder
from app.core.enricher import enrich_clip
from app.core.killable_subprocess import run_killable_target
from app.core.llm import LLMClient
from app.core.llm.config import LLMConfig
from app.core.metrics.token_usage import TokenAccumulator, TokenUsage
from app.core.splitter import StopRequested
from app.core.vector_db.faiss_db import FaissVectorDB
from app.core.vector_db.sub_texts import build_sub_texts, non_empty_subspaces
from app.db.database import DB_PATH, get_db_conn
from .process_db import (
    clear_clips_for_video,
    get_clips,
    get_video,
    insert_clip_to_db,
    read_config,
    set_video_status,
    update_clip_asr,
    update_clip_field,
)
from .process_shared import (
    ProcessCancelled,
    STEP_LABELS,
    cancel_event_for,
    check_cancel,
    get_splitter,
    logger,
    parse_positive_int,
)
from app.utils.logging_utils import stage_log

# 单片段单步（抽帧/ASR/VLM/Embedding）上限：短切片下一般远小于此值；超时则子进程 terminate/kill 或抛出后重试
PIPELINE_STEP_TIMEOUT_SEC = 600.0
# 共尝试次数：首次 + 3 次重试，仍失败则跳过该片段改步骤
PIPELINE_STEP_MAX_ATTEMPTS = 4
# 全流程总超时（秒）：默认 6 小时，避免极端情况下任务无限运行
PIPELINE_TOTAL_TIMEOUT_SEC = 6 * 60 * 60.0
# split 阶段超时（秒）：默认 2 小时
PIPELINE_SPLIT_TIMEOUT_SEC = 2 * 60 * 60.0
# 队列 put/join 与 worker 收尾等待超时（秒）。
# 注意：join 是「等待全部片段处理完」的兜底上限，不是单步处理时长——
# Whisper medium 每片段独立子进程加载模型时，30+ 片段的 ASR 可能超过 5 分钟，
# 过短会导致 join 超时把整条流水线判失败（曾出现 300s 误杀 31 片段任务）。
PIPELINE_QUEUE_TIMEOUT_SEC = 1800.0
PIPELINE_WORKERS_DRAIN_TIMEOUT_SEC = 600.0

# multiprocessing 子进程入口（app.core.pipeline_isolated_workers 内顶层函数）
_PIPELINE_ISOLATED = "app.core.pipeline_isolated_workers"

T = TypeVar("T")


def _transcript_from_payload(d: dict[str, Any]) -> ASRTranscript:
    segs: list[ASRSegment] = []
    for s in d.get("segments") or []:
        try:
            t = (s.get("text") or "").strip()
            if not t:
                continue
            segs.append(ASRSegment(start=float(s["start"]), end=float(s["end"]), text=t))
        except (KeyError, TypeError, ValueError):
            continue
    return ASRTranscript(text=(d.get("text") or "").strip(), segments=tuple(segs))


async def _step_with_timeout_retries(
    clip_id: str,
    step_label: str,
    run: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = PIPELINE_STEP_MAX_ATTEMPTS,
    timeout_sec: float = PIPELINE_STEP_TIMEOUT_SEC,
) -> T | None:
    """对单片段单步重试：单次超时/进程强杀由 run() 内 killable 任务抛出 TimeoutError。"""
    last_err: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await run()
        except asyncio.CancelledError:
            raise
        except ProcessCancelled:
            raise
        except TimeoutError as e:
            last_err = e
            logger.warning(
                "片段 %s %s 超时 (第 %d/%d 次, 限制 %.0fs)",
                clip_id,
                step_label,
                attempt,
                max_attempts,
                timeout_sec,
            )
        except Exception as e:
            last_err = e
            logger.warning(
                "片段 %s %s 失败 (第 %d/%d 次): %s",
                clip_id,
                step_label,
                attempt,
                max_attempts,
                e,
            )
        if attempt < max_attempts:
            await asyncio.sleep(min(2 ** (attempt - 1), 30))
    logger.error(
        "片段 %s %s 已达 %d 次尝试仍失败，跳过该步骤: %s",
        clip_id,
        step_label,
        max_attempts,
        last_err,
    )
    return None


async def run_pipeline(
    video_id: str,
    reporter,
    skip_steps: list = None,
    task_id: str | None = None,
    clip_ids_filter: frozenset[str] | None = None,
    embed_incremental: bool = False,
):
    """执行全素材处理（按片段流水线并发）：split -> (frames||asr) -> vlm -> embed

    clip_ids_filter: 仅在不重新切分时生效；只处理这些 clip id（须已通过 API 校验归属）。
    embed_incremental: 增量多向量化——仅补齐缺失子空间，已存在的子空间不重复 embed。
        供「预处理页面 → 继续拆维度向量化」使用，避免重跑时全量重 embed。"""
    skip_steps = skip_steps or []
    skip_cn = "、".join(STEP_LABELS.get(s, s) for s in skip_steps) if skip_steps else "无"
    stage_log(
        "预处理",
        f"开始处理视频 {video_id}（跳过: {skip_cn}）",
        status="running",
    )

    video = await get_video(video_id)
    if not video:
        logger.error("run_pipeline: video_id=%s 视频不存在", video_id)
        raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")

    splitter = get_splitter(video_id)

    cancel_event_for(video_id).clear()
    video_path = video["file_path"]
    await set_video_status(video_id, "processing")

    db = await get_db_conn()
    try:
        split_mode = await read_config(db, "split_mode", "scene")
        scene_threshold = float(await read_config(db, "scene_threshold", "0.4"))
        scene_min_scene_len = int(await read_config(db, "scene_min_scene_len", "30"))
        fixed_duration = float(await read_config(db, "fixed_duration", "10"))
        hybrid_max_segment_sec = float(await read_config(db, "hybrid_max_segment_sec", "60"))
        transcode_opts = {
            "clip_container": await read_config(db, "clip_container", "mp4"),
            "clip_vcodec": await read_config(db, "clip_vcodec", "libx264"),
            "clip_acodec": await read_config(db, "clip_acodec", "aac"),
            "clip_preset": await read_config(db, "clip_preset", "veryfast"),
            "clip_crf": await read_config(db, "clip_crf", "18"),
            "clip_video_bitrate_kbps": await read_config(db, "clip_video_bitrate_kbps", "0"),
            "clip_audio_bitrate_kbps": await read_config(db, "clip_audio_bitrate_kbps", "128"),
            "clip_g": await read_config(db, "clip_g", "48"),
            "clip_keyint_min": await read_config(db, "clip_keyint_min", "48"),
            "clip_sc_threshold": await read_config(db, "clip_sc_threshold", "0"),
            "clip_fps": await read_config(db, "clip_fps", "0"),
            "clip_scale_width": await read_config(db, "clip_scale_width", "0"),
            "clip_scale_height": await read_config(db, "clip_scale_height", "0"),
            "clip_pix_fmt": await read_config(db, "clip_pix_fmt", "yuv420p"),
            "cut_mode": await read_config(db, "cut_mode", "fast"),
            "stream_copy": await read_config(db, "stream_copy", "false"),
            "stream_copy_audio": await read_config(db, "stream_copy_audio", "false"),
            "split_max_workers": await read_config(db, "split_max_workers", "2"),
            "ffmpeg_threads_per_job": await read_config(db, "ffmpeg_threads_per_job", "1"),
            "quiet_split": await read_config(db, "quiet_split", "true"),
        }
        asr_provider = await read_config(db, "asr_provider", "whisper")
        asr_model = await read_config(db, "asr_model", "small")
        asr_base_url = await read_config(db, "asr_base_url", "https://api.openai.com/v1")
        asr_api_key = await read_config(db, "asr_api_key", "")
        asr_openai_model = await read_config(db, "asr_openai_model", "whisper-1")
        asr_language_raw = await read_config(db, "asr_language", "zh")
        asr_language = (asr_language_raw or "").strip()
        vlm_base_url = await read_config(db, "vlm_base_url", "https://api.openai.com/v1")
        vlm_model = await read_config(db, "vlm_model", "gpt-4o")
        vlm_api_key = await read_config(db, "vlm_api_key", "")
        vector_dim = int(await read_config(db, "vector_dimension", "1024"))
        frame_fps = float(await read_config(db, "frame_fps", "1"))
        frame_target_pixels = int(await read_config(db, "frame_target_pixels", "0"))
        frame_concurrency_raw = await read_config(db, "frame_concurrency", "3")
        vlm_max_images = int(await read_config(db, "vlm_max_images_per_batch", "10"))
        vlm_context_length = int(await read_config(db, "vlm_context_length", "65536"))
        asr_concurrency_raw = await read_config(db, "asr_concurrency", "1")
        vlm_concurrency_raw = await read_config(db, "vlm_concurrency", "3")
        embedding_concurrency_raw = await read_config(db, "embedding_concurrency", "3")
        asr_concurrency = parse_positive_int(asr_concurrency_raw, default=1, min_v=1, max_v=16)
        frame_concurrency = parse_positive_int(frame_concurrency_raw, default=3, min_v=1, max_v=16)
        vlm_concurrency = parse_positive_int(vlm_concurrency_raw, default=3, min_v=1, max_v=16)
        embedding_concurrency = parse_positive_int(embedding_concurrency_raw, default=3, min_v=1, max_v=16)
        embedding_base_url = await read_config(db, "embedding_base_url", "https://api.openai.com/v1")
        embedding_api_key = await read_config(db, "embedding_api_key", "")
        embedding_model = await read_config(db, "embedding_model", "text-embedding-3-small")
        embedding_timeout_sec = float(await read_config(db, "embedding_timeout_sec", "120"))
        if embedding_timeout_sec <= 0:
            embedding_timeout_sec = 120.0
        enrich_enabled_cfg = (await read_config(db, "enrich_enabled", "true")).strip().lower() in ("1", "true", "yes")
        asr_auto_correct_cfg = (await read_config(db, "asr_auto_correct", "false")).strip().lower() in ("1", "true", "yes")
        asr_auto_correct_apply = (await read_config(db, "asr_auto_correct_apply", "true")).strip().lower() in ("1", "true", "yes")
        asr_correct_hint = (await read_config(db, "asr_correct_hint", "")).strip()
    finally:
        await db.close()

    loop = asyncio.get_event_loop()
    cancel_event = cancel_event_for(video_id)
    await check_cancel(video_id)
    pipeline_deadline = time.perf_counter() + PIPELINE_TOTAL_TIMEOUT_SEC

    t0 = time.perf_counter()
    step_start_ts: dict[str, float] = {}
    step_end_ts: dict[str, float] = {}
    metrics_errors: list[str] = []
    vlm_tokens = TokenAccumulator()
    llm_tokens = TokenAccumulator()
    embed_tokens = TokenAccumulator()

    def _now() -> float:
        return time.perf_counter()

    def _ensure_step_start(step: str) -> None:
        if step not in step_start_ts:
            step_start_ts[step] = _now()

    def _ensure_step_end(step: str) -> None:
        if step not in step_end_ts and step in step_start_ts:
            step_end_ts[step] = _now()

    def _timing_ms_snapshot() -> dict:
        out: dict[str, int] = {}
        for s in ("split", "extract_frames", "asr", "vlm", "enrich", "embed", "replica"):
            st = step_start_ts.get(s)
            ed = step_end_ts.get(s)
            out[s] = 0 if st is None else int(((ed or _now()) - st) * 1000)
        out["total"] = int((_now() - t0) * 1000)
        return out

    def _metrics_snapshot() -> dict:
        return {
            "timing_ms": _timing_ms_snapshot(),
            "tokens": {
                "vlm": vlm_tokens.to_dict(),
                "llm": llm_tokens.to_dict(),
                "embed": embed_tokens.to_dict(),
            },
            "errors": list(metrics_errors),
        }

    def _remaining_timeout(cap_sec: float | None = None) -> float:
        remain = pipeline_deadline - time.perf_counter()
        if remain <= 0:
            raise TimeoutError(f"流水线总超时（>{int(PIPELINE_TOTAL_TIMEOUT_SEC)}s）")
        if cap_sec is None:
            return remain
        return max(0.1, min(cap_sec, remain))

    async def _put_with_timeout(q: asyncio.Queue, item: Any, label: str):
        try:
            await asyncio.wait_for(q.put(item), timeout=_remaining_timeout(PIPELINE_QUEUE_TIMEOUT_SEC))
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise TimeoutError(
                f"队列投递 {label} 超时（>{int(PIPELINE_QUEUE_TIMEOUT_SEC)}s），流水线可能已阻塞"
            ) from exc
        logger.debug("queue put ok: %s", label)

    async def _join_with_timeout(q: asyncio.Queue, label: str):
        try:
            await asyncio.wait_for(q.join(), timeout=_remaining_timeout(PIPELINE_QUEUE_TIMEOUT_SEC))
        except (asyncio.TimeoutError, TimeoutError) as exc:
            # asyncio.TimeoutError 的 str() 为空，必须包装出可读消息，否则任务级
            # handler 会打出「处理异常: 」空错误，无法定位
            raise TimeoutError(
                f"等待「{label}」阶段完成超时（>{int(PIPELINE_QUEUE_TIMEOUT_SEC)}s）："
                f"片段处理过慢或存在阻塞，可重跑（已完成的片段会跳过）"
            ) from exc
        logger.debug("queue join ok: %s", label)

    do_split = "split" not in skip_steps
    if do_split:
        _ensure_step_start("split")
        await reporter.send("split", "running", f"开始切分视频（流式模式：{split_mode})")
    else:
        await reporter.send("split", "skip", "跳过视频切分")

    clips_rows = await get_clips(video_id) if not do_split else []
    if not do_split and clip_ids_filter:
        clips_rows = [r for r in clips_rows if r["id"] in clip_ids_filter]
    total_clips = len(clips_rows)
    do_frames = "extract_frames" not in skip_steps
    do_asr = "asr" not in skip_steps
    do_vlm = "vlm" not in skip_steps
    do_embed = "embed" not in skip_steps
    do_enrich = enrich_enabled_cfg and "enrich" not in skip_steps

    if do_frames:
        msg = f"开始流式抽帧（{frame_fps} 帧/秒）" if do_split else f"开始为 {total_clips} 个片段抽帧（{frame_fps} 帧/秒）"
        await reporter.send("extract_frames", "running", msg)
    else:
        await reporter.send("extract_frames", "skip", "跳过图帧提取")

    whisper_inprocess_transcribe = os.environ.get("SMARTCLIP_WHISPER_INPROCESS_TRANSCRIBE", "").strip().lower() in ("1", "true", "yes")
    # TODO: 是否在主进程线程中执行 Embedding，非主进程情况下会卡死，待修复
    embed_inprocess = os.environ.get("SMARTCLIP_EMBED_INPROCESS", "1").strip().lower() in ("1", "true", "yes")

    asr_instance = None
    if do_asr:
        try:
            if asr_provider in ("openai", "bailian"):
                provider_name = "OpenAI ASR" if asr_provider == "openai" else "百炼 ASR"
                await reporter.send("asr", "running", f"使用 {provider_name} ({asr_openai_model}) 开始语音识别（子进程，可强杀超时）...")
                if not (asr_api_key or "").strip():
                    do_asr = False
                    await reporter.send("asr", "error", f"{provider_name} 未配置 API Key")
                else:
                    asr_instance = None
            else:
                if whisper_inprocess_transcribe:
                    await reporter.send("asr", "running", f"加载 Whisper ({asr_model}) 主进程线程识别（仅提音频走可杀子进程）...")
                    from app.core.asr.whisper_asr import WhisperASR

                    asr_instance = await run_heavy(WhisperASR, asr_model, language=asr_language or None)
                    logger.warning(
                        "SMARTCLIP_WHISPER_INPROCESS_TRANSCRIBE=1：Whisper 转写在主进程线程中执行，wait_for 超时后仍可能长期占用线程"
                    )
                else:
                    await reporter.send("asr", "running", f"使用 Whisper ({asr_model}) 子进程识别（可强杀超时，每片段会加载模型）...")
                    asr_instance = None
                    logger.info(
                        "本地 Whisper 每片段在独立子进程中识别；若需单进程复用模型可设 SMARTCLIP_WHISPER_INPROCESS_TRANSCRIBE=1（更快但超时有线程滞留风险）"
                    )
        except Exception as e:
            do_asr = False
            await reporter.send("asr", "error", f"ASR 初始化失败: {e}")
    else:
        await reporter.send("asr", "skip", "跳过语音识别")

    vlm_instance = None
    if do_vlm:
        if not vlm_api_key:
            do_vlm = False
            await reporter.send("vlm", "skip", "VLM API Key 未配置，跳过")
        else:
            await reporter.send("vlm", "running", f"使用 {vlm_model} 生成视觉描述...")
            try:
                from app.core.vlm.openai_vlm import OpenAIVLM

                vlm_instance = OpenAIVLM(base_url=vlm_base_url, model=vlm_model, api_key=vlm_api_key)
            except Exception as e:
                do_vlm = False
                await reporter.send("vlm", "error", f"VLM 初始化失败: {e}")
    else:
        await reporter.send("vlm", "skip", "跳过视觉描述")

    embedder = None
    vector_db = None
    if do_embed:
        if not embedding_api_key:
            do_embed = False
            await reporter.send("embed", "skip", "Embedding API Key 未配置，跳过向量入库")
        else:
            mode = "主进程线程" if embed_inprocess else "子进程"
            await reporter.send("embed", "running", f"开始生成 Embedding 并入库（{mode}，单片段超时 {int(embedding_timeout_sec)}s）...")
            try:
                embedder = Embedder(
                    base_url=embedding_base_url,
                    api_key=embedding_api_key,
                    model=embedding_model,
                    request_timeout_sec=embedding_timeout_sec,
                    volc_output_dimensions=vector_dim,
                )
                vector_db = FaissVectorDB(db_path=DB_PATH, vector_dimension=vector_dim)
                if embed_inprocess:
                    logger.warning(
                        "SMARTCLIP_EMBED_INPROCESS=1：Embedding 在主进程线程执行；超时后线程可能继续运行直至底层请求返回"
                    )
            except Exception as e:
                do_embed = False
                await reporter.send("embed", "error", f"Embedding 初始化失败: {e}")
    else:
        await reporter.send("embed", "skip", "跳过向量入库")

    # enrich：用 LLM 给每个片段生成「旁白适配摘要 + 关键词 + 情绪标签」，
    # 抹平「旁白文案（抽象层）↔ 画面/台词（具体层）」的表征鸿沟，提升旁白检索命中率。
    llm_instance = None
    if do_enrich:
        try:
            db = await get_db_conn()
            try:
                llm_params = await LLMConfig.get_llm_params_with_defaults(db, default_temperature=0.3)
            finally:
                await db.close()
            llm_instance = LLMClient(
                base_url=llm_params["base_url"],
                api_key=llm_params["api_key"],
                model=llm_params["model"],
                temperature=llm_params["temperature"],
                max_tokens=llm_params["max_tokens"],
            )
            await reporter.send("enrich", "running", f"智能标注开启（model={llm_params['model']}）：为每个片段生成旁白适配摘要/关键词/情绪…")
        except Exception as e:
            do_enrich = False
            llm_instance = None
            await reporter.send("enrich", "skip", f"智能标注跳过：LLM 未配置或初始化失败（{e}）")
    else:
        await reporter.send("enrich", "skip", "跳过智能标注（未启用或已 skip）")

    # ASR 自动 LLM 校准：独立于 enrich，即便 enrich 关闭也可启用。
    # 复用 llm_* 配置，温度偏低（0.2）以求稳定；失败不阻断流水线。
    asr_correct_llm: LLMClient | None = None
    if do_asr and asr_auto_correct_cfg:
        try:
            db = await get_db_conn()
            try:
                _ac_params = await LLMConfig.get_llm_params_with_defaults(db, default_temperature=0.2, default_max_tokens=8192)
            finally:
                await db.close()
            asr_correct_llm = LLMClient(
                base_url=_ac_params["base_url"],
                api_key=_ac_params["api_key"],
                model=_ac_params["model"],
                temperature=_ac_params["temperature"],
                max_tokens=_ac_params["max_tokens"],
                timeout=120.0,
            )
            logger.info("ASR 自动校准已启用（apply=%s, model=%s）", asr_auto_correct_apply, _ac_params["model"])
        except Exception as e:
            asr_correct_llm = None
            logger.warning("ASR 自动校准初始化失败，跳过: %s", e)

    frames_worker_count = max(1, frame_concurrency)
    asr_worker_count = max(1, asr_concurrency)
    vlm_worker_count = max(1, vlm_concurrency)
    embed_worker_count = max(1, embedding_concurrency)
    max_workers = max(frames_worker_count, asr_worker_count, vlm_worker_count, embed_worker_count)
    queue_maxsize = max(1, max_workers * 2)
    vector_db_lock = asyncio.Lock()
    progress_lock = asyncio.Lock()
    vlm_enqueue_lock = asyncio.Lock()
    frame_done = frame_success = asr_done = asr_success = vlm_done = vlm_success = emb_done = emb_success = 0
    enrich_done = enrich_success = 0

    async def _inc_progress(step: str, message_prefix: str, total: int, success: int, done: int):
        _ensure_step_start(step)
        completed = total > 0 and done >= total
        if completed:
            _ensure_step_end(step)
        # 全部处理完毕时立即发 status="done"，前端可以实时看到步骤完成
        # （不必等 Queue.join() 收尾）
        step_status = "done" if completed else "running"
        await reporter.send(
            step,
            step_status,
            f"{message_prefix} {done}/{total} 已处理（成功 {success}）",
            {"current": done, "total": total, "processed": success, "metrics": _metrics_snapshot()},
        )

    async def _load_frame_paths(clip_path: str):
        clip_name = os.path.splitext(os.path.basename(clip_path))[0]
        frames_dir = os.path.join(splitter.frames_dir, clip_name)
        if os.path.isdir(frames_dir):
            return sorted(os.path.join(frames_dir, f) for f in os.listdir(frames_dir) if f.lower().endswith((".jpg", ".png")))
        return []

    frame_queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)
    asr_queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)
    vlm_queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)
    embed_queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)

    def _make_item(clip_id: str, clip_path: str, asr_text: str = "", vlm_description: str = "") -> dict:
        item = {"id": clip_id, "clip_path": clip_path, "asr_text": (asr_text or "").strip(), "vlm_description": (vlm_description or "").strip(), "frame_paths": None, "frame_ready": asyncio.Event(), "asr_ready": asyncio.Event(), "vlm_enqueued": False, "abstract_summary": "", "keywords": [], "emotion_tags": []}
        if not do_asr:
            item["asr_ready"].set()
        return item

    async def _maybe_enqueue_vlm(item: dict):
        if not item["frame_ready"].is_set() or not item["asr_ready"].is_set():
            return
        async with vlm_enqueue_lock:
            if item["vlm_enqueued"]:
                return
            item["vlm_enqueued"] = True
            await _put_with_timeout(vlm_queue, item, f"vlm:{item['id']}")

    async def _frames_worker():
        nonlocal frame_done, frame_success
        while True:
            item = await frame_queue.get()
            if item is None:
                frame_queue.task_done()
                break
            ok = False
            try:
                await check_cancel(video_id)

                async def _run_frames():
                    await check_cancel(video_id)
                    fp = item["frame_paths"]
                    if not fp:
                        if do_frames:
                            fp = await run_killable_target(
                                _PIPELINE_ISOLATED,
                                "isolated_extract_frames",
                                (video_id, item["clip_path"], frame_fps, frame_target_pixels),
                                timeout_sec=PIPELINE_STEP_TIMEOUT_SEC,
                            )
                        elif do_vlm:
                            fp = await _load_frame_paths(item["clip_path"])
                            if not fp:
                                fp = await run_killable_target(
                                    _PIPELINE_ISOLATED,
                                    "isolated_extract_frames",
                                    (video_id, item["clip_path"], frame_fps, frame_target_pixels),
                                    timeout_sec=PIPELINE_STEP_TIMEOUT_SEC,
                                )
                    return fp or []

                frame_paths = await _step_with_timeout_retries(item["id"], "抽帧", _run_frames)
                if frame_paths is not None:
                    item["frame_paths"] = frame_paths
                    ok = bool(frame_paths)
                else:
                    item["frame_paths"] = []
            except ProcessCancelled:
                raise
            except Exception as e:
                logger.warning("片段 %s 抽帧失败: %s", item["id"], e)
            finally:
                item["frame_ready"].set()
                try:
                    if do_frames:
                        async with progress_lock:
                            frame_done += 1
                            if ok:
                                frame_success += 1
                            await _inc_progress("extract_frames", "抽帧", total_clips, frame_success, frame_done)
                    await _maybe_enqueue_vlm(item)
                except Exception:
                    logger.exception("_frames_worker finally 异常，跳过进度更新以免 task_done 缺失")
                finally:
                    frame_queue.task_done()

    async def _asr_worker():
        nonlocal asr_done, asr_success
        while True:
            item = await asr_queue.get()
            if item is None:
                asr_queue.task_done()
                break
            ok = False
            try:
                await check_cancel(video_id)

                async def _run_asr():
                    await check_cancel(video_id)
                    if asr_provider == "openai":
                        payload = await run_killable_target(
                            _PIPELINE_ISOLATED,
                            "isolated_openai_asr_clip",
                            (video_id, item["clip_path"], True, asr_base_url, asr_api_key, asr_openai_model, asr_language),
                            timeout_sec=PIPELINE_STEP_TIMEOUT_SEC,
                        )
                        return _transcript_from_payload(payload)
                    if asr_provider == "bailian":
                        payload = await run_killable_target(
                            _PIPELINE_ISOLATED,
                            "isolated_bailian_asr_clip",
                            (video_id, item["clip_path"], True, asr_base_url, asr_api_key, asr_openai_model, asr_language),
                            timeout_sec=PIPELINE_STEP_TIMEOUT_SEC,
                        )
                        return _transcript_from_payload(payload)
                    if whisper_inprocess_transcribe:
                        audio_path = await run_killable_target(
                            _PIPELINE_ISOLATED,
                            "isolated_extract_audio",
                            (video_id, item["clip_path"], True),
                            timeout_sec=PIPELINE_STEP_TIMEOUT_SEC,
                        )
                        return await asyncio.wait_for(
                            run_heavy(asr_instance.transcribe_detailed, audio_path),
                            timeout=PIPELINE_STEP_TIMEOUT_SEC,
                        )
                    payload = await run_killable_target(
                        _PIPELINE_ISOLATED,
                        "isolated_whisper_asr_clip",
                        (video_id, item["clip_path"], True, asr_model, asr_language or None),
                        timeout_sec=PIPELINE_STEP_TIMEOUT_SEC,
                    )
                    return _transcript_from_payload(payload)

                tr = await _step_with_timeout_retries(item["id"], "ASR", _run_asr)
                if tr is not None:
                    seg_json = json.dumps(tr.segments_as_dicts(), ensure_ascii=False) if tr.segments else None
                    await update_clip_asr(item["id"], tr.text, seg_json)
                    item["asr_text"] = (tr.text or "").strip()
                    # ASR 自动 LLM 校准：修正识别错误，保留原句级时间轴。
                    # 在 asr_ready.set() 之前完成，使下游 VLM/embedding 基于校准后文本。
                    # 注入视频标题作为主题，帮助修正领域专有名词（如「面积纸」→「面巾纸」）。
                    if asr_correct_llm is not None and item["asr_text"]:
                        try:
                            seg_list = tr.segments_as_dicts() if tr.segments else []
                            ac = await correct_transcript(
                                asr_correct_llm,
                                item["asr_text"],
                                seg_list,
                                topic=(video.get("name") or "").strip() or None,
                                hint=asr_correct_hint or None,
                            )
                            if ac["changed"]:
                                if asr_auto_correct_apply:
                                    ac_seg_json = (
                                        json.dumps(ac["corrected_segments"], ensure_ascii=False)
                                        if ac["corrected_segments"]
                                        else None
                                    )
                                    await update_clip_asr(
                                        item["id"], ac["corrected_text"], ac_seg_json
                                    )
                                    item["asr_text"] = (ac["corrected_text"] or "").strip()
                                    logger.info("片段 %s ASR 自动校准已应用", item["id"])
                                else:
                                    logger.info("片段 %s ASR 自动校准有改动但未应用（apply=False）", item["id"])
                        except Exception as ac_e:
                            logger.warning("片段 %s ASR 自动校准失败，沿用原结果: %s", item["id"], ac_e)
                    ok = True
            except ProcessCancelled:
                raise
            except Exception as e:
                logger.warning("片段 %s ASR 失败: %s", item["id"], e)
            finally:
                item["asr_ready"].set()
                try:
                    await _maybe_enqueue_vlm(item)
                    async with progress_lock:
                        asr_done += 1
                        if ok:
                            asr_success += 1
                        await _inc_progress("asr", "ASR", total_clips, asr_success, asr_done)
                except Exception:
                    logger.exception("_asr_worker finally 异常，跳过进度更新以免 task_done 缺失")
                finally:
                    asr_queue.task_done()

    async def _vlm_worker():
        nonlocal vlm_done, vlm_success, enrich_done, enrich_success
        while True:
            item = await vlm_queue.get()
            if item is None:
                vlm_queue.task_done()
                break
            ok = False
            try:
                await check_cancel(video_id)
                if do_vlm and vlm_instance is not None:
                    frame_paths = item["frame_paths"] or []
                    if frame_paths:
                        frame_times_sec = splitter.frame_timestamps_in_clip(item["clip_path"], len(frame_paths))

                        async def _run_vlm():
                            await check_cancel(video_id)
                            return await run_killable_target(
                                _PIPELINE_ISOLATED,
                                "isolated_vlm_generate",
                                (
                                    vlm_base_url,
                                    vlm_model,
                                    vlm_api_key,
                                    frame_paths,
                                    frame_times_sec,
                                    vlm_max_images,
                                    vlm_context_length,
                                ),
                                timeout_sec=PIPELINE_STEP_TIMEOUT_SEC,
                            )

                        raw_vlm = await _step_with_timeout_retries(item["id"], "VLM", _run_vlm)
                        if raw_vlm is not None:
                            description = raw_vlm.get("description") or ""
                            usage_dict = raw_vlm.get("usage")
                            usage = TokenUsage(**usage_dict) if usage_dict else None
                            est = int(raw_vlm.get("est") or 0)
                            try:
                                vlm_tokens.add_call(usage, estimated_total_tokens=est)
                            except Exception:
                                metrics_errors.append("vlm_usage_merge_error")
                            item["vlm_description"] = description.strip()
                            await update_clip_field(item["id"], "vlm_description", item["vlm_description"])
                            ok = True

                # enrich：基于台词+画面生成旁白适配摘要/关键词/情绪（抹平表征鸿沟）。
                # 与 do_vlm 解耦——enrich_only 重跑时 VLM 被 skip，但 asr_text/vlm_description
                # 已由 _make_item 从 DB 预加载，可独立跑。失败不阻断 pipeline，三字段留空即可。
                if do_enrich and llm_instance is not None:
                    t_enrich0 = time.perf_counter()

                    async def _run_enrich():
                        await check_cancel(video_id)
                        return await enrich_clip(
                            llm_instance,
                            asr_text=item["asr_text"],
                            vlm_description=item["vlm_description"],
                        )

                    enriched = await _step_with_timeout_retries(item["id"], "智能标注", _run_enrich)
                    t_enrich_ms = int((time.perf_counter() - t_enrich0) * 1000)
                    if enriched:
                        item["abstract_summary"] = enriched.get("abstract_summary", "")
                        item["keywords"] = enriched.get("keywords", [])
                        item["emotion_tags"] = enriched.get("emotion_tags", [])
                        if item["abstract_summary"]:
                            await update_clip_field(item["id"], "abstract_summary", item["abstract_summary"])
                        if item["keywords"]:
                            await update_clip_field(item["id"], "keywords", json.dumps(item["keywords"], ensure_ascii=False))
                        if item["emotion_tags"]:
                            await update_clip_field(item["id"], "emotion_tags", json.dumps(item["emotion_tags"], ensure_ascii=False))
                        enrich_success += 1
                        logger.info("片段 %s 智能标注完成：%dms（kw=%d, em=%d）", item["id"], t_enrich_ms, len(item["keywords"]), len(item["emotion_tags"]))
                    else:
                        logger.warning("片段 %s 智能标注失败/超时：%dms", item["id"], t_enrich_ms)
                    enrich_done += 1
                    try:
                        async with progress_lock:
                            await _inc_progress("enrich", "智能标注", total_clips, enrich_success, enrich_done)
                    except Exception:
                        logger.exception("enrich 进度更新异常")
            except ProcessCancelled:
                raise
            except Exception as e:
                logger.warning("片段 %s VLM 失败: %s", item["id"], e)
            finally:
                try:
                    if do_vlm:
                        async with progress_lock:
                            vlm_done += 1
                            if ok:
                                vlm_success += 1
                            await _inc_progress("vlm", "VLM", total_clips, vlm_success, vlm_done)
                    await _put_with_timeout(embed_queue, item, f"embed:{item['id']}")
                except ProcessCancelled:
                    raise
                except Exception:
                    logger.exception("_vlm_worker finally 异常，跳过以免 task_done 缺失")
                finally:
                    vlm_queue.task_done()

    async def _embed_worker():
        nonlocal emb_done, emb_success
        while True:
            item = await embed_queue.get()
            if item is None:
                embed_queue.task_done()
                break
            ok = False
            try:
                await check_cancel(video_id)
                if do_embed and embedder is not None and vector_db is not None:
                    if do_asr:
                        logger.info("片段 %s Embedding 等待 ASR 完成...", item["id"])
                        await item["asr_ready"].wait()
                    # 多向量子空间文本拼装：asr(台词+关键词) / vlm(画面) / abstract(摘要+情绪)。
                    # 拆分独立子空间抹平「旁白（抽象层）↔ 画面/台词（具体层）」的表征鸿沟，
                    # 检索侧由 FaissVectorDB 做 RRF 融合。无 enrich 数据时自动退化为 asr+vlm 两路。
                    sub_texts = build_sub_texts(
                        asr_text=item.get("asr_text", ""),
                        vlm_description=item.get("vlm_description", ""),
                        abstract_summary=item.get("abstract_summary", ""),
                        keywords=item.get("keywords"),
                        emotion_tags=item.get("emotion_tags"),
                    )
                    wanted_subs = non_empty_subspaces(sub_texts)
                    # 增量模式：只补缺失子空间（已存在的不重 embed），供「继续拆维度向量化」复用。
                    incremental_skipped = False
                    if embed_incremental and wanted_subs:
                        existing = vector_db.get_embedding_multi(item["id"])
                        before = wanted_subs
                        wanted_subs = [s for s in wanted_subs if not existing.get(s)]
                        incremental_skipped = bool(before) and not wanted_subs
                    if wanted_subs:
                        # 该日志与 WS 进度用于判断：是否已进入 embedding 外部调用、卡在哪个 clip
                        try:
                            async with progress_lock:
                                await reporter.send(
                                    "embed",
                                    "running",
                                    f"Embedding 正在处理片段 {item['id']}（已处理 {emb_done}/{total_clips}）",
                                    {"current": emb_done, "total": total_clips, "inflight_clip_id": item["id"], "metrics": _metrics_snapshot()},
                                )
                        except Exception:
                            pass
                        total_len = sum(len(sub_texts[s]) for s in wanted_subs)
                        logger.info(
                            "片段 %s Embedding 开始：子空间=%s 总长=%d model=%s",
                            item["id"],
                            wanted_subs,
                            total_len,
                            embedding_model,
                        )
                        async def _run_embed():
                            await check_cancel(video_id)
                            if embed_inprocess:
                                # 与 /process-embed 同路径：主进程线程调用，便于复现/对齐自测。
                                # 逐子空间调用 embedder.embed（火山方舟无 batch），共享同一 Embedder 连接。
                                usage_box: dict[str, Any] = {}

                                def _do_embed_sync():
                                    merged_usage: TokenUsage | None = None
                                    vectors: dict[str, list[float]] = {}

                                    def _on_usage(u):
                                        nonlocal merged_usage
                                        if u is None:
                                            return
                                        if merged_usage is None:
                                            merged_usage = TokenUsage()
                                        merged_usage.add(u)

                                    for sub in wanted_subs:
                                        vectors[sub] = embedder.embed(sub_texts[sub], on_usage=_on_usage)
                                    u_dict = merged_usage.to_dict() if isinstance(merged_usage, TokenUsage) else None
                                    return {"vectors": vectors, "usage": u_dict}

                                # 走专用 blocking_pool：embedding 是阻塞型 HTTP 调用，
                                # 默认 asyncio.to_thread 会与普通 HTTP 请求争默认线程池。
                                return await asyncio.wait_for(run_heavy(_do_embed_sync), timeout=embedding_timeout_sec)
                            return await run_killable_target(
                                _PIPELINE_ISOLATED,
                                "isolated_embed_multi",
                                (
                                    embedding_base_url,
                                    embedding_api_key,
                                    embedding_model,
                                    {s: sub_texts[s] for s in wanted_subs},
                                    embedding_timeout_sec,
                                    vector_dim,
                                ),
                                timeout_sec=embedding_timeout_sec,
                            )

                        t_embed0 = time.perf_counter()
                        raw_emb = await _step_with_timeout_retries(
                            item["id"],
                            "Embedding",
                            _run_embed,
                            timeout_sec=embedding_timeout_sec,
                        )
                        t_embed_ms = int((time.perf_counter() - t_embed0) * 1000)
                        if raw_emb is not None:
                            vectors = raw_emb["vectors"]
                            usage_dict = raw_emb.get("usage")
                            usage = TokenUsage(**usage_dict) if usage_dict else None
                            try:
                                embed_tokens.add_call(usage)
                            except Exception:
                                metrics_errors.append("embed_usage_merge_error")
                            async with vector_db_lock:
                                vector_db.add_embedding_multi(item["id"], vectors)
                            logger.info(
                                "片段 %s Embedding 写入完成：%dms 子空间=%s",
                                item["id"], t_embed_ms, list(vectors.keys()),
                            )
                            ok = True
                        else:
                            logger.warning("片段 %s Embedding 失败/超时：%dms", item["id"], t_embed_ms)
                    elif incremental_skipped:
                        logger.info("片段 %s Embedding 跳过：增量模式下子空间已齐全", item["id"])
                        ok = True  # 增量幂等完成，计入成功
                    else:
                        logger.info("片段 %s Embedding 跳过：无可用文本（asr+vlm 为空）", item["id"])
                else:
                    logger.info("片段 %s Embedding 跳过：do_embed=%s embedder=%s vector_db=%s", item["id"], do_embed, bool(embedder), bool(vector_db))
            except ProcessCancelled:
                raise
            except Exception as e:
                logger.warning("片段 %s Embedding 失败: %s", item["id"], e)
            finally:
                try:
                    if do_embed:
                        async with progress_lock:
                            emb_done += 1
                            if ok:
                                emb_success += 1
                            await _inc_progress("embed", "Embedding", total_clips, emb_success, emb_done)
                except Exception:
                    logger.exception("_embed_worker finally 异常，跳过进度更新以免 task_done 缺失")
                finally:
                    embed_queue.task_done()

    frames_workers = [asyncio.create_task(_frames_worker()) for _ in range(frames_worker_count)]
    vlm_workers = [asyncio.create_task(_vlm_worker()) for _ in range(vlm_worker_count)]
    embed_workers = [asyncio.create_task(_embed_worker()) for _ in range(embed_worker_count)]
    asr_workers = [asyncio.create_task(_asr_worker()) for _ in range(asr_worker_count)] if do_asr else []
    all_workers = [*frames_workers, *vlm_workers, *embed_workers, *asr_workers]
    cancelled_early = False

    async def _cancel_all_workers():
        for t in all_workers:
            t.cancel()
        await asyncio.wait_for(
            asyncio.gather(*all_workers, return_exceptions=True),
            timeout=_remaining_timeout(PIPELINE_WORKERS_DRAIN_TIMEOUT_SEC),
        )

    async def _enqueue_item(item: dict):
        await _put_with_timeout(frame_queue, item, f"frame:{item['id']}")
        if do_asr:
            await _put_with_timeout(asr_queue, item, f"asr:{item['id']}")

    def _split_progress_message(d: dict) -> str:
        phase = str(d.get("phase") or "")
        shots = int(d.get("shots_detected") or 0)
        planned = int(d.get("segments_planned") or 0)
        ready = int(d.get("clips_ready") or 0)
        mode = str(d.get("split_mode") or split_mode)
        if phase == "detecting":
            if mode == "hybrid" and planned > 0 and ready > 0:
                return (
                    f"镜头识别中（已发现 {shots} 个镜头），"
                    f"已导出 {ready}/{planned} 段（含超长镜头二次切分）…"
                )
            return f"镜头识别中，已发现 {shots} 个镜头…"
        if phase == "planning":
            return (
                f"混合模式：已规划 {planned} 段（{shots} 个镜头），"
                f"超长镜头二次切分中，已导出 {ready} 段…"
            )
        if phase == "cutting" and planned > 0:
            return f"正在导出片段 {ready}/{planned}（{shots} 个镜头），切分尚未结束…"
        if ready > 0:
            return f"已导出 {ready} 个片段，切分进行中…"
        return f"切分进行中（模式: {mode}）…"

    if do_split:
        await clear_clips_for_video(video_id)
        split_out_queue: asyncio.Queue = asyncio.Queue()
        split_done = object()
        split_error = {"err": None}
        split_count = 0
        last_split_detail: dict = {"phase": "detecting", "split_mode": split_mode, "shots_detected": 0, "segments_planned": 0, "clips_ready": 0}

        def _on_clip_created(clip):
            asyncio.run_coroutine_threadsafe(split_out_queue.put(("clip", clip)), loop).result()

        def _on_split_progress(data: dict):
            asyncio.run_coroutine_threadsafe(split_out_queue.put(("progress", data)), loop).result()

        async def _run_split_task():
            try:
                # 重任务（ffmpeg 切分）走专用 blocking_pool，避免占用默认线程池导致
                # 普通 HTTP 请求（list videos / stream / 静态文件等）排队卡顿。
                if split_mode == "fixed":
                    await asyncio.wait_for(
                        run_heavy(
                            splitter.split_by_fixed,
                            video_path,
                            fixed_duration,
                            transcode_opts=transcode_opts,
                            on_clip_created=_on_clip_created,
                            on_progress=_on_split_progress,
                            should_stop=cancel_event.is_set,
                        ),
                        timeout=_remaining_timeout(PIPELINE_SPLIT_TIMEOUT_SEC),
                    )
                elif split_mode == "hybrid":
                    await asyncio.wait_for(
                        run_heavy(
                            splitter.split_by_hybrid,
                            video_path,
                            scene_threshold,
                            scene_min_scene_len,
                            hybrid_max_segment_sec,
                            fixed_duration,
                            transcode_opts=transcode_opts,
                            on_clip_created=_on_clip_created,
                            on_progress=_on_split_progress,
                            should_stop=cancel_event.is_set,
                        ),
                        timeout=_remaining_timeout(PIPELINE_SPLIT_TIMEOUT_SEC),
                    )
                else:
                    await asyncio.wait_for(
                        run_heavy(
                            splitter.split_by_scene,
                            video_path,
                            scene_threshold,
                            scene_min_scene_len,
                            transcode_opts=transcode_opts,
                            on_clip_created=_on_clip_created,
                            on_progress=_on_split_progress,
                            should_stop=cancel_event.is_set,
                        ),
                        timeout=_remaining_timeout(PIPELINE_SPLIT_TIMEOUT_SEC),
                    )
            except (StopRequested, ProcessCancelled):
                split_error["err"] = ProcessCancelled()
            except Exception as e:
                split_error["err"] = e
            finally:
                await split_out_queue.put(("done", split_done))

        split_task = asyncio.create_task(_run_split_task())
        while True:
            _remaining_timeout()
            try:
                await check_cancel(video_id)
            except ProcessCancelled:
                cancelled_early = True
                break
            try:
                item = await asyncio.wait_for(split_out_queue.get(), timeout=min(1.0, _remaining_timeout(1.0)))
            except asyncio.TimeoutError:
                continue
            kind = item[0] if isinstance(item, tuple) else "clip"
            payload = item[1] if isinstance(item, tuple) else item
            if kind == "done":
                break
            if kind == "progress":
                last_split_detail = {**last_split_detail, **(payload or {})}
                detail = {
                    **last_split_detail,
                    "processed": split_count,
                    "metrics": _metrics_snapshot(),
                }
                await reporter.send(
                    "split",
                    "running",
                    _split_progress_message(detail),
                    detail,
                )
                continue
            clip_obj = payload
            try:
                await check_cancel(video_id)
            except ProcessCancelled:
                cancelled_early = True
                break
            clip_id = await insert_clip_to_db(video_id, clip_obj)
            split_count += 1
            total_clips = split_count
            last_split_detail["clips_ready"] = split_count
            planned = int(last_split_detail.get("segments_planned") or 0)
            detail = {
                **last_split_detail,
                "processed": split_count,
                "current": split_count,
                "total": max(planned, split_count),
                "metrics": _metrics_snapshot(),
            }
            await reporter.send(
                "split",
                "running",
                _split_progress_message({**detail, "phase": "cutting", "clips_ready": split_count}),
                detail,
            )
            await _enqueue_item(_make_item(clip_id, clip_obj.clip_path))

        await split_task
        if split_error["err"] is not None:
            await _cancel_all_workers()
            raise split_error["err"]
        if split_count <= 0:
            await _cancel_all_workers()
            await reporter.send("extract_frames", "error", "没有可处理的片段")
            await set_video_status(video_id, "error")
            return
        _ensure_step_end("split")
        await reporter.send(
            "split",
            "done",
            f"切分完成，共 {split_count} 个片段"
            + (
                f"（{int(last_split_detail.get('shots_detected') or 0)} 个镜头"
                f"→{int(last_split_detail.get('segments_planned') or split_count)} 段）"
                if split_mode in ("scene", "hybrid")
                and int(last_split_detail.get("shots_detected") or 0) > 0
                else ""
            ),
            {
                "total_clips": split_count,
                "shots_detected": int(last_split_detail.get("shots_detected") or 0),
                "segments_planned": int(last_split_detail.get("segments_planned") or split_count),
                "phase": "done",
                "metrics": _metrics_snapshot(),
            },
        )
    else:
        if not clips_rows:
            await _cancel_all_workers()
            await reporter.send("extract_frames", "error", "没有可处理的片段")
            await set_video_status(video_id, "error")
            return
        for clip in clips_rows:
            await _enqueue_item(_make_item(clip["id"], clip["clip_path"], clip["asr_text"] or "", clip["vlm_description"] or ""))

    if cancelled_early:
        await _cancel_all_workers()
        raise ProcessCancelled()

    # 收尾段：哨兵投递 → 逐队列 join → worker 排空。任何异常都要先回收 worker，
    # 否则孤儿协程会继续向已判失败的任务写进度（表现为「各步骤 done 但任务 error」）。
    try:
        for _ in range(frames_worker_count):
            await _put_with_timeout(frame_queue, None, "frame:sentinel")
        if do_asr:
            for _ in range(asr_worker_count):
                await _put_with_timeout(asr_queue, None, "asr:sentinel")
        await _join_with_timeout(frame_queue, "抽帧")
        if do_asr:
            await _join_with_timeout(asr_queue, "语音识别(ASR)")
        for _ in range(vlm_worker_count):
            await _put_with_timeout(vlm_queue, None, "vlm:sentinel")
        await _join_with_timeout(vlm_queue, "视觉描述(VLM)")
        for _ in range(embed_worker_count):
            await _put_with_timeout(embed_queue, None, "embed:sentinel")
        await _join_with_timeout(embed_queue, "向量入库(Embedding)")
        try:
            await asyncio.wait_for(
                asyncio.gather(*frames_workers, *vlm_workers, *embed_workers, *asr_workers),
                timeout=_remaining_timeout(PIPELINE_WORKERS_DRAIN_TIMEOUT_SEC),
            )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise TimeoutError(
                f"worker 收尾排空超时（>{int(PIPELINE_WORKERS_DRAIN_TIMEOUT_SEC)}s），可能有步骤阻塞"
            ) from exc
    except BaseException:
        try:
            await _cancel_all_workers()
        except Exception:
            logger.exception("异常路径回收 worker 失败（忽略）")
        raise

    if do_frames:
        _ensure_step_end("extract_frames")
        await reporter.send("extract_frames", "done", f"抽帧完成，成功 {frame_success}/{total_clips} 个（并发={frames_worker_count}）", {"processed": frame_success, "total": total_clips, "errors": total_clips - frame_success, "concurrency": frames_worker_count, "metrics": _metrics_snapshot()})
    if do_asr:
        _ensure_step_end("asr")
        await reporter.send("asr", "done", f"语音识别完成，成功 {asr_success}/{total_clips} 个（并发={asr_worker_count}）", {"processed": asr_success, "total": total_clips, "concurrency": asr_worker_count, "metrics": _metrics_snapshot()})
    if do_vlm:
        _ensure_step_end("vlm")
        await reporter.send("vlm", "done", f"视觉描述完成，成功 {vlm_success}/{total_clips} 个（并发={vlm_worker_count}）", {"processed": vlm_success, "total": total_clips, "concurrency": vlm_worker_count, "metrics": _metrics_snapshot()})
    if do_enrich:
        _ensure_step_end("enrich")
        await reporter.send("enrich", "done", f"智能标注完成，成功 {enrich_success}/{total_clips} 个（生成旁白适配摘要/关键词/情绪）", {"processed": enrich_success, "total": total_clips, "errors": total_clips - enrich_success, "metrics": _metrics_snapshot()})
    if do_embed:
        _ensure_step_end("embed")
        await reporter.send("embed", "done", f"向量入库完成，成功 {emb_success}/{total_clips} 个（并发={embed_worker_count}，model={embedding_model}）", {"processed": emb_success, "total": total_clips, "concurrency": embed_worker_count, "model": embedding_model, "metrics": _metrics_snapshot()})

    # 后置 step：复刻模板生成（仅 is_replica_ref=1 的参考视频触发；失败不阻断 pipeline）
    do_replica = "replica" not in skip_steps
    is_replica_ref = False
    if do_replica:
        try:
            db = await get_db_conn()
            try:
                cur = await db.execute("SELECT is_replica_ref FROM videos WHERE id = ?", (video_id,))
                vrow = await cur.fetchone()
                is_replica_ref = bool(vrow and int(vrow["is_replica_ref"] or 0) == 1)
            finally:
                await db.close()
        except Exception:
            is_replica_ref = False

    if do_replica and is_replica_ref:
        _ensure_step_start("replica")
        await reporter.send("replica", "running", "复刻模板生成中（基于多模态 clips）…")
        try:
            from app.api.replica import _generate_replica_template_core, ReplicaGenerateError, _REPLICA_TYPE_RULES, _REPLICA_TYPE_DEFAULT

            # 推断复刻类型：优先用 films 视频自身的标记，否则按 clips 数量粗判
            replica_type = _REPLICA_TYPE_DEFAULT
            result = await _generate_replica_template_core(
                video_id,
                replica_type=replica_type,
                style_profile="通用",
                quality_mode="high_quality",
                max_clips=min(160, max(20, total_clips or 80)),
                auto_status="confirmed",
            )
            _ensure_step_end("replica")
            await reporter.send(
                "replica",
                "done",
                f"复刻模板已生成并入库（template_id={result['template_id'][:8]}…）",
                {"template_id": result["template_id"], "metrics": _metrics_snapshot()},
            )
        except ReplicaGenerateError as e:
            logger.warning("复刻模板后置 step 生成失败（不阻断）video_id=%s: %s", video_id, e.detail)
            await reporter.send("replica", "error", f"复刻模板生成失败（不影响素材处理）: {e.detail}")
        except Exception as e:
            logger.exception("复刻模板后置 step 异常（不阻断）video_id=%s", video_id)
            await reporter.send("replica", "error", f"复刻模板生成异常（不影响素材处理）: {e}")
    else:
        await reporter.send("replica", "skip", "跳过复刻模板生成（非复刻参考视频或已显式 skip）")

    await set_video_status(video_id, "done")
    # 注：最终 "done" 事件由 _run_task 在 update_job_status 之后发送，避免 TaskHub 竞态
