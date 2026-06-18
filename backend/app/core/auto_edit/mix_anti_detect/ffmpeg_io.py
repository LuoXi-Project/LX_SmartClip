"""FFmpeg 解码分离与重新封装。"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any

from app.utils.bin_paths import ffprobe_bin
from app.utils.ffmpeg_utils import run_ffmpeg
from app.utils.ffprobe_utils import probe_duration, probe_video_dimensions

logger = logging.getLogger(__name__)


def has_video_stream(path: str) -> bool:
    probe = subprocess.run(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    return (probe.stdout.decode(errors="replace") or "").strip() == "video"


def probe_audio_duration(path: str) -> float:
    return float(probe_duration(path) or 0.0)


def probe_media_info(path: str) -> dict[str, Any]:
    dur = float(probe_duration(path) or 0.0)
    has_video = has_video_stream(path)
    if has_video:
        w, h = probe_video_dimensions(path, default=(1920, 1080), logger_=logger)
    else:
        w, h = 0, 0
    fps = 30.0
    if not has_video:
        return {"duration_sec": dur, "width": w, "height": h, "fps": fps}
    try:
        probe = subprocess.run(
            [
                ffprobe_bin(),
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=r_frame_rate,nb_frames",
                "-of",
                "json",
                path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        data = json.loads(probe.stdout.decode(errors="replace") or "{}")
        streams = data.get("streams") or []
        if streams:
            rate = str(streams[0].get("r_frame_rate") or "30/1")
            if "/" in rate:
                num, den = rate.split("/", 1)
                den_f = float(den) if float(den) else 1.0
                fps = float(num) / den_f if den_f else 30.0
            nb = streams[0].get("nb_frames")
            if nb and dur <= 0:
                dur = float(nb) / max(fps, 1.0)
    except Exception as e:
        logger.debug("probe fps failed: %s", e)
    return {"duration_sec": dur, "width": w, "height": h, "fps": fps}


def has_audio_stream(path: str) -> bool:
    probe = subprocess.run(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    return (probe.stdout.decode(errors="replace") or "").strip() == "audio"


def extract_video_raw(input_path: str, work_dir: str, *, fps: float) -> tuple[str, dict[str, Any]]:
    """分离视频轨为中间 mp4（便于 OpenCV 读取）。"""
    os.makedirs(work_dir, exist_ok=True)
    out = os.path.join(work_dir, "video_track.mp4")
    run_ffmpeg(
        [
            "-i",
            input_path,
            "-an",
            "-vf",
            f"fps={fps:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "16",
            "-pix_fmt",
            "yuv420p",
            out,
        ],
        desc="anti-detect extract video",
    )
    info = probe_media_info(out)
    return out, info


def extract_audio_wav(input_path: str, work_dir: str) -> str | None:
    if not has_audio_stream(input_path):
        return None
    os.makedirs(work_dir, exist_ok=True)
    out = os.path.join(work_dir, "audio_track.wav")
    run_ffmpeg(
        [
            "-i",
            input_path,
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            out,
        ],
        desc="anti-detect extract audio",
    )
    return out


def mux_av(
    video_path: str,
    audio_path: str | None,
    output_path: str,
    *,
    output_format: str,
) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    args = ["-i", video_path]
    if audio_path and os.path.isfile(audio_path):
        args += ["-i", audio_path, "-map", "0:v:0", "-map", "1:a:0"]
    else:
        args += ["-map", "0:v:0"]

    # 防检测不依赖编码精度：用 veryfast（与全站默认对齐）提速，medium 过慢。
    vcodec = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
    if audio_path and os.path.isfile(audio_path):
        acodec = ["-c:a", "aac", "-b:a", "192k"]
    else:
        acodec = []

    if output_format == "mkv":
        args += vcodec + acodec + ["-f", "matroska", output_path]
    else:
        args += vcodec + acodec + ["-movflags", "+faststart", output_path]

    run_ffmpeg(args, desc=f"anti-detect mux {output_format}")
    return output_path


def copy_metadata_tags(src: str, dst: str) -> None:
    """尽力复制容器元数据（非关键路径）。"""
    try:
        meta_path = dst + ".meta.json"
        probe = subprocess.run(
            [ffprobe_bin(), "-v", "quiet", "-show_format", "-of", "json", src],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(probe.stdout.decode(errors="replace"))
    except Exception:
        pass
