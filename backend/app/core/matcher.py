import difflib
import logging
from typing import List, Optional

from app.utils.logging_utils import stage_log

logger = logging.getLogger(__name__)

# ASR 与文案最低相似度（SequenceMatcher），低于此值则改为「全部片段 0 分」兜底
_ASR_SIM_MIN = 0.06
# 候选过多时不调用 LLM，避免超长上下文
_LLM_MAX_CANDIDATES = 40


def _attach_media_urls(candidates: List[dict], api_base_url: str) -> None:
    base_url = api_base_url.rstrip("/") if api_base_url else ""
    for c in candidates:
        clip_id = c.get("clip_id")
        video_id = c.get("video_id")
        c["preview_url"] = (
            f"{base_url}/api/videos/clips/{clip_id}/stream"
            if base_url
            else f"/api/videos/clips/{clip_id}/stream"
        )
        c["thumbnail_url"] = (
            f"{base_url}/api/videos/{video_id}/thumbnail"
            if base_url
            else f"/api/videos/{video_id}/thumbnail"
        )


def _load_clips_for_videos(db_conn, video_ids: List[str]) -> List[dict]:
    placeholders = ",".join("?" * len(video_ids))
    rows = db_conn.execute(
        f"SELECT id AS clip_id, video_id, clip_path, start_time, end_time, "
        f"duration, asr_text, vlm_description "
        f"FROM clips WHERE video_id IN ({placeholders}) ORDER BY video_id, start_time",
        video_ids,
    ).fetchall()
    return [dict(r) for r in rows]


def _fetch_clips_by_ids(db_conn, clip_ids: List[str]) -> List[dict]:
    if not clip_ids:
        return []
    placeholders = ",".join("?" * len(clip_ids))
    rows = db_conn.execute(
        f"SELECT id AS clip_id, video_id, clip_path, start_time, end_time, "
        f"duration, asr_text, vlm_description "
        f"FROM clips WHERE id IN ({placeholders})",
        clip_ids,
    ).fetchall()
    row_map = {r["clip_id"]: dict(r) for r in rows}
    return [row_map[cid] for cid in clip_ids if cid in row_map]


def _asr_similarity_candidates(
    db_conn,
    query: str,
    video_ids: List[str],
    top_k: int,
) -> List[dict]:
    """向量无结果时，用 ASR 文本与文案的字符级相似度做候选（不依赖 VLM）。"""
    clips = _load_clips_for_videos(db_conn, video_ids)
    if not clips:
        return []
    q = query.strip()
    if not q:
        return []
    rated: List[tuple[float, dict]] = []
    for c in clips:
        a = (c.get("asr_text") or "").strip()
        r = difflib.SequenceMatcher(None, q, a).ratio() if a else 0.0
        rated.append((r, c))
    rated.sort(key=lambda x: x[0], reverse=True)
    if not rated or rated[0][0] < _ASR_SIM_MIN:
        return []
    out: List[dict] = []
    for r, c in rated:
        if r < _ASR_SIM_MIN:
            break
        if len(out) >= top_k:
            break
        mc = dict(c)
        mc["score"] = round(float(r) * 10.0, 3)
        mc["reason"] = "ASR 文本相似度（向量无结果或索引为空，未使用画面描述）"
        out.append(mc)
    return out


def _fallback_all_clips_zero_score(
    db_conn,
    query: str,
    video_ids: List[str],
) -> List[dict]:
    """所选视频的全部片段，统一 0 分；按与文案的 ASR 相似度排序便于口播场景挑选。"""
    clips = _load_clips_for_videos(db_conn, video_ids)
    q = (query or "").strip()
    if q:
        def _sim(c: dict) -> float:
            a = (c.get("asr_text") or "").strip()
            if not a:
                return 0.0
            return difflib.SequenceMatcher(None, q, a).ratio()

        clips.sort(key=_sim, reverse=True)
    for c in clips:
        c["score"] = 0.0
        c["reason"] = "向量检索无匹配，以下为所选视频全部片段（可按口播手动选用）"
    return clips


