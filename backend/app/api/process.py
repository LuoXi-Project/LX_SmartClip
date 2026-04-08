import asyncio
from datetime import datetime
import json
import logging
import os
import time
import uuid
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from app.db.database import get_db_conn, DB_PATH
from app.core.splitter import VideoSplitter, StopRequested
from app.core.embedder import Embedder
from app.core.vector_db.faiss_db import FaissVectorDB
from app.core.license import ensure_license_valid, is_license_enforced
from app.core.metrics.token_usage import TokenAccumulator, TokenUsage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["process"])
jobs_router = APIRouter(prefix="/api/process-jobs", tags=["process"])
splitter = VideoSplitter()

# 用户停止：不能继承 Exception，否则会被流水线里大量 except Exception 吞掉
class ProcessCancelled(BaseException):
    pass


_cancel_events: dict[str, asyncio.Event] = {}
_job_tasks: dict[str, asyncio.Task] = {}
_task_subscribers: dict[str, set[WebSocket]] = {}


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _cancel_event_for(video_id: str) -> asyncio.Event:
    ev = _cancel_events.get(video_id)
    if ev is None:
        ev = asyncio.Event()
        _cancel_events[video_id] = ev
    return ev


def request_process_cancel(video_id: str) -> None:
    _cancel_event_for(video_id).set()


async def _check_cancel(video_id: str) -> None:
    if _cancel_event_for(video_id).is_set():
        raise ProcessCancelled()


def _parse_positive_int(raw: str, default: int, min_v: int = 1, max_v: int = 16) -> int:
    try:
        v = int(str(raw).strip())
    except Exception:
        return default
    if v < min_v:
        return min_v
    if v > max_v:
        return max_v
    return v

STEP_LABELS = {
    "split":          "视频切分",
    "extract_frames": "图帧提取",
    "asr":            "语音识别 (ASR)",
    "vlm":            "视觉描述 (VLM)",
    "embed":          "向量入库",
}


async def _read_config(db, key: str, default: str = "") -> str:
    cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row["value"] if row else default


class ProgressReporter:
    """向 WebSocket 推送进度；无 WebSocket 时仅记录日志"""

    def __init__(self, ws: WebSocket = None, task_id: str | None = None):
        self.ws = ws
        self.task_id = task_id

    async def send(self, step: str, status: str, message: str, detail: dict = None):
        payload = {
            "step":    step,
            "status":  status,
            "message": message,
            "detail":  detail or {},
        }
        logger.info("[%s] %s: %s", step, status, message)
        if self.task_id:
            await _update_task_from_progress(
                self.task_id,
                step=step,
                status=status,
                message=message,
                detail=payload["detail"],
            )
            await _broadcast_task_message(self.task_id, payload)
        if self.ws:
            try:
                await self.ws.send_json(payload)
            except Exception:
                pass


async def _set_video_status(video_id: str, status: str):
    db = await get_db_conn()
    try:
        await db.execute("UPDATE videos SET status = ? WHERE id = ?", (status, video_id))
        await db.commit()
    finally:
        await db.close()


async def _get_video(video_id: str):
    db = await get_db_conn()
    try:
        cursor = await db.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
        return await cursor.fetchone()
    finally:
        await db.close()


async def _get_clips(video_id: str):
    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT id, clip_path, asr_text, vlm_description FROM clips "
            "WHERE video_id = ? ORDER BY start_time",
            (video_id,),
        )
        return await cursor.fetchall()
    finally:
        await db.close()


async def _get_task(task_id: str):
    db = await get_db_conn()
    try:
        cursor = await db.execute("SELECT * FROM process_tasks WHERE id = ?", (task_id,))
        return await cursor.fetchone()
    finally:
        await db.close()


async def _get_running_task_for_video(video_id: str):
    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT * FROM process_tasks WHERE video_id = ? AND status = 'running' ORDER BY created_at DESC LIMIT 1",
            (video_id,),
        )
        return await cursor.fetchone()
    finally:
        await db.close()


def _row_to_task_payload(row) -> dict:
    if not row:
        return {}
    try:
        steps = json.loads(row["progress_json"]) if row["progress_json"] else {}
    except Exception:
        steps = {}
    try:
        metrics = json.loads(row["metrics_json"]) if row["metrics_json"] else None
    except Exception:
        metrics = None
    return {
        "id": row["id"],
        "video_id": row["video_id"],
        "status": row["status"],
        "current_step": row["current_step"],
        "steps": steps,
        "metrics": metrics,
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "finished_at": row["finished_at"],
    }


