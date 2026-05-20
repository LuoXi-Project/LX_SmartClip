from __future__ import annotations

import logging
from typing import Dict, List, Tuple

import numpy as np

from app.core.embedder import Embedder
from app.core.vector_db.faiss_db import FaissVectorDB
from app.models.film_commentary import FilmAlignment, FilmSentence

logger = logging.getLogger(__name__)

_MIN_SIM = 0.22
_BACKTRACK_SEC = 45.0


def _cosine(a: List[float], b: List[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


async def align_sentences_to_clips(
    *,
    sentences: List[FilmSentence],
    clips: List[dict],
    video_id: str,
    embedder: Embedder,
    vector_db: FaissVectorDB,
    top_k: int,
) -> List[FilmAlignment]:
    """L4：分句语义匹配 + 时序单调约束。"""
    clip_by_id: Dict[str, dict] = {c["id"]: c for c in clips}
    cursor = 0.0
    alignments: List[FilmAlignment] = []

    for sent in sentences:
        q = sent.text.strip()
        if not q:
            continue
        q_vec = embedder.embed(q)
        candidate_ids = vector_db.search(q_vec, top_k=top_k, video_ids=[video_id])

        # 向量库无命中时，按 ASR 字符相似度兜底
        if not candidate_ids:
            import difflib

            rated: List[Tuple[float, dict]] = []
            for c in clips:
                a = (c.get("asr_text") or "").strip()
                r = difflib.SequenceMatcher(None, q, a).ratio() if a else 0.0
                rated.append((r, c))
            rated.sort(key=lambda x: x[0], reverse=True)
            candidate_ids = [c["id"] for r, c in rated[:top_k] if r >= 0.05]

        best_clip: dict | None = None
        best_score = -1.0
        best_reason = ""

        for rank, cid in enumerate(candidate_ids):
            c = clip_by_id.get(cid)
            if not c:
                continue
            st = float(c.get("start_time") or 0)
            emb = vector_db.get_embedding(cid)
            if emb:
                sem = _cosine(q_vec, emb)
                reason = "向量语义"
            else:
                # 无向量：用排名衰减
                sem = max(0.15, 0.85 - rank * 0.06)
                reason = "顺序兜底"

            temporal = 1.0
            if st < cursor - _BACKTRACK_SEC:
                temporal = 0.35
            elif st < cursor:
                temporal = 0.65
            elif st >= cursor:
                temporal = 1.0

            score = sem * 0.78 + temporal * 0.22
            if score > best_score:
                best_score = score
                best_clip = c
                best_reason = f"{reason} score={score:.3f}"

        if not best_clip:
            # 取 cursor 之后第一个切片
            for c in clips:
                if float(c.get("start_time") or 0) >= cursor - 1.0:
                    best_clip = c
                    best_reason = "时序顺延"
                    best_score = 0.1
                    break
        if not best_clip:
            continue

        if best_score < _MIN_SIM:
            logger.info("句子 #%s 相似度偏低仍采用: %s", sent.index, best_reason)

        alignments.append(
            FilmAlignment(
                sentence_index=sent.index,
                clip_id=best_clip["id"],
                video_id=video_id,
                start_time=float(best_clip.get("start_time") or 0),
                end_time=float(best_clip.get("end_time") or 0),
                score=round(best_score, 4),
                reason=best_reason,
            )
        )
        cursor = max(cursor, float(best_clip.get("end_time") or cursor))

    return alignments
