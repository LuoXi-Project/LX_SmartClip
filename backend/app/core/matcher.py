import difflib
import logging
from typing import List, Literal, Optional, Tuple

from app.utils.logging_utils import stage_log

logger = logging.getLogger(__name__)

MatchMode = Literal["auto", "vector", "text", "llm_only"]

# 文本初筛至少返回的最低分（高于 0 即可进入候选，供 LLM 精排）
_TEXT_RECALL_FLOOR = 0.01
# 候选过多时不调用 LLM，避免超长上下文
_LLM_MAX_CANDIDATES = 40

VALID_MATCH_MODES = frozenset({"auto", "vector", "text", "llm_only"})


def resolve_match_mode(
    cfg_mode: str,
    *,
    has_embed_key: bool,
    has_vectors: bool,
    has_llm_key: bool,
) -> MatchMode:
    """解析有效匹配模式（auto 时按可用能力自动降级）。"""
    mode = (cfg_mode or "auto").strip().lower()
    if mode not in VALID_MATCH_MODES:
        mode = "auto"

    if mode != "auto":
        return mode  # type: ignore[return-value]

    if has_embed_key and has_vectors:
        return "vector"
    if has_llm_key:
        return "text"
    if has_embed_key:
        return "vector"
    return "text"


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


def _load_clips(db_conn, video_ids: Optional[List[str]] = None) -> List[dict]:
    if video_ids:
        return _load_clips_for_videos(db_conn, video_ids)
    rows = db_conn.execute(
        "SELECT id AS clip_id, video_id, clip_path, start_time, end_time, "
        "duration, asr_text, vlm_description "
        "FROM clips ORDER BY video_id, start_time"
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


def _text_sim(query: str, text: str) -> float:
    """中文友好文本相似度：子串命中 > 滑动窗口 > 字符覆盖 > 全局序列比。"""
    q = query.strip()
    t = text.strip()
    if not q or not t:
        return 0.0

    if q in t:
        return min(1.0, 0.78 + 0.22 * (len(q) / max(len(t), len(q))))

    q_cf, t_cf = q.casefold(), t.casefold()
    if q_cf in t_cf:
        return min(1.0, 0.74 + 0.22 * (len(q) / max(len(t), len(q))))

    q_len = len(q)
    best_window = 0.0
    if q_len <= len(t):
        for i in range(len(t) - q_len + 1):
            window = t[i : i + q_len]
            r = difflib.SequenceMatcher(None, q, window, autojunk=False).ratio()
            if r > best_window:
                best_window = r
                if r >= 0.95:
                    break

    q_chars = {c for c in q if not c.isspace()}
    char_cover = 0.0
    if q_chars:
        t_chars = {c for c in t if not c.isspace()}
        char_cover = len(q_chars & t_chars) / len(q_chars)

    global_ratio = difflib.SequenceMatcher(None, q, t, autojunk=False).quick_ratio()
    return max(best_window * 0.95, char_cover * 0.88, global_ratio * 0.35)


def _clip_text_score(
    query: str,
    clip: dict,
    *,
    weight_asr: float = 0.55,
    weight_vlm: float = 0.45,
) -> float:
    asr = (clip.get("asr_text") or "").strip()
    vlm = (clip.get("vlm_description") or "").strip()
    scores: List[float] = []
    weights: List[float] = []
    if asr:
        scores.append(_text_sim(query, asr))
        weights.append(weight_asr)
    if vlm:
        scores.append(_text_sim(query, vlm))
        weights.append(weight_vlm)
    if not scores:
        return 0.0
    total_w = sum(weights)
    weighted = sum(s * w for s, w in zip(scores, weights)) / total_w
    return max(weighted, max(scores))


def _text_similarity_candidates(
    db_conn,
    query: str,
    video_ids: Optional[List[str]],
    top_k: int,
    *,
    weight_asr: float = 0.55,
    weight_vlm: float = 0.45,
) -> List[dict]:
    """ASR + VLM 文本相似度初筛（不依赖向量库）。"""
    clips = _load_clips(db_conn, video_ids)
    if not clips:
        return []
    q = query.strip()
    if not q:
        return []

    rated: List[tuple[float, dict]] = []
    for c in clips:
        r = _clip_text_score(q, c, weight_asr=weight_asr, weight_vlm=weight_vlm)
        if r > 0:
            rated.append((r, c))
    rated.sort(key=lambda x: x[0], reverse=True)

    if not rated or rated[0][0] < _TEXT_RECALL_FLOOR:
        return []

    out: List[dict] = []
    for r, c in rated[:top_k]:
        mc = dict(c)
        mc["score"] = round(float(r) * 10.0, 3)
        mc["reason"] = "ASR/VLM 文本相似度（无向量检索）"
        out.append(mc)
    return out


def _fallback_all_clips_zero_score(
    db_conn,
    query: str,
    video_ids: List[str],
) -> List[dict]:
    """所选视频的全部片段，统一 0 分；按与文案的文本相似度排序便于手动选用。"""
    clips = _load_clips_for_videos(db_conn, video_ids)
    q = (query or "").strip()
    if q:
        clips.sort(key=lambda c: _clip_text_score(q, c), reverse=True)
    for c in clips:
        c["score"] = 0.0
        c["reason"] = "文本检索无强匹配，以下为所选视频全部片段（可手动选用）"
    return clips


class Matcher:
    """
    素材匹配引擎（多模式）

    - vector：Embedding 向量初筛 → LLM 精排
    - text：ASR/VLM 文本相似度初筛 → LLM 精排
    - llm_only：加载候选后直接 LLM 精排（过多时先文本压至 top_k）
    """

    def __init__(
        self,
        embedder=None,
        vector_db=None,
        llm=None,
        *,
        text_weight_asr: float = 0.55,
        text_weight_vlm: float = 0.45,
    ):
        self.embedder = embedder
        self.vector_db = vector_db
        self.llm = llm
        self.text_weight_asr = text_weight_asr
        self.text_weight_vlm = text_weight_vlm

    def _recall_on_vector_failure(
        self,
        query: str,
        db_conn,
        top_k: int,
        video_ids: Optional[List[str]],
        *,
        reason: str,
    ) -> Tuple[List[dict], bool]:
        """向量链路失败时的降级：优先 LLM 直接匹配，否则加宽文本初筛。"""
        logger.warning("[Matcher] %s，尝试降级检索", reason)
        clips = _load_clips(db_conn, video_ids)
        if self.llm and clips and len(clips) <= _LLM_MAX_CANDIDATES:
            logger.info(
                "[Matcher] %s，候选 %d 个 ≤ %d，改用 LLM 直接匹配",
                reason,
                len(clips),
                _LLM_MAX_CANDIDATES,
            )
            stage_log(
                "检索",
                f"{reason}，改用 LLM 匹配 {len(clips)} 个片段…",
                status="running",
            )
            return self._recall_llm_only(query, db_conn, top_k, video_ids)

        stage_log("检索", f"{reason}，降级为文本初筛…", status="running")
        widen_k = min(max(top_k * 3, top_k), _LLM_MAX_CANDIDATES)
        return self._recall_text(query, db_conn, widen_k, video_ids)

    def _recall_vector(
        self,
        query: str,
        db_conn,
        top_k: int,
        video_ids: Optional[List[str]],
    ) -> Tuple[List[dict], bool]:
        if self.embedder is None or self.vector_db is None:
            raise RuntimeError("向量匹配模式需要 embedder 与 vector_db")

        stage_log("检索", f"向量初筛（top_k={top_k}）…", status="running")
        logger.info("[Matcher] vector 初筛: query_len=%d, top_k=%d", len(query), top_k)
        try:
            query_vec = self.embedder.embed(query)
        except Exception as e:
            return self._recall_on_vector_failure(
                query, db_conn, top_k, video_ids, reason=f"Embedding 失败: {e}"
            )

        try:
            candidate_ids = self.vector_db.search(
                query_vec, top_k=top_k, video_ids=video_ids or None
            )
        except Exception as e:
            return self._recall_on_vector_failure(
                query, db_conn, top_k, video_ids, reason=f"向量检索失败: {e}"
            )

        candidates = _fetch_clips_by_ids(db_conn, candidate_ids) if candidate_ids else []
        used_full_fallback = False

        if not candidates and video_ids:
            logger.warning("[Matcher] 向量初筛无可用候选，尝试文本相似度兜底")
            candidates = _text_similarity_candidates(
                db_conn,
                query,
                video_ids,
                top_k,
                weight_asr=self.text_weight_asr,
                weight_vlm=self.text_weight_vlm,
            )
            if candidates:
                logger.info("[Matcher] 文本相似度候选: %d 个", len(candidates))
            else:
                candidates = _fallback_all_clips_zero_score(db_conn, query, video_ids)
                used_full_fallback = bool(candidates)
        elif not candidates:
            logger.warning("[Matcher] 向量初筛无结果且未限定 video_ids")
            return [], False

        return candidates, used_full_fallback

    def _recall_text(
        self,
        query: str,
        db_conn,
        top_k: int,
        video_ids: Optional[List[str]],
    ) -> Tuple[List[dict], bool]:
        stage_log("检索", f"文本初筛（ASR+VLM，top_k={top_k}）…", status="running")
        logger.info("[Matcher] text 初筛: query_len=%d, top_k=%d", len(query), top_k)
        candidates = _text_similarity_candidates(
            db_conn,
            query,
            video_ids,
            top_k,
            weight_asr=self.text_weight_asr,
            weight_vlm=self.text_weight_vlm,
        )
        used_full_fallback = False
        if not candidates and video_ids:
            candidates = _fallback_all_clips_zero_score(db_conn, query, video_ids)
            used_full_fallback = bool(candidates)
            if used_full_fallback:
                logger.warning(
                    "[Matcher] 文本初筛无强匹配，返回所选视频全部片段共 %d 个",
                    len(candidates),
                )
        return candidates, used_full_fallback

    def _recall_llm_only(
        self,
        query: str,
        db_conn,
        top_k: int,
        video_ids: Optional[List[str]],
    ) -> Tuple[List[dict], bool]:
        stage_log("检索", "纯 LLM 匹配：加载候选片段…", status="running")
        clips = _load_clips(db_conn, video_ids)
        if not clips:
            return [], False
        if len(clips) <= _LLM_MAX_CANDIDATES:
            logger.info("[Matcher] llm_only: 候选 %d 个，直接 LLM 精排", len(clips))
            return clips, False
        logger.info(
            "[Matcher] llm_only: 候选 %d 个，先文本压至 top_k=%d",
            len(clips),
            top_k,
        )
        narrowed = _text_similarity_candidates(
            db_conn,
            query,
            video_ids,
            top_k,
            weight_asr=self.text_weight_asr,
            weight_vlm=self.text_weight_vlm,
        )
        if narrowed:
            return narrowed, False
        if video_ids:
            return _fallback_all_clips_zero_score(db_conn, query, video_ids), True
        return clips[:top_k], False

    def match(
        self,
        query: str,
        db_conn,
        top_k: int = 12,
        top_n: int = 5,
        video_ids: Optional[List[str]] = None,
        api_base_url: str = "",
        mode: MatchMode = "vector",
    ) -> dict:
        video_ids = [v for v in (video_ids or []) if v]
        scoped_ids = video_ids or None

        if mode == "vector":
            candidates, used_full_fallback = self._recall_vector(
                query, db_conn, top_k, scoped_ids
            )
        elif mode == "text":
            candidates, used_full_fallback = self._recall_text(
                query, db_conn, top_k, scoped_ids
            )
        elif mode == "llm_only":
            candidates, used_full_fallback = self._recall_llm_only(
                query, db_conn, top_k, scoped_ids
            )
        else:
            raise ValueError(f"未知匹配模式: {mode}")

        if not candidates:
            return {"query": query, "top_n": top_n, "recommended": [], "candidates": []}

        logger.info("[Matcher] 初筛候选: %d 个片段 (mode=%s)", len(candidates), mode)

        force_llm = mode == "llm_only"
        skip_llm = not force_llm and len(candidates) > _LLM_MAX_CANDIDATES

        if self.llm is not None and (force_llm or not skip_llm):
            stage_log("检索", f"LLM 精排 {len(candidates)} 个候选…", status="running")
            logger.info("[Matcher] Level-2 LLM 精排...")
            try:
                candidates = self.llm.rank(query, candidates)
            except Exception as e:
                logger.warning("[Matcher] LLM 精排异常，使用初筛排序: %s", e)
                for i, c in enumerate(candidates):
                    c.setdefault("score", round(1.0 - i * 0.05, 3))
                    c.setdefault("reason", "初筛排序")
        else:
            if skip_llm and self.llm is not None:
                logger.info(
                    "[Matcher] 跳过 LLM 精排（候选过多: %d > %d）",
                    len(candidates),
                    _LLM_MAX_CANDIDATES,
                )
            default_reason = {
                "vector": "向量相似度排序",
                "text": "文本相似度排序",
                "llm_only": "候选排序",
            }.get(mode, "初筛排序")
            for i, c in enumerate(candidates):
                c.setdefault("score", round(1.0 - i * 0.05, 3))
                c.setdefault("reason", default_reason)

        _attach_media_urls(candidates, api_base_url)

        recommended = candidates if used_full_fallback else candidates[:top_n]
        logger.info(
            "[Matcher] 匹配完成 (mode=%s): 推荐 %d 个，候选共 %d 个",
            mode,
            len(recommended),
            len(candidates),
        )
        return {
            "query": query,
            "top_n": top_n,
            "recommended": recommended,
            "candidates": candidates,
        }