async def _create_task(video_id: str) -> dict:
    running = await _get_running_task_for_video(video_id)
    if running:
        return _row_to_task_payload(running)
    task_id = str(uuid.uuid4())
    now = _now_iso()
    db = await get_db_conn()
    try:
        await db.execute(
            "INSERT INTO process_tasks (id, video_id, status, progress_json, created_at, updated_at) VALUES (?, ?, 'running', ?, ?, ?)",
            (task_id, video_id, "{}", now, now),
        )
        await db.commit()
    finally:
        await db.close()
    created = await _get_task(task_id)
    return _row_to_task_payload(created)


async def _update_task_status(task_id: str, status: str, error_message: str | None = None):
    now = _now_iso()
    finished_at = now if status in ("done", "error", "cancelled") else None
    db = await get_db_conn()
    try:
        await db.execute(
            "UPDATE process_tasks SET status = ?, error_message = ?, updated_at = ?, finished_at = COALESCE(?, finished_at) WHERE id = ?",
            (status, error_message, now, finished_at, task_id),
        )
        await db.commit()
    finally:
        await db.close()


async def _update_task_from_progress(task_id: str, step: str, status: str, message: str, detail: dict):
    row = await _get_task(task_id)
    if not row:
        return
    try:
        progress = json.loads(row["progress_json"]) if row["progress_json"] else {}
    except Exception:
        progress = {}
    progress[step] = {
        "status": status,
        "message": message,
        "detail": detail or {},
    }
    metrics = None
    if isinstance(detail, dict):
        m = detail.get("metrics")
        if isinstance(m, dict):
            metrics = m
    now = _now_iso()
    db = await get_db_conn()
    try:
        await db.execute(
            "UPDATE process_tasks SET current_step = ?, progress_json = ?, metrics_json = COALESCE(?, metrics_json), updated_at = ? WHERE id = ?",
            (step, json.dumps(progress, ensure_ascii=False), json.dumps(metrics, ensure_ascii=False) if metrics else None, now, task_id),
        )
        await db.commit()
    finally:
        await db.close()


async def _broadcast_task_message(task_id: str, payload: dict):
    subscribers = _task_subscribers.get(task_id)
    if not subscribers:
        return
    stale: list[WebSocket] = []
    for ws in subscribers:
        try:
            await ws.send_json(payload)
        except Exception:
            stale.append(ws)
    for ws in stale:
        subscribers.discard(ws)
    if not subscribers:
        _task_subscribers.pop(task_id, None)


async def _update_clip_field(clip_id: str, field: str, value: str):
    db = await get_db_conn()
    try:
        await db.execute(f"UPDATE clips SET {field} = ? WHERE id = ?", (value, clip_id))
        await db.commit()
    finally:
        await db.close()


async def _update_clip_asr(clip_id: str, asr_text: str, asr_segments_json: str | None):
    """同时写入全文与时间轴 JSON（asr_segments 为 None 时写入 SQL NULL）。"""
    db = await get_db_conn()
    try:
        await db.execute(
            "UPDATE clips SET asr_text = ?, asr_segments = ? WHERE id = ?",
            (asr_text, asr_segments_json, clip_id),
        )
        await db.commit()
    finally:
        await db.close()


async def _save_clips_to_db(video_id: str, clips):
    """将 ClipInfo 列表写入 clips 表"""
    db = await get_db_conn()
    try:
        await db.execute("DELETE FROM clips WHERE video_id = ?", (video_id,))
        for clip in clips:
            cid = str(uuid.uuid4())
            await db.execute(
                "INSERT INTO clips (id, video_id, clip_path, start_time, end_time, duration) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (cid, video_id, clip.clip_path, clip.start_time, clip.end_time, clip.duration),
            )
        await db.execute(
            "UPDATE videos SET total_clips = ? WHERE id = ?", (len(clips), video_id)
        )
        await db.commit()
    finally:
        await db.close()


async def _clear_clips_for_video(video_id: str):
    db = await get_db_conn()
    try:
        await db.execute("DELETE FROM clips WHERE video_id = ?", (video_id,))
        await db.execute("UPDATE videos SET total_clips = 0 WHERE id = ?", (video_id,))
        await db.commit()
    finally:
        await db.close()


