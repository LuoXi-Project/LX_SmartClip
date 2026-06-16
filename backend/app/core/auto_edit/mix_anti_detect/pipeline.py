"""混剪防检测主管线：解码 → 画面/音频处理 → 调度循环 → 封装归档。"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.auto_edit.mix_anti_detect.audio import process_audio_file
from app.core.auto_edit.mix_anti_detect.ffmpeg_io import (
    copy_metadata_tags,
    extract_audio_wav,
    extract_video_raw,
    mux_av,
    probe_audio_duration,
    probe_media_info,
)
from app.core.auto_edit.mix_anti_detect.scheduler import AntiDetectScheduler
from app.core.auto_edit.mix_anti_detect.video import process_video_file
from app.models.auto_edit import MixAntiDetectConfig
from app.utils.logging_utils import stage_log
from app.utils.paths import ensure_storage_subpath

logger = logging.getLogger(__name__)


def _archive_dir() -> str:
    return ensure_storage_subpath("mix_anti_detect", "outputs")


def _log_dir() -> str:
    return ensure_storage_subpath("mix_anti_detect", "logs")


def _write_job_log(job_id: str, payload: dict[str, Any]) -> str:
    os.makedirs(_log_dir(), exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(_log_dir(), f"{ts}_{job_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def run_anti_detect_pipeline(
    input_path: str,
    cfg: MixAntiDetectConfig,
    *,
    job_id: str | None = None,
) -> tuple[str, str]:
    """
    执行完整防检测管线。
    返回 (成品路径, 日志路径)。
    """
    job_id = job_id or uuid.uuid4().hex[:10]
    scheduler = AntiDetectScheduler(cfg)
    fmt = scheduler.output_format()

    work_root = ensure_storage_subpath("mix_anti_detect", "work", job_id)
    os.makedirs(work_root, exist_ok=True)

    log_record: dict[str, Any] = {
        "job_id": job_id,
        "input": os.path.abspath(input_path),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "base_seed": scheduler.base_seed,
        "iterations": [],
        "output_format": fmt,
    }

    stage_log("混剪防检测", f"任务 {job_id} 开始解码分离", status="running")
    t0 = time.time()

    src_info = probe_media_info(input_path)
    log_record["source_probe"] = src_info

    current_video = input_path
    current_audio: str | None = extract_audio_wav(input_path, work_root)

    iterations = scheduler.iterations()
    last_video_work = current_video

    for it in range(1, iterations + 1):
        iter_dir = os.path.join(work_root, f"iter_{it}")
        os.makedirs(iter_dir, exist_ok=True)

        if it == 1:
            vid_src, vid_info = extract_video_raw(
                current_video,
                iter_dir,
                fps=float(src_info.get("fps") or 30.0),
            )
        else:
            vid_src = last_video_work
            vid_info = probe_media_info(vid_src)

        total_frames = max(1, int(float(vid_info.get("duration_sec") or 0) * float(vid_info.get("fps") or 30)))
        if current_audio and os.path.isfile(current_audio):
            audio_dur = probe_audio_duration(current_audio)
        else:
            audio_dur = float(src_info.get("duration_sec") or 0)

        params = scheduler.build_params(
            iteration=it,
            total_frames=total_frames,
            audio_duration_sec=audio_dur,
        )
        iter_log = scheduler.summary_dict(params)
        iter_log["step"] = it

        stage_log(
            "混剪防检测",
            f"任务 {job_id} 第 {it}/{iterations} 轮 画面+音频扰动 (gain={params.gain:.2f})",
            status="running",
        )

        processed_video = os.path.join(iter_dir, "video_processed.mp4")
        process_video_file(
            vid_src,
            processed_video,
            cfg.video,
            params,
            fps=float(vid_info.get("fps") or 30.0),
        )
        last_video_work = processed_video

        if current_audio and os.path.isfile(current_audio):
            current_audio = process_audio_file(
                current_audio,
                cfg.audio,
                params,
                iter_dir,
            )

        iter_log["video_out"] = processed_video
        iter_log["audio_out"] = current_audio
        log_record["iterations"].append(iter_log)

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    out_name = f"{base_name}_ad_{job_id}.{fmt}"
    archive_path = os.path.join(_archive_dir(), out_name)

    mux_av(
        last_video_work,
        current_audio,
        archive_path,
        output_format=fmt,
    )
    copy_metadata_tags(input_path, archive_path)

    elapsed = round(time.time() - t0, 2)
    log_record["finished_at"] = datetime.now(timezone.utc).isoformat()
    log_record["elapsed_sec"] = elapsed
    log_record["output"] = archive_path
    log_path = _write_job_log(job_id, log_record)

    stage_log(
        "混剪防检测",
        f"任务 {job_id} 完成 → {out_name}（{elapsed}s）",
        status="done",
    )

    try:
        shutil.rmtree(work_root, ignore_errors=True)
    except Exception:
        pass

    return archive_path, log_path
