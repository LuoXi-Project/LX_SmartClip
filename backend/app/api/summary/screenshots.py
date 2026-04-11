"""总结笔记：从原片截取帧并落盘，Markdown 内嵌本地图片路径。"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess

import aiosqlite

from app.utils.bin_paths import ffmpeg_bin

logger = logging.getLogger(__name__)

# backend/app/api/summary -> ../../../storage/summary_shots
_SUMMARY_DIR = os.path.dirname(__file__)
SUMMARY_SHOTS_ROOT = os.path.abspath(os.path.join(_SUMMARY_DIR, "..", "..", "..", "storage", "summary_shots"))

_SCREENSHOT_RE = re.compile(r"\*Screenshot-\[(\d{1,2}:\d{2}(?::\d{2})?)\]")


def time_token_to_seconds(t: str) -> float:
    try:
        parts = [int(x) for x in t.strip().split(":")]
    except ValueError:
        return 0.0
    if len(parts) == 2:
        return float(parts[0] * 60 + parts[1])
    if len(parts) == 3:
        return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    return 0.0


def _extract_frame_jpeg(video_path: str, t_sec: float, out_path: str, *, max_w: int = 1280) -> bool:
    if not video_path or not os.path.isfile(video_path):
        return False
    t_sec = max(0.0, float(t_sec))
    vf = f"scale={max_w}:-1"
    try:
        r = subprocess.run(
            [
                ffmpeg_bin(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                str(t_sec),
                "-i",
                video_path,
                "-frames:v",
                "1",
                "-vf",
                vf,
                "-q:v",
                "3",
                out_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode != 0:
            logger.warning("ffmpeg 截图失败 t=%s: %s", t_sec, (r.stderr or "")[:300])
            return False
        return os.path.isfile(out_path) and os.path.getsize(out_path) > 0
    except Exception as e:
        logger.warning("截图异常 t=%s: %s", t_sec, e)
        return False


def materialize_screenshot_placeholders(markdown: str, video_path: str, summary_id: str) -> str:
    """
    将 *Screenshot-[mm:ss] 替换为 ![...](/storage/summary_shots/{summary_id}/...jpg)。
    同一 summary 目录会先清空再写入（用于同 id 重跑，一般新 id 目录本为空）。
    """
    if not markdown or not video_path or not os.path.isfile(video_path):
        return markdown

    out_dir = os.path.join(SUMMARY_SHOTS_ROOT, summary_id)
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)
    os.makedirs(out_dir, exist_ok=True)

    counts: dict[int, int] = {}

    def repl(m: re.Match[str]) -> str:
        token = m.group(1)
        sec = time_token_to_seconds(token)
        sec_i = int(round(sec))
        counts[sec_i] = counts.get(sec_i, 0) + 1
        n = counts[sec_i]
        fname = f"s{sec_i}.jpg" if n == 1 else f"s{sec_i}_{n}.jpg"
        dest = os.path.join(out_dir, fname)
        if _extract_frame_jpeg(video_path, sec, dest):
            return f"![截图 @ {token}](/storage/summary_shots/{summary_id}/{fname})"
        return f"\n\n> **截图失败**（{token}）\n\n"

    return _SCREENSHOT_RE.sub(repl, markdown)


async def cleanup_previous_summary_shots_for_video(db: aiosqlite.Connection, video_id: str, mode: str) -> None:
    """
    同一视频再次生成前，删除「当前最新一条总结」的截图目录，避免磁盘堆积；
    注意：数据库里旧行若仍指向该目录，缩略图将失效（通常前端只展示最新一条）。
    """
    cur = await db.execute(
        """
        SELECT id FROM video_summaries
        WHERE video_id = ? AND mode = ?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (video_id, mode),
    )
    row = await cur.fetchone()
    if not row:
        return
    sid = row[0]
    d = os.path.join(SUMMARY_SHOTS_ROOT, sid)
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
        logger.info("已删除旧总结截图目录: %s", d)


async def delete_shots_for_summary_id(db: aiosqlite.Connection, summary_id: str) -> None:
    """删除指定总结 id 的截图目录（例如更新/删除总结时可选调用）。"""
    d = os.path.join(SUMMARY_SHOTS_ROOT, summary_id)
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