async def _insert_clip_to_db(video_id: str, clip) -> str:
    clip_id = str(uuid.uuid4())
    db = await get_db_conn()
    try:
        await db.execute(
            "INSERT INTO clips (id, video_id, clip_path, start_time, end_time, duration) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                clip_id,
                video_id,
                clip.clip_path,
                float(clip.start_time),
                float(clip.end_time),
                float(clip.duration),
            ),
        )
        await db.execute(
            "UPDATE videos SET total_clips = (SELECT COUNT(*) FROM clips WHERE video_id = ?) WHERE id = ?",
            (video_id, video_id),
        )
        await db.commit()
        return clip_id
    finally:
        await db.close()


async def _run_pipeline(video_id: str, reporter: ProgressReporter, skip_steps: list = None, task_id: str | None = None):
    """执行全素材处理（按片段流水线并发）：split -> (frames||asr) -> vlm -> embed"""
    skip_steps = skip_steps or []

    video = await _get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")

    _cancel_event_for(video_id).clear()
    video_path = video["file_path"]
    await _set_video_status(video_id, "processing")

    # 读取全部配置
    db = await get_db_conn()
    try:
        split_mode      = await _read_config(db, "split_mode", "scene")
        scene_threshold = float(await _read_config(db, "scene_threshold", "0.4"))
        scene_min_scene_len = int(await _read_config(db, "scene_min_scene_len", "30"))
        fixed_duration  = float(await _read_config(db, "fixed_duration", "10"))
        hybrid_max_segment_sec = float(await _read_config(db, "hybrid_max_segment_sec", "60"))

        # 切分性能/转码参数（由前端配置）
        transcode_opts = {
            "clip_container": await _read_config(db, "clip_container", "mp4"),
            "clip_vcodec": await _read_config(db, "clip_vcodec", "libx264"),
            "clip_acodec": await _read_config(db, "clip_acodec", "aac"),
            "clip_preset": await _read_config(db, "clip_preset", "veryfast"),
            "clip_crf": await _read_config(db, "clip_crf", "23"),
            "clip_video_bitrate_kbps": await _read_config(db, "clip_video_bitrate_kbps", "0"),
            "clip_audio_bitrate_kbps": await _read_config(db, "clip_audio_bitrate_kbps", "128"),
            "clip_fps": await _read_config(db, "clip_fps", "0"),
            "clip_scale_width": await _read_config(db, "clip_scale_width", "0"),
            "clip_scale_height": await _read_config(db, "clip_scale_height", "0"),
            "clip_pix_fmt": await _read_config(db, "clip_pix_fmt", "yuv420p"),
            # cut performance / stream copy
            "cut_mode": await _read_config(db, "cut_mode", "fast"),
            "stream_copy": await _read_config(db, "stream_copy", "false"),
            "stream_copy_audio": await _read_config(db, "stream_copy_audio", "false"),
            "split_max_workers": await _read_config(db, "split_max_workers", "2"),
            "ffmpeg_threads_per_job": await _read_config(db, "ffmpeg_threads_per_job", "1"),
            "quiet_split": await _read_config(db, "quiet_split", "true"),
        }
        asr_provider    = await _read_config(db, "asr_provider", "whisper")
        asr_model       = await _read_config(db, "asr_model", "base")
        asr_base_url    = await _read_config(db, "asr_base_url", "https://api.openai.com/v1")
        asr_api_key     = await _read_config(db, "asr_api_key", "")
        asr_openai_model = await _read_config(db, "asr_openai_model", "whisper-1")
        asr_language_raw = await _read_config(db, "asr_language", "zh")
        asr_language = (asr_language_raw or "").strip()
        vlm_base_url    = await _read_config(db, "vlm_base_url", "https://api.openai.com/v1")
        vlm_model       = await _read_config(db, "vlm_model", "gpt-4o")
        vlm_api_key     = await _read_config(db, "vlm_api_key", "")
        vector_dim      = int(await _read_config(db, "vector_dimension", "1536"))
        frame_fps       = float(await _read_config(db, "frame_fps", "1"))
        frame_target_pixels = int(await _read_config(db, "frame_target_pixels", "0"))
        frame_concurrency_raw = await _read_config(db, "frame_concurrency", "3")
        vlm_max_images    = int(await _read_config(db, "vlm_max_images_per_batch", "10"))
        vlm_context_length = int(await _read_config(db, "vlm_context_length", "8192"))
        asr_concurrency_raw = await _read_config(db, "asr_concurrency", "1")
        vlm_concurrency_raw = await _read_config(db, "vlm_concurrency", "3")
        embedding_concurrency_raw = await _read_config(db, "embedding_concurrency", "3")
        asr_concurrency = _parse_positive_int(asr_concurrency_raw, default=1, min_v=1, max_v=16)
        frame_concurrency = _parse_positive_int(frame_concurrency_raw, default=3, min_v=1, max_v=16)
        vlm_concurrency = _parse_positive_int(vlm_concurrency_raw, default=3, min_v=1, max_v=16)
        embedding_concurrency = _parse_positive_int(embedding_concurrency_raw, default=3, min_v=1, max_v=16)
        embedding_base_url = await _read_config(db, "embedding_base_url", "https://api.openai.com/v1")
        embedding_api_key  = await _read_config(db, "embedding_api_key", "")
        embedding_model    = await _read_config(db, "embedding_model", "text-embedding-3-small")
    finally:
        await db.close()

    loop = asyncio.get_event_loop()
    cancel_event = _cancel_event_for(video_id)

    await _check_cancel(video_id)

    # ===== Metrics（阶段耗时 + token）=====
    t0 = time.perf_counter()
    step_start_ts: dict[str, float] = {}
    step_end_ts: dict[str, float] = {}
    metrics_errors: list[str] = []
    vlm_tokens = TokenAccumulator()
    llm_tokens = TokenAccumulator()  # 当前 pipeline 不调用 LLM，但预留结构给前端统一展示
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
        for s in ("split", "extract_frames", "asr", "vlm", "embed"):
            st = step_start_ts.get(s)
            ed = step_end_ts.get(s)
            if st is None:
                out[s] = 0
            else:
                out[s] = int(((ed or _now()) - st) * 1000)
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

    do_split = "split" not in skip_steps
    if do_split:
        _ensure_step_start("split")
        await reporter.send("split", "running", f"开始切分视频（流式模式：{split_mode})")
    else:
        await reporter.send("split", "skip", "跳过视频切分")

    clips_rows = await _get_clips(video_id) if not do_split else []
    total_clips = len(clips_rows)
    do_frames = "extract_frames" not in skip_steps
    do_asr = "asr" not in skip_steps
    do_vlm = "vlm" not in skip_steps
    do_embed = "embed" not in skip_steps

    if do_frames:
        if do_split:
            await reporter.send("extract_frames", "running", f"开始流式抽帧（{frame_fps} 帧/秒）")
        else:
            await reporter.send("extract_frames", "running", f"开始为 {total_clips} 个片段抽帧（{frame_fps} 帧/秒）")
    else:
        await reporter.send("extract_frames", "skip", "跳过图帧提取")

    asr_instance = None
    if do_asr:
        try:
            if asr_provider == "openai":
                await reporter.send("asr", "running", f"使用 OpenAI ASR ({asr_openai_model}) 开始语音识别...")
                from app.core.asr.openai_asr import OpenAIASR
                asr_instance = OpenAIASR(
                    base_url=asr_base_url,
                    api_key=asr_api_key,
                    model=asr_openai_model,
                    language=asr_language,
                )
            else:
                await reporter.send("asr", "running", f"加载 Whisper ({asr_model}) 开始语音识别...")
                from app.core.asr.whisper_asr import WhisperASR

                def _make_whisper():
                    return WhisperASR(asr_model, language=asr_language or None)

                asr_instance = await loop.run_in_executor(None, _make_whisper)
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
                vlm_instance = OpenAIVLM(
                    base_url=vlm_base_url, model=vlm_model, api_key=vlm_api_key
                )
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
            await reporter.send("embed", "running", "开始生成 Embedding 并入库...")
            try:
                embedder = Embedder(
                    base_url=embedding_base_url,
                    api_key=embedding_api_key,
                    model=embedding_model,
                )
                vector_db = FaissVectorDB(db_path=DB_PATH, vector_dimension=vector_dim)
            except Exception as e:
                do_embed = False
                await reporter.send("embed", "error", f"Embedding 初始化失败: {e}")
    else:
        await reporter.send("embed", "skip", "跳过向量入库")

    # 多队列流水线：frames/asr 并发，frames -> vlm -> embed 级联。
    # 优先使用已有的分阶段并发配置（frame/asr/vlm/embedding）。
    frames_worker_count = max(1, frame_concurrency)
    asr_worker_count = max(1, asr_concurrency)
    vlm_worker_count = max(1, vlm_concurrency)
    embed_worker_count = max(1, embedding_concurrency)
    max_workers = max(frames_worker_count, asr_worker_count, vlm_worker_count, embed_worker_count)
    queue_maxsize = max(1, max_workers * 2)
    vector_db_lock = asyncio.Lock()
    progress_lock = asyncio.Lock()
    vlm_enqueue_lock = asyncio.Lock()

    frame_done = 0
    frame_success = 0
    asr_done = 0
    asr_success = 0
    vlm_done = 0
    vlm_success = 0
    emb_done = 0
    emb_success = 0

    async def _inc_progress(step: str, message_prefix: str, total: int, success: int, done: int):
        # phase timing
        _ensure_step_start(step)
        if total > 0 and done >= total:
            _ensure_step_end(step)
        await reporter.send(
            step,
            "running",
            f"{message_prefix} {done}/{total} 完成",
            {
                "current": done,
                "total": total,
                "processed": success,
                "metrics": _metrics_snapshot(),
            },
        )

    async def _load_frame_paths(clip_path: str):
        clip_name = os.path.splitext(os.path.basename(clip_path))[0]
        frames_dir = os.path.join(splitter.frames_dir, clip_name)
        if os.path.isdir(frames_dir):
            return sorted(
                os.path.join(frames_dir, f)
                for f in os.listdir(frames_dir)
                if f.lower().endswith((".jpg", ".png"))
            )
        return []

    frame_queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)
    asr_queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)
    vlm_queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)
    embed_queue: asyncio.Queue = asyncio.Queue(maxsize=queue_maxsize)

    def _make_item(clip_id: str, clip_path: str, asr_text: str = "", vlm_description: str = "") -> dict:
        item = {
            "id": clip_id,
            "clip_path": clip_path,
            "asr_text": (asr_text or "").strip(),
            "vlm_description": (vlm_description or "").strip(),
            "frame_paths": None,
            "frame_ready": asyncio.Event(),
            "asr_ready": asyncio.Event(),
            "vlm_enqueued": False,
        }
        if not do_asr:
            item["asr_ready"].set()
        return item

    async def _maybe_enqueue_vlm(item: dict):
        """同一片段仅在依赖就绪后入队一次，避免等待全量阶段结束。"""
        if not item["frame_ready"].is_set() or not item["asr_ready"].is_set():
            return
        async with vlm_enqueue_lock:
            if item["vlm_enqueued"]:
                return
            item["vlm_enqueued"] = True
            await vlm_queue.put(item)

    async def _frames_worker():
        nonlocal frame_done, frame_success
        while True:
            item = await frame_queue.get()
            if item is None:
                frame_queue.task_done()
                break
            ok = False
            try:
                await _check_cancel(video_id)
                frame_paths = item["frame_paths"]
                if not frame_paths:
                    if do_frames:
                        frame_paths = await loop.run_in_executor(
                            None,
                            splitter.extract_frames,
                            item["clip_path"],
                            frame_fps,
                            frame_target_pixels,
                        )
                    elif do_vlm:
                        frame_paths = await _load_frame_paths(item["clip_path"])
                        if not frame_paths:
                            frame_paths = await loop.run_in_executor(
                                None,
                                splitter.extract_frames,
                                item["clip_path"],
                                frame_fps,
                                frame_target_pixels,
                            )
                item["frame_paths"] = frame_paths or []
                ok = bool(item["frame_paths"])
            except Exception as e:
                logger.warning("片段 %s 抽帧失败: %s", item["id"], e)
            finally:
                item["frame_ready"].set()
                if do_frames:
                    async with progress_lock:
                        frame_done += 1
                        if ok:
                            frame_success += 1
                        await _inc_progress("extract_frames", "抽帧", total_clips, frame_success, frame_done)
                await _maybe_enqueue_vlm(item)
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
                await _check_cancel(video_id)
                audio_path = await loop.run_in_executor(
                    None, splitter.extract_audio, item["clip_path"], True
                )
                tr = await loop.run_in_executor(
                    None, asr_instance.transcribe_detailed, audio_path
                )
                seg_json = (
                    json.dumps(tr.segments_as_dicts(), ensure_ascii=False)
                    if tr.segments
                    else None
                )
                await _update_clip_asr(item["id"], tr.text, seg_json)
                item["asr_text"] = (tr.text or "").strip()
                ok = True
            except Exception as e:
                logger.warning("片段 %s ASR 失败: %s", item["id"], e)
            finally:
                item["asr_ready"].set()
                await _maybe_enqueue_vlm(item)
                async with progress_lock:
                    asr_done += 1
                    if ok:
                        asr_success += 1
                    await _inc_progress("asr", "ASR", total_clips, asr_success, asr_done)
                asr_queue.task_done()

    async def _vlm_worker():
        nonlocal vlm_done, vlm_success
        while True:
            item = await vlm_queue.get()
            if item is None:
                vlm_queue.task_done()
                break
            ok = False
            try:
                await _check_cancel(video_id)
                if do_vlm and vlm_instance is not None:
                    frame_paths = item["frame_paths"] or []
                    if frame_paths:
                        frame_times_sec = splitter.frame_timestamps_in_clip(
                            item["clip_path"], len(frame_paths)
                        )
                        def _call_vlm(fp, ts):
                            box: dict[str, object] = {"usage": None, "est": 0}

                            def _on_usage(u: TokenUsage | None, est: int):
                                box["usage"] = u
                                box["est"] = int(est or 0)

                            desc = vlm_instance.generate_description(
                                fp,
                                ts,
                                vlm_max_images,
                                vlm_context_length,
                                on_usage=_on_usage,
                            )
                            return desc, box

                        description, usage_box = await loop.run_in_executor(
                            None,
                            lambda fp=frame_paths, ts=frame_times_sec: _call_vlm(fp, ts),
                        )
                        try:
                            usage = usage_box.get("usage")  # type: ignore[assignment]
                            est = int(usage_box.get("est") or 0)
                            if usage is None or isinstance(usage, TokenUsage):
                                vlm_tokens.add_call(usage, estimated_total_tokens=est)
                            else:
                                metrics_errors.append("vlm_usage_type_error")
                        except Exception:
                            metrics_errors.append("vlm_usage_merge_error")
                        item["vlm_description"] = (description or "").strip()
                        await _update_clip_field(item["id"], "vlm_description", item["vlm_description"])
                        ok = True
            except Exception as e:
                logger.warning("片段 %s VLM 失败: %s", item["id"], e)
            finally:
                if do_vlm:
                    async with progress_lock:
                        vlm_done += 1
                        if ok:
                            vlm_success += 1
                        await _inc_progress("vlm", "VLM", total_clips, vlm_success, vlm_done)
                await embed_queue.put(item)
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
                await _check_cancel(video_id)
                if do_embed and embedder is not None and vector_db is not None:
                    if do_asr:
                        await item["asr_ready"].wait()
                    text = f'{item["asr_text"]} {item["vlm_description"]}'.strip()
                    if text:
                        def _call_embed(inp: str):
                            box: dict[str, object] = {"usage": None}

                            def _on_usage(u: TokenUsage | None):
                                box["usage"] = u

                            vec = embedder.embed(inp, on_usage=_on_usage)
                            return vec, box

                        embedding, usage_box = await loop.run_in_executor(
                            None,
                            lambda t=text: _call_embed(t),
                        )
                        try:
                            usage = usage_box.get("usage")  # type: ignore[assignment]
                            if usage is None or isinstance(usage, TokenUsage):
                                embed_tokens.add_call(usage)
                            else:
                                metrics_errors.append("embed_usage_type_error")
                        except Exception:
                            metrics_errors.append("embed_usage_merge_error")
                        async with vector_db_lock:
                            vector_db.add_embedding(item["id"], embedding)
                        ok = True
            except Exception as e:
                logger.warning("片段 %s Embedding 失败: %s", item["id"], e)
            finally:
                if do_embed:
                    async with progress_lock:
                        emb_done += 1
                        if ok:
                            emb_success += 1
                        await _inc_progress("embed", "Embedding", total_clips, emb_success, emb_done)
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
        await asyncio.gather(*all_workers, return_exceptions=True)

    async def _enqueue_item(item: dict):
        await frame_queue.put(item)
        if do_asr:
            await asr_queue.put(item)

    if do_split:
        await _clear_clips_for_video(video_id)
        split_out_queue: asyncio.Queue = asyncio.Queue()
        split_done = object()
        split_error = {"err": None}
        split_count = 0

        def _on_clip_created(clip):
            asyncio.run_coroutine_threadsafe(split_out_queue.put(clip), loop).result()

        async def _run_split_task():
            try:
                if split_mode == "fixed":
                    await loop.run_in_executor(
                        None,
                        lambda: splitter.split_by_fixed(
                            video_path,
                            fixed_duration,
                            transcode_opts=transcode_opts,
                            on_clip_created=_on_clip_created,
                        ),
                    )
                elif split_mode == "hybrid":
                    await loop.run_in_executor(
                        None,
                        lambda: splitter.split_by_hybrid(
                            video_path,
                            scene_threshold,
                            scene_min_scene_len,
                            hybrid_max_segment_sec,
                            fixed_duration,
                            transcode_opts=transcode_opts,
                            on_clip_created=_on_clip_created,
                            should_stop=cancel_event.is_set,
                        ),
                    )
                else:
                    await loop.run_in_executor(
                        None,
                        lambda: splitter.split_by_scene(
                            video_path,
                            scene_threshold,
                            scene_min_scene_len,
                            transcode_opts=transcode_opts,
                            on_clip_created=_on_clip_created,
                            should_stop=cancel_event.is_set,
                        ),
                    )
            except (StopRequested, ProcessCancelled):
                split_error["err"] = ProcessCancelled()
            except Exception as e:
                split_error["err"] = e
            finally:
                await split_out_queue.put(split_done)

        split_task = asyncio.create_task(_run_split_task())

        while True:
            try:
                await _check_cancel(video_id)
            except ProcessCancelled:
                cancelled_early = True
                break
            try:
                clip_obj = await asyncio.wait_for(split_out_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if clip_obj is split_done:
                break
            try:
                await _check_cancel(video_id)
            except ProcessCancelled:
                cancelled_early = True
                break
            clip_id = await _insert_clip_to_db(video_id, clip_obj)
            split_count += 1
            total_clips = split_count
            await reporter.send(
                "split",
                "running",
                f"已切分 {split_count} 个片段，正在流式进入后续处理",
                {"processed": split_count},
            )
            await _enqueue_item(_make_item(clip_id, clip_obj.clip_path))

        await split_task
        if split_error["err"] is not None:
            await _cancel_all_workers()
            raise split_error["err"]
        if split_count <= 0:
            await _cancel_all_workers()
            await reporter.send("extract_frames", "error", "没有可处理的片段")
            await _set_video_status(video_id, "error")
            return
        _ensure_step_end("split")
        await reporter.send(
            "split",
            "done",
            f"切分完成，共 {split_count} 个片段",
            {"total_clips": split_count, "metrics": _metrics_snapshot()},
        )
    else:
        if not clips_rows:
            await _cancel_all_workers()
            await reporter.send("extract_frames", "error", "没有可处理的片段")
            await _set_video_status(video_id, "error")
            return
        for clip in clips_rows:
            await _enqueue_item(
                _make_item(
                    clip["id"],
                    clip["clip_path"],
                    clip["asr_text"] or "",
                    clip["vlm_description"] or "",
                )
            )

    if cancelled_early:
        await _cancel_all_workers()
        raise ProcessCancelled()

    for _ in range(frames_worker_count):
        await frame_queue.put(None)
    if do_asr:
        for _ in range(asr_worker_count):
            await asr_queue.put(None)

    await frame_queue.join()
    if do_asr:
        await asr_queue.join()
    for _ in range(vlm_worker_count):
        await vlm_queue.put(None)

    await vlm_queue.join()
    for _ in range(embed_worker_count):
        await embed_queue.put(None)

    await embed_queue.join()

    await asyncio.gather(*frames_workers, *vlm_workers, *embed_workers, *asr_workers)

    if do_frames:
        _ensure_step_end("extract_frames")
        await reporter.send(
            "extract_frames",
            "done",
            f"抽帧完成，成功 {frame_success}/{total_clips} 个（并发={frames_worker_count}）",
            {
                "processed": frame_success,
                "total": total_clips,
                "errors": total_clips - frame_success,
                "concurrency": frames_worker_count,
                "metrics": _metrics_snapshot(),
            },
        )
    if do_asr:
        _ensure_step_end("asr")
        await reporter.send(
            "asr",
            "done",
            f"语音识别完成，成功 {asr_success}/{total_clips} 个（并发={asr_worker_count}）",
            {
                "processed": asr_success,
                "total": total_clips,
                "concurrency": asr_worker_count,
                "metrics": _metrics_snapshot(),
            },
        )
    if do_vlm:
        _ensure_step_end("vlm")
        await reporter.send(
            "vlm",
            "done",
            f"视觉描述完成，成功 {vlm_success}/{total_clips} 个（并发={vlm_worker_count}）",
            {
                "processed": vlm_success,
                "total": total_clips,
                "concurrency": vlm_worker_count,
                "metrics": _metrics_snapshot(),
            },
        )
    if do_embed:
        _ensure_step_end("embed")
        await reporter.send(
            "embed",
            "done",
            f"向量入库完成，成功 {emb_success}/{total_clips} 个（并发={embed_worker_count}，model={embedding_model}）",
            {
                "processed": emb_success,
                "total": total_clips,
                "concurrency": embed_worker_count,
                "model": embedding_model,
                "metrics": _metrics_snapshot(),
            },
        )

    await _set_video_status(video_id, "done")
    # 最终汇总
    await reporter.send("done", "done", "全部处理完成！", {"metrics": _metrics_snapshot()})


# HTTP 接口：POST /api/videos/{id}/process-cancel
@router.post("/{video_id}/process-cancel")
async def process_video_cancel(video_id: str):
    """兼容旧接口：按视频取消正在运行的任务。"""
    running = await _get_running_task_for_video(video_id)
    if not running:
        return {"ok": True, "video_id": video_id}
    request_process_cancel(video_id)
    return {"ok": True, "video_id": video_id, "task_id": running["id"]}


async def _run_task(task_id: str, video_id: str, skip_steps: list[str] | None = None):
    reporter = ProgressReporter(ws=None, task_id=task_id)
    try:
        await _run_pipeline(video_id, reporter, skip_steps=skip_steps or [], task_id=task_id)
        await _update_task_status(task_id, "done")
    except ProcessCancelled:
        await _set_video_status(video_id, "pending")
        await reporter.send("done", "done", "处理已停止", {"cancelled": True})
        await _update_task_status(task_id, "cancelled")
    except Exception as e:
        await _set_video_status(video_id, "error")
        await reporter.send("error", "error", f"处理异常: {str(e)}")
        await _update_task_status(task_id, "error", error_message=str(e))
    finally:
        _job_tasks.pop(task_id, None)


@router.post("/{video_id}/process-jobs")
async def create_process_job(video_id: str):
    video = await _get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")
    if is_license_enforced() and not await ensure_license_valid():
        raise HTTPException(status_code=403, detail="LICENSE_REQUIRED")

    task_payload = await _create_task(video_id)
    task_id = task_payload["id"]
    if task_id not in _job_tasks:
        _job_tasks[task_id] = asyncio.create_task(_run_task(task_id, video_id))
    return {
        "task_id": task_id,
        "video_id": video_id,
        "status": task_payload["status"],
        "stream_url": f"/api/process-jobs/{task_id}/ws",
    }


@jobs_router.get("/{task_id}")
async def get_process_job(task_id: str):
    row = await _get_task(task_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"任务 '{task_id}' 不存在")
    return _row_to_task_payload(row)


@jobs_router.post("/{task_id}/cancel")
async def cancel_process_job(task_id: str):
    row = await _get_task(task_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"任务 '{task_id}' 不存在")
    request_process_cancel(row["video_id"])
    return {"ok": True, "task_id": task_id, "video_id": row["video_id"]}


@jobs_router.websocket("/{task_id}/ws")
async def process_job_ws(task_id: str, ws: WebSocket):
    await ws.accept()
    row = await _get_task(task_id)
    if not row:
        await ws.send_json({"step": "error", "status": "error", "message": "任务不存在", "detail": {}})
        await ws.close()
        return
    _task_subscribers.setdefault(task_id, set()).add(ws)
    try:
        while True:
            await ws.receive()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        _task_subscribers.get(task_id, set()).discard(ws)
        try:
            await ws.close()
        except Exception:
            pass


# 兼容旧接口：行为改为“创建后台任务并返回 task_id”
@router.post("/{video_id}/process")
async def process_video_http(video_id: str):
    return await create_process_job(video_id)


# 兼容旧 WebSocket 接口：不再断开即取消，仅复用任务订阅
@router.websocket("/{video_id}/process-ws")
async def process_video_ws(video_id: str, ws: WebSocket):
    await ws.accept()
    video = await _get_video(video_id)
    if not video:
        await ws.send_json({"step": "error", "status": "error", "message": "视频不存在", "detail": {}})
        await ws.close()
        return
    if is_license_enforced() and not await ensure_license_valid():
        await ws.send_json({"step": "error", "status": "error", "message": "LICENSE_REQUIRED", "detail": {}})
        await ws.close()
        return
    try:
        _ = await asyncio.wait_for(ws.receive_json(), timeout=60.0)
    except Exception:
        pass
    task_payload = await _create_task(video_id)
    task_id = task_payload["id"]
    if task_id not in _job_tasks:
        _job_tasks[task_id] = asyncio.create_task(_run_task(task_id, video_id))
    _task_subscribers.setdefault(task_id, set()).add(ws)
    try:
        while True:
            await ws.receive()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        _task_subscribers.get(task_id, set()).discard(ws)
        try:
            await ws.close()
        except Exception:
            pass
