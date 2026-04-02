from __future__ import annotations

import json
import os
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from app.models.bgm import BgmTrack, BgmUpdatePayload

router = APIRouter(prefix="/api/bgm", tags=["bgm"])

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_BGM_DIR = os.path.join(_BACKEND_DIR, "storage", "bgm")
_BGM_MANIFEST_PATH = os.path.join(_BGM_DIR, "bgm_manifest.json")
_BGM_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")
_WIN_INVALID = '<>:"/\\|?*'


def _sanitize_bgm_stem(original_filename: str) -> str:
    """从上传名得到安全的文件主名（不含扩展名），便于在素材目录中辨认。"""
    base = os.path.basename(original_filename or "").strip()
    stem = os.path.splitext(base)[0].strip() or "track"
    for ch in _WIN_INVALID:
        stem = stem.replace(ch, "_")
    stem = stem.strip(". \t") or "track"
    if len(stem) > 180:
        stem = stem[:180].rstrip(". ")
    return stem


def _unique_storage_filename(stem: str, ext: str) -> str:
    """在 storage/bgm 下生成不冲突的存储文件名（优先保留 stem + 原扩展名）。"""
    candidate = f"{stem}{ext}"
    dest = os.path.join(_BGM_DIR, candidate)
    if not os.path.isfile(dest):
        return candidate
    n = 1
    while True:
        candidate = f"{stem} ({n}){ext}"
        dest = os.path.join(_BGM_DIR, candidate)
        if not os.path.isfile(dest):
            return candidate
        n += 1


def _ensure_dir() -> None:
    os.makedirs(_BGM_DIR, exist_ok=True)


def _load_manifest() -> List[dict]:
    if not os.path.isfile(_BGM_MANIFEST_PATH):
        return []
    try:
        with open(_BGM_MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict) and isinstance(data.get("tracks"), list):
            return [x for x in data["tracks"] if isinstance(x, dict)]
    except Exception:
        return []
    return []


def _save_manifest(items: List[dict]) -> None:
    _ensure_dir()
    with open(_BGM_MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def _scan_files() -> List[str]:
    if not os.path.isdir(_BGM_DIR):
        return []
    out: List[str] = []
    for name in os.listdir(_BGM_DIR):
        if name.lower().endswith(_BGM_EXTS) and os.path.isfile(os.path.join(_BGM_DIR, name)):
            out.append(name)
    return sorted(out)


def _build_track_list() -> List[BgmTrack]:
    files = _scan_files()
    manifest = _load_manifest()
    by_id = {str(item.get("id")): item for item in manifest if item.get("id")}

    # 也允许通过 path/filename 匹配
    by_filename: dict[str, dict] = {}
    for item in manifest:
        path = str(item.get("path") or "").strip()
        if path:
            by_filename[os.path.basename(path)] = item

    tracks: List[BgmTrack] = []
    for filename in files:
        meta = None
        # 先试 id 映射，再试 path/filename
        for item in manifest:
            if os.path.basename(str(item.get("path") or "")) == filename:
                meta = item
                break
        if not meta:
            meta = {}
        track_id = str(meta.get("id") or uuid.uuid4().hex)
        title = str(meta.get("title") or os.path.splitext(filename)[0])
        mood = meta.get("mood") or None
        bpm_raw = meta.get("bpm")
        try:
            bpm = float(bpm_raw) if bpm_raw is not None else None
        except Exception:
            bpm = None
        tags_val = meta.get("tags") or []
        if isinstance(tags_val, str):
            tags = [t.strip() for t in tags_val.split(",") if t.strip()]
        elif isinstance(tags_val, list):
            tags = [str(t).strip() for t in tags_val if str(t).strip()]
        else:
            tags = []
        url = f"/storage/bgm/{filename}"
        tracks.append(
            BgmTrack(
                id=track_id,
                title=title,
                mood=str(mood) if mood else None,
                bpm=bpm,
                tags=tags,
                filename=filename,
                url=url,
            )
        )
    return tracks


def _upsert_manifest_from_tracks(tracks: List[BgmTrack]) -> None:
    items: List[dict] = []
    for t in tracks:
        items.append(
            {
                "id": t.id,
                "title": t.title,
                "path": t.filename,
                "mood": t.mood,
                "bpm": t.bpm,
                "tags": t.tags,
            }
        )
    _save_manifest(items)


@router.get("/tracks", response_model=List[BgmTrack])
async def list_tracks() -> List[BgmTrack]:
    """列出本地 BGM 音乐库（基于 storage/bgm + manifest 合并）"""
    return _build_track_list()


@router.post("/upload", response_model=BgmTrack)
async def upload_track(
    file: UploadFile = File(...),
    client_filename: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    mood: Optional[str] = Form(None),
    bpm: Optional[float] = Form(None),
    tags: Optional[str] = Form(None),
) -> BgmTrack:
    """上传新的 BGM 音频并写入 manifest。"""
    _ensure_dir()
    name_hint = (file.filename or client_filename or "").strip()
    if not name_hint:
        raise HTTPException(status_code=400, detail="无法识别文件名（请检查浏览器 multipart 是否正常）")
    ext = os.path.splitext(name_hint)[1].lower()
    if ext not in _BGM_EXTS:
        raise HTTPException(status_code=400, detail="不支持的音频格式")

    stem = _sanitize_bgm_stem(name_hint)
    filename = _unique_storage_filename(stem, ext)
    dest = os.path.join(_BGM_DIR, filename)
    content = await file.read()
    with open(dest, "wb") as f:
        f.write(content)

    tracks = _build_track_list()
    # 扫描结果会为刚写入的文件生成一条无 manifest 的临时行，避免与下面 append 重复
    tracks = [t for t in tracks if t.filename != filename]
    new_id = uuid.uuid4().hex
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    new_track = BgmTrack(
        id=new_id,
        title=title or os.path.splitext(name_hint)[0],
        mood=mood or None,
        bpm=bpm,
        tags=tag_list,
        filename=filename,
        url=f"/storage/bgm/{filename}",
    )
    tracks.append(new_track)
    _upsert_manifest_from_tracks(tracks)
    return new_track


@router.patch("/tracks/{track_id}", response_model=BgmTrack)
async def update_track(track_id: str, payload: BgmUpdatePayload) -> BgmTrack:
    """更新 BGM 元数据（标题/情绪/BPM/标签）。"""
    tracks = _build_track_list()
    found = None
    for t in tracks:
        if t.id == track_id:
            found = t
            break
    if not found:
        raise HTTPException(status_code=404, detail="BGM 不存在")

    if payload.title is not None:
        found.title = payload.title
    if payload.mood is not None:
        found.mood = payload.mood or None
    if payload.bpm is not None:
        found.bpm = payload.bpm
    if payload.tags is not None:
        found.tags = [str(t).strip() for t in payload.tags if str(t).strip()]

    _upsert_manifest_from_tracks(tracks)
    return found


@router.delete("/tracks/{track_id}")
async def delete_track(track_id: str) -> dict:
    """删除 BGM：同时删除音频文件和 manifest 条目。"""
    tracks = _build_track_list()
    remaining: List[BgmTrack] = []
    deleted: Optional[BgmTrack] = None
    for t in tracks:
        if t.id == track_id:
            deleted = t
        else:
            remaining.append(t)
    if not deleted:
        raise HTTPException(status_code=404, detail="BGM 不存在")

    # 删除物理文件（失败不算致命）
    try:
        path = os.path.join(_BGM_DIR, deleted.filename)
        if os.path.isfile(path):
            os.remove(path)
    except Exception:
        pass

    _upsert_manifest_from_tracks(remaining)
    return {"status": "ok"}

