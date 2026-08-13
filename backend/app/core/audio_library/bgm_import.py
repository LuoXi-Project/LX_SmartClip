"""BGM 库入库公共逻辑（供 BGM 上传 API 和音频库爬虫 worker 共用）。

从 api/bgm.py 抽取，保持单一数据源：音频文件落 storage/bgm/，元数据写 bgm_manifest.json。
爬虫 worker 下载完一首歌后调 import_audio_file() 把音频纳入 BGM 库。
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.models.bgm import BgmTrack
from app.utils.paths import ensure_storage_subpath, storage_subpath

logger = logging.getLogger("audio_library.bgm_import")

BGM_DIR = ensure_storage_subpath("bgm")
BGM_MANIFEST_PATH = os.path.join(BGM_DIR, "bgm_manifest.json")
BGM_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")
_WIN_INVALID = '<>:"/\\|?*'


def sanitize_bgm_stem(original_filename: str) -> str:
    """从文件名得到安全的文件主名（不含扩展名）。"""
    base = os.path.basename(original_filename or "").strip()
    stem = os.path.splitext(base)[0].strip() or "track"
    for ch in _WIN_INVALID:
        stem = stem.replace(ch, "_")
    stem = stem.strip(". \t") or "track"
    if len(stem) > 180:
        stem = stem[:180].rstrip(". ")
    return stem


def unique_storage_filename(stem: str, ext: str) -> str:
    """在 storage/bgm 下生成不冲突的存储文件名。"""
    candidate = f"{stem}{ext}"
    dest = os.path.join(BGM_DIR, candidate)
    if not os.path.isfile(dest):
        return candidate
    n = 1
    while True:
        candidate = f"{stem} ({n}){ext}"
        dest = os.path.join(BGM_DIR, candidate)
        if not os.path.isfile(dest):
            return candidate
        n += 1


def estimate_bpm(audio_path: str) -> Optional[float]:
    """基于音频包络自相关估算 BPM。失败返回 None。"""
    try:
        import numpy as np
        from moviepy import AudioFileClip
        fps = 22050
        hop = 512
        min_bpm, max_bpm = 60.0, 200.0
        max_seconds = 120.0

        with AudioFileClip(audio_path) as clip:
            if clip.duration is None or clip.duration <= 0:
                return None
            end_sec = min(float(clip.duration), max_seconds)
            if hasattr(clip, "subclipped"):
                seg = clip.subclipped(0, end_sec)
            else:
                seg = clip.subclip(0, end_sec)
            samples = seg.to_soundarray(fps=fps)

        if samples.size == 0:
            return None

        mono = samples.mean(axis=1) if samples.ndim > 1 else samples
        n_frames = len(mono) // hop
        if n_frames < 32:
            return None

        trimmed = mono[: n_frames * hop].reshape(n_frames, hop)
        envelope = np.mean(np.abs(trimmed), axis=1).astype(np.float64)
        envelope = envelope - envelope.mean()
        std = envelope.std()
        if std <= 1e-8:
            return None
        envelope = envelope / std

        env_rate = fps / hop
        min_lag = max(1, int(round((60.0 / max_bpm) * env_rate)))
        max_lag = int(round((60.0 / min_bpm) * env_rate))
        if max_lag <= min_lag:
            return None

        corr = np.correlate(envelope, envelope, mode="full")
        corr = corr[len(corr) // 2:]
        if len(corr) <= max_lag:
            return None

        window = corr[min_lag: max_lag + 1]
        if window.size == 0:
            return None
        best_lag = int(np.argmax(window)) + min_lag
        bpm = 60.0 * env_rate / best_lag
        while bpm < 70:
            bpm *= 2
        while bpm > 180:
            bpm /= 2
        return round(float(bpm), 1)
    except Exception:
        return None


def load_manifest() -> list[dict]:
    """读取 bgm_manifest.json。损坏则备份并回退空。"""
    if not os.path.isfile(BGM_MANIFEST_PATH):
        return []
    try:
        with open(BGM_MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict) and isinstance(data.get("tracks"), list):
            return [x for x in data["tracks"] if isinstance(x, dict)]
    except (json.JSONDecodeError, OSError) as e:
        logger.error("BGM manifest 损坏，回退为空: path=%s err=%s", BGM_MANIFEST_PATH, e)
        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            backup = f"{BGM_MANIFEST_PATH}.corrupt.{ts}"
            os.replace(BGM_MANIFEST_PATH, backup)
        except OSError:
            pass
        return []
    return []


def save_manifest(items: list[dict]) -> None:
    """原子写 manifest（先 .tmp 再 os.replace）。"""
    os.makedirs(BGM_DIR, exist_ok=True)
    tmp = BGM_MANIFEST_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    os.replace(tmp, BGM_MANIFEST_PATH)


def import_audio_file(
    *,
    src_audio_path: str,
    title: str,
    tags: Optional[list[str]] = None,
    mood: Optional[str] = None,
    preferred_filename: Optional[str] = None,
    move: bool = True,
) -> BgmTrack:
    """把一个已下载的音频文件纳入 BGM 库。

    流程：
    1. 按 preferred_filename 或 title 生成 storage/bgm 下不冲突的文件名
    2. move=True 时移动文件（爬虫下载到临时目录的场景）；False 时复制
    3. 估算 BPM
    4. append manifest 条目并原子写

    返回新建的 BgmTrack。文件名冲突会自动加 (n) 后缀。
    """
    tags = tags or []
    ext = os.path.splitext(src_audio_path)[1].lower()
    if ext not in BGM_EXTS:
        ext = ".mp3"  # 兜底
    stem = sanitize_bgm_stem(preferred_filename or title)
    filename = unique_storage_filename(stem, ext)
    dest = os.path.join(BGM_DIR, filename)

    if move:
        import shutil
        shutil.move(src_audio_path, dest)
    else:
        import shutil
        shutil.copy2(src_audio_path, dest)

    bpm = estimate_bpm(dest)
    new_id = uuid.uuid4().hex
    new_track = BgmTrack(
        id=new_id,
        title=title,
        mood=mood,
        bpm=bpm,
        tags=list(tags),
        filename=filename,
        url=f"/storage/bgm/{filename}",
    )

    # 合并写入 manifest：读现有 → 追加新条目 → 原子写
    items = load_manifest()
    items.append({
        "id": new_id,
        "title": title,
        "path": filename,
        "mood": mood,
        "bpm": bpm,
        "tags": list(tags),
    })
    save_manifest(items)
    logger.info("音频已纳入 BGM 库: %s -> %s (bpm=%s)", title, filename, bpm)
    return new_track


def manifest_has_source_id(source: str, source_id: str) -> bool:
    """检查 BGM manifest 里是否已存在某源某 id 的歌曲（按 tags 里的 source:source_id 标记去重）。"""
    marker = f"{source}:{source_id}"
    for item in load_manifest():
        tags = item.get("tags") or []
        if isinstance(tags, list) and marker in tags:
            return True
    return False
