"""向量库清理辅助。

提供「按 clip_id 列表删除向量」的统一入口，供 delete_video / clear_clips_for_video
等删除路径调用，避免 SQLite 已删但向量库残留导致孤儿累积。

设计要点：
- 软失败：向量库不可用（faiss 未装 / 文件损坏）时只记日志，不抛异常，
  保证删除视频/片段的主流程不会被向量库拖垮。
- 一次性批量删除 + 单次 rebuild，避免 N 次 100MB 文件重写。
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Iterable, Optional

from app.db.database import DB_PATH

logger = logging.getLogger(__name__)


def purge_clip_vectors(
    clip_ids: Iterable[str],
    *,
    db_path: str = DB_PATH,
    vector_dimension: Optional[int] = None,
) -> int:
    """删除给定 clip_id 对应的向量。返回实际删除数量。

    - vector_dimension 为 None 时从 config 读取，读不到则用 1024。
    - 任何异常都吞掉并记 warning，不阻断调用方。
    """
    ids = [cid for cid in clip_ids if cid]
    if not ids:
        return 0

    try:
        if vector_dimension is None:
            vector_dimension = _read_vector_dimension(db_path)

        from app.core.vector_db.faiss_db import FaissVectorDB

        vdb = FaissVectorDB(db_path=db_path, vector_dimension=vector_dimension)
        return vdb.delete_embeddings(ids)
    except Exception as e:
        logger.warning("清理 clip 向量失败（已忽略，不阻断删除流程）: ids=%d err=%s", len(ids), e)
        return 0


def purge_video_vectors(
    video_id: str,
    *,
    db_path: str = DB_PATH,
    vector_dimension: Optional[int] = None,
) -> int:
    """删除某 video 下所有 clip 的向量。"""
    try:
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(
                "SELECT id FROM clips WHERE video_id = ?", (video_id,)
            ).fetchall()
        finally:
            conn.close()
        clip_ids = [r[0] for r in rows]
        if not clip_ids:
            return 0
        return purge_clip_vectors(clip_ids, db_path=db_path, vector_dimension=vector_dimension)
    except Exception as e:
        logger.warning("查询 video=%s 的 clip 列表失败: %s", video_id, e)
        return 0


def _read_vector_dimension(db_path: str) -> int:
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT value FROM config WHERE key = ?", ("vector_dimension",)
            ).fetchone()
            if row:
                return int(row[0])
        finally:
            conn.close()
    except Exception:
        pass
    return 1024