class Matcher:
    """
    三级匹配引擎

    Level 1 — 向量初筛：用 Embedder 将文案向量化，FAISS 检索 top_k 候选
    Level 2 — LLM 精排：将候选片段的 asr_text + vlm_description 送给 LLM 评分排序
    Level 3 — 返回结果：输出 top_n 推荐 + 完整候选列表

    兜底：向量无结果且指定了 video_ids 时，先用 ASR 文本相似度候选；仍不可用则返回该视频全部片段（0 分）。
    """

    def __init__(self, embedder, vector_db, llm=None):
        """
        Args:
            embedder:   Embedder 实例（文本 -> 向量）
            vector_db:  IVectorDB 实例（向量检索）
            llm:        ILLM 实例（精排），可为 None（跳过精排）
        """
        self.embedder = embedder
        self.vector_db = vector_db
        self.llm = llm

    def match(
        self,
        query: str,
        db_conn,
        top_k: int = 12,
        top_n: int = 5,
        video_ids: Optional[List[str]] = None,
        api_base_url: str = "",
    ) -> dict:
        """
        执行三级匹配。

        Args:
            query:     用户文案
            db_conn:   同步 sqlite3 连接（用于获取片段元数据）
            top_k:     向量初筛数量
            top_n:     最终推荐数量
            video_ids: 限定检索范围（None = 全部）

        Returns:
            {
                "query": str,
                "top_n": int,
                "recommended": [ {clip_id, video_id, clip_path, start_time, end_time,
                                    duration, asr_text, vlm_description, score, reason}, ... ],
                "candidates": [ ... ]   # 全部初筛候选（含精排分数）
            }
        """
        video_ids = [v for v in (video_ids or []) if v]

        # ── Level 1：向量初筛 ──────────────────────────────────────────
        stage_log("检索", f"向量初筛（top_k={top_k}）…", status="running")
        logger.info("[Matcher] Level-1 向量初筛: query_len=%d, top_k=%d", len(query), top_k)
        query_vec = self.embedder.embed(query)
        candidate_ids = self.vector_db.search(query_vec, top_k=top_k, video_ids=video_ids or None)

        candidates: List[dict] = _fetch_clips_by_ids(db_conn, candidate_ids) if candidate_ids else []
        used_full_fallback = False

        if not candidates and video_ids:
            logger.warning("[Matcher] 向量初筛无可用候选，尝试 ASR 文本相似度（不依赖 VLM）")
            candidates = _asr_similarity_candidates(db_conn, query, video_ids, top_k)
            if candidates:
                logger.info("[Matcher] ASR 相似度候选: %d 个", len(candidates))
            else:
                candidates = _fallback_all_clips_zero_score(db_conn, query, video_ids)
                used_full_fallback = bool(candidates)
                if used_full_fallback:
                    logger.warning(
                        "[Matcher] 向量与 ASR 强匹配均无结果，返回所选视频全部片段（0 分）共 %d 个",
                        len(candidates),
                    )
        elif not candidates:
            logger.warning("[Matcher] 向量初筛无结果且未限定 video_ids，无法展示素材列表")
            return {"query": query, "top_n": top_n, "recommended": [], "candidates": []}

        logger.info("[Matcher] 初筛候选: %d 个片段", len(candidates))

        skip_llm = used_full_fallback or len(candidates) > _LLM_MAX_CANDIDATES

        # ── Level 2：LLM 精排 ──────────────────────────────────────────
        if self.llm is not None and not skip_llm:
            stage_log("检索", f"LLM 精排 {len(candidates)} 个候选…", status="running")
            logger.info("[Matcher] Level-2 LLM 精排...")
            try:
                candidates = self.llm.rank(query, candidates)
            except Exception as e:
                logger.warning("[Matcher] LLM 精排异常，使用向量/ASR 排序: %s", e)
                for i, c in enumerate(candidates):
                    c.setdefault("score", round(1.0 - i * 0.05, 3))
                    c.setdefault("reason", "向量相似度排序")
        else:
            if skip_llm and self.llm is not None:
                logger.info(
                    "[Matcher] 跳过 LLM 精排（fallback=%s, candidates=%d）",
                    used_full_fallback,
                    len(candidates),
                )
            for i, c in enumerate(candidates):
                c.setdefault("score", round(1.0 - i * 0.05, 3))
                c.setdefault("reason", "向量相似度排序")

        # ── Level 3：补充预览/封面 URL 并返回 ───────────────────────────
        _attach_media_urls(candidates, api_base_url)

        # 全量 0 分兜底时须返回全部片段供手动选片；前端会优先展示 recommended
        recommended = candidates if used_full_fallback else candidates[:top_n]
        logger.info("[Matcher] 匹配完成: 推荐 %d 个，候选共 %d 个", len(recommended), len(candidates))
        return {
            "query": query,
            "top_n": top_n,
            "recommended": recommended,
            "candidates": candidates,
        }
