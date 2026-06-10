"""素材处理流水线运行时上下文。"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from app.core.embedder import Embedder
from app.core.metrics.token_usage import TokenAccumulator
from app.core.vector_db.faiss_db import FaissVectorDB
from app.db.database import DB_PATH, get_db_conn

from .process_db import read_config
from .process_pipeline_helpers import PIPELINE_QUEUE_TIMEOUT_SEC, PIPELINE_TOTAL_TIMEOUT_SEC
from .process_shared import logger, parse_positive_int


class PipelineContext:
    """run_pipeline 各阶段共享的可变状态。"""

    def __init__(
        self,
        *,
        video_id: str,
        reporter: Any,
        skip_steps: list[str] | None,
        task_id: str | None,
        clip_ids_filter: frozenset[str] | None,
        video: dict,
        splitter: Any,
        loop: asyncio.AbstractEventLoop,
        cancel_event: Any,
    ) -> None:
        self.video_id = video_id
        self.reporter = reporter
        self.skip_steps = skip_steps or []
        self.task_id = task_id
        self.clip_ids_filter = clip_ids_filter
        self.video = video
        self.splitter = splitter
        self.loop = loop
        self.cancel_event = cancel_event

        self.pipeline_deadline = time.perf_counter() + PIPELINE_TOTAL_TIMEOUT_SEC
        self.t0 = time.perf_counter()
        self.step_start_ts: dict[str, float] = {}
        self.step_end_ts: dict[str, float] = {}
        self.metrics_errors: list[str] = []
        self.vlm_tokens = TokenAccumulator()
        self.llm_tokens = TokenAccumulator()
        self.embed_tokens = TokenAccumulator()

        self.total_clips = 0
        self.do_split = True
        self.do_frames = True
        self.do_asr = True
        self.do_vlm = True
        self.do_embed = True

        self.asr_instance = None
        self.vlm_instance = None
        self.embedder: Embedder | None = None
        self.vector_db: FaissVectorDB | None = None

        self.frame_done = self.frame_success = 0
        self.asr_done = self.asr_success = 0
        self.vlm_done = self.vlm_success = 0
        self.emb_done = self.emb_success = 0

        self.frame_queue: asyncio.Queue | None = None
        self.asr_queue: asyncio.Queue | None = None
        self.vlm_queue: asyncio.Queue | None = None
        self.embed_queue: asyncio.Queue | None = None
        self.vector_db_lock: asyncio.Lock | None = None
        self.progress_lock: asyncio.Lock | None = None
        self.vlm_enqueue_lock: asyncio.Lock | None = None
        self.all_workers: list[asyncio.Task] = []

        self.whisper_inprocess_transcribe = False
        self.embed_inprocess = True

        # 配置项（load_config 后填充）
        self.split_mode = "scene"
        self.scene_threshold = 0.4
        self.scene_min_scene_len = 30
        self.fixed_duration = 10.0
        self.hybrid_max_segment_sec = 60.0
        self.transcode_opts: dict[str, str] = {}
        self.asr_provider = "whisper"
        self.asr_model = "base"
        self.asr_base_url = ""
        self.asr_api_key = ""
        self.asr_openai_model = "whisper-1"
        self.asr_language = "zh"
        self.vlm_base_url = ""
        self.vlm_model = "gpt-4o"
        self.vlm_api_key = ""
        self.vector_dim = 1024
        self.frame_fps = 1.0
        self.frame_target_pixels = 0
        self.vlm_max_images = 10
        self.vlm_context_length = 65536
        self.asr_concurrency = 1
        self.frame_concurrency = 3
        self.vlm_concurrency = 3
        self.embedding_concurrency = 3
        self.embedding_base_url = ""
        self.embedding_api_key = ""
        self.embedding_model = "text-embedding-3-small"
        self.embedding_timeout_sec = 120.0

    def _now(self) -> float:
        return time.perf_counter()

    def ensure_step_start(self, step: str) -> None:
        if step not in self.step_start_ts:
            self.step_start_ts[step] = self._now()

    def ensure_step_end(self, step: str) -> None:
        if step not in self.step_end_ts and step in self.step_start_ts:
            self.step_end_ts[step] = self._now()

    def timing_ms_snapshot(self) -> dict:
        out: dict[str, int] = {}
        for s in ("split", "extract_frames", "asr", "vlm", "embed"):
            st = self.step_start_ts.get(s)
            ed = self.step_end_ts.get(s)
            out[s] = 0 if st is None else int(((ed or self._now()) - st) * 1000)
        out["total"] = int((self._now() - self.t0) * 1000)
        return out

    def metrics_snapshot(self) -> dict:
        return {
            "timing_ms": self.timing_ms_snapshot(),
            "tokens": {
                "vlm": self.vlm_tokens.to_dict(),
                "llm": self.llm_tokens.to_dict(),
                "embed": self.embed_tokens.to_dict(),
            },
            "errors": list(self.metrics_errors),
        }

    def remaining_timeout(self, cap_sec: float | None = None) -> float:
        remain = self.pipeline_deadline - time.perf_counter()
        if remain <= 0:
            raise TimeoutError(f"流水线总超时（>{int(PIPELINE_TOTAL_TIMEOUT_SEC)}s）")
        if cap_sec is None:
            return remain
        return max(0.1, min(cap_sec, remain))

    async def put_with_timeout(self, q: asyncio.Queue, item: Any, label: str) -> None:
        await asyncio.wait_for(q.put(item), timeout=self.remaining_timeout(PIPELINE_QUEUE_TIMEOUT_SEC))
        logger.debug("queue put ok: %s", label)

    async def join_with_timeout(self, q: asyncio.Queue, label: str) -> None:
        await asyncio.wait_for(q.join(), timeout=self.remaining_timeout(PIPELINE_QUEUE_TIMEOUT_SEC))
        logger.debug("queue join ok: %s", label)

    async def load_config(self) -> None:
        db = await get_db_conn()
        try:
            self.split_mode = await read_config(db, "split_mode", "scene")
            self.scene_threshold = float(await read_config(db, "scene_threshold", "0.4"))
            self.scene_min_scene_len = int(await read_config(db, "scene_min_scene_len", "30"))
            self.fixed_duration = float(await read_config(db, "fixed_duration", "10"))
            self.hybrid_max_segment_sec = float(await read_config(db, "hybrid_max_segment_sec", "60"))
            self.transcode_opts = {
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
            self.asr_provider = await read_config(db, "asr_provider", "whisper")
            self.asr_model = await read_config(db, "asr_model", "base")
            self.asr_base_url = await read_config(db, "asr_base_url", "https://api.openai.com/v1")
            self.asr_api_key = await read_config(db, "asr_api_key", "")
            self.asr_openai_model = await read_config(db, "asr_openai_model", "whisper-1")
            asr_language_raw = await read_config(db, "asr_language", "zh")
            self.asr_language = (asr_language_raw or "").strip()
            self.vlm_base_url = await read_config(db, "vlm_base_url", "https://api.openai.com/v1")
            self.vlm_model = await read_config(db, "vlm_model", "gpt-4o")
            self.vlm_api_key = await read_config(db, "vlm_api_key", "")
            self.vector_dim = int(await read_config(db, "vector_dimension", "1024"))
            self.frame_fps = float(await read_config(db, "frame_fps", "1"))
            self.frame_target_pixels = int(await read_config(db, "frame_target_pixels", "0"))
            frame_concurrency_raw = await read_config(db, "frame_concurrency", "3")
            self.vlm_max_images = int(await read_config(db, "vlm_max_images_per_batch", "10"))
            self.vlm_context_length = int(await read_config(db, "vlm_context_length", "65536"))
            asr_concurrency_raw = await read_config(db, "asr_concurrency", "1")
            vlm_concurrency_raw = await read_config(db, "vlm_concurrency", "3")
            embedding_concurrency_raw = await read_config(db, "embedding_concurrency", "3")
            self.asr_concurrency = parse_positive_int(asr_concurrency_raw, default=1, min_v=1, max_v=16)
            self.frame_concurrency = parse_positive_int(frame_concurrency_raw, default=3, min_v=1, max_v=16)
            self.vlm_concurrency = parse_positive_int(vlm_concurrency_raw, default=3, min_v=1, max_v=16)
            self.embedding_concurrency = parse_positive_int(embedding_concurrency_raw, default=3, min_v=1, max_v=16)
            self.embedding_base_url = await read_config(db, "embedding_base_url", "https://api.openai.com/v1")
            self.embedding_api_key = await read_config(db, "embedding_api_key", "")
            self.embedding_model = await read_config(db, "embedding_model", "text-embedding-3-small")
            self.embedding_timeout_sec = float(await read_config(db, "embedding_timeout_sec", "120"))
            if self.embedding_timeout_sec <= 0:
                self.embedding_timeout_sec = 120.0
        finally:
            await db.close()

        self.whisper_inprocess_transcribe = os.environ.get(
            "SMARTCLIP_WHISPER_INPROCESS_TRANSCRIBE", ""
        ).strip().lower() in ("1", "true", "yes")
        self.embed_inprocess = os.environ.get(
            "SMARTCLIP_EMBED_INPROCESS", "1"
        ).strip().lower() in ("1", "true", "yes")

    def init_queues(self) -> None:
        max_workers = max(
            self.frame_concurrency,
            self.asr_concurrency,
            self.vlm_concurrency,
            self.embedding_concurrency,
        )
        queue_maxsize = max(1, max_workers * 2)
        self.vector_db_lock = asyncio.Lock()
        self.progress_lock = asyncio.Lock()
        self.vlm_enqueue_lock = asyncio.Lock()
        self.frame_queue = asyncio.Queue(maxsize=queue_maxsize)
        self.asr_queue = asyncio.Queue(maxsize=queue_maxsize)
        self.vlm_queue = asyncio.Queue(maxsize=queue_maxsize)
        self.embed_queue = asyncio.Queue(maxsize=queue_maxsize)

    @property
    def video_path(self) -> str:
        return self.video["file_path"]
