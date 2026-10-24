import difflib
import json
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


def _parse_json_list(raw: Optional[str]) -> List[str]:
    """把 clips.keywords / emotion_tags 的 JSON 字符串解析为 list[str]，失败返回 []。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(data, list):
        return [str(x).strip() for x in data if str(x).strip()]
    return []


def _normalize_clip_rows(rows) -> List[dict]:
    """把 DB 行 dict 标准化：解析 keywords/emotion_tags 的 JSON 字符串为 list。"""
    out: List[dict] = []
    for r in rows:
        d = dict(r)
        d["keywords"] = _parse_json_list(d.get("keywords"))
        d["emotion_tags"] = _parse_json_list(d.get("emotion_tags"))
        out.append(d)
    return out


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
        f"duration, asr_text, vlm_description, abstract_summary, keywords, emotion_tags "
        f"FROM clips WHERE video_id IN ({placeholders}) ORDER BY video_id, start_time",
        video_ids,
    ).fetchall()
    return _normalize_clip_rows(rows)


def _load_clips(db_conn, video_ids: Optional[List[str]] = None) -> List[dict]:
    if video_ids:
        return _load_clips_for_videos(db_conn, video_ids)
    rows = db_conn.execute(
        "SELECT id AS clip_id, video_id, clip_path, start_time, end_time, "
        "duration, asr_text, vlm_description, abstract_summary, keywords, emotion_tags "
        "FROM clips ORDER BY video_id, start_time"
    ).fetchall()
    return _normalize_clip_rows(rows)


def _fetch_clips_by_ids(db_conn, clip_ids: List[str]) -> List[dict]:
    if not clip_ids:
        return []
    placeholders = ",".join("?" * len(clip_ids))
    rows = db_conn.execute(
        f"SELECT id AS clip_id, video_id, clip_path, start_time, end_time, "
        f"duration, asr_text, vlm_description, abstract_summary, keywords, emotion_tags "
        f"FROM clips WHERE id IN ({placeholders})",
        clip_ids,
    ).fetchall()
    row_map = {r["clip_id"]: _norm_one(r) for r in rows}
    return [row_map[cid] for cid in clip_ids if cid in row_map]


def _norm_one(row) -> dict:
    """单个行的标准化（用于保持顺序的 _fetch_clips_by_ids）。"""
    d = dict(row)
    d["keywords"] = _parse_json_list(d.get("keywords"))
    d["emotion_tags"] = _parse_json_list(d.get("emotion_tags"))
    return d


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
    weight_asr: float = 0.30,
    weight_vlm: float = 0.25,
    weight_summary: float = 0.30,
    weight_tags: float = 0.15,
) -> float:
    """ASR / VLM / 旁白适配摘要 / 关键词+情绪 四路加权文本相似度。

    abstract_summary 给较高权重，因为它由 LLM 专门为「对齐旁白抽象层」生成，
    是抹平「旁白 ↔ 画面」表征鸿沟的关键信号；无 enrich 数据时自动退化为原两路。
    """
    asr = (clip.get("asr_text") or "").strip()
    vlm = (clip.get("vlm_description") or "").strip()
    summary = (clip.get("abstract_summary") or "").strip()
    tags_text = " ".join(
        (clip.get("keywords") or []) + (clip.get("emotion_tags") or [])
    ).strip()

    scores: List[float] = []
    weights: List[float] = []
    if asr:
        scores.append(_text_sim(query, asr))
        weights.append(weight_asr)
    if vlm:
        scores.append(_text_sim(query, vlm))
        weights.append(weight_vlm)
    if summary:
        scores.append(_text_sim(query, summary))
        weights.append(weight_summary)
    if tags_text:
        scores.append(_text_sim(query, tags_text))
        weights.append(weight_tags)
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
    weight_asr: float = 0.30,
    weight_vlm: float = 0.25,
    weight_summary: float = 0.30,
    weight_tags: float = 0.15,
) -> List[dict]:
    """ASR + VLM + 旁白适配摘要 + 关键词/情绪 四路文本相似度初筛（不依赖向量库）。"""
    clips = _load_clips(db_conn, video_ids)
    if not clips:
        return []
    q = query.strip()
    if not q:
        return []

    rated: List[tuple[float, dict]] = []
    for c in clips:
        r = _clip_text_score(
            q,
            c,
            weight_asr=weight_asr,
            weight_vlm=weight_vlm,
            weight_summary=weight_summary,
            weight_tags=weight_tags,
        )
        if r > 0:
            rated.append((r, c))
    rated.sort(key=lambda x: x[0], reverse=True)

    if not rated or rated[0][0] < _TEXT_RECALL_FLOOR:
        return []

    out: List[dict] = []
    for r, c in rated[:top_k]:
        mc = dict(c)
        mc["score"] = round(float(r) * 10.0, 3)
        mc["reason"] = "ASR/VLM/摘要/标签 文本相似度（无向量检索）"
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
        text_weight_asr: float = 0.30,
        text_weight_vlm: float = 0.25,
        text_weight_summary: float = 0.30,
        text_weight_tags: float = 0.15,
    ):
        self.embedder = embedder
        self.vector_db = vector_db
        self.llm = llm
        self.text_weight_asr = text_weight_asr
        self.text_weight_vlm = text_weight_vlm
        self.text_weight_summary = text_weight_summary
        self.text_weight_tags = text_weight_tags

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
        *,
        subspaces: Optional[List[str]] = None,
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
                query_vec, top_k=top_k, video_ids=video_ids or None, subspaces=subspaces
            )
        except Exception as e:
            return self._recall_on_vector_failure(
                query, db_conn, top_k, video_ids, reason=f"向量检索失败: {e}"
            )

        candidates = _fetch_clips_by_ids(db_conn, candidate_ids) if candidate_ids else []
        used_full_fallback = False

        # 混合召回（P2）：向量召回对「旁白↔画面」跨层匹配可能漏，
        # 追加 enrich 后的文本命中作为补充，按 clip_id 去重后合并送 LLM 精排。
        if candidates and (video_ids is not None):
            existing_ids = {c["clip_id"] for c in candidates}
            text_extra = _text_similarity_candidates(
                db_conn,
                query,
                video_ids,
                top_k,
                weight_asr=self.text_weight_asr,
                weight_vlm=self.text_weight_vlm,
                weight_summary=self.text_weight_summary,
                weight_tags=self.text_weight_tags,
            )
            added = 0
            for c in text_extra:
                if c["clip_id"] not in existing_ids:
                    candidates.append(c)
                    existing_ids.add(c["clip_id"])
                    added += 1
            if added:
                logger.info("[Matcher] 混合召回：文本补充 %d 个候选（合并后 %d 个）", added, len(candidates))

        if not candidates and video_ids:
            logger.warning("[Matcher] 向量初筛无可用候选，尝试文本相似度兜底")
            candidates = _text_similarity_candidates(
                db_conn,
                query,
                video_ids,
                top_k,
                weight_asr=self.text_weight_asr,
                weight_vlm=self.text_weight_vlm,
                weight_summary=self.text_weight_summary,
                weight_tags=self.text_weight_tags,
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
            weight_summary=self.text_weight_summary,
            weight_tags=self.text_weight_tags,
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
            weight_summary=self.text_weight_summary,
            weight_tags=self.text_weight_tags,
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
        min_llm_score: float = 0.0,
        min_similarity: float = 0.0,
        refine: Optional[bool] = None,
        subspaces: Optional[List[str]] = None,
        penalize_clip_ids: Optional[List[str]] = None,
        penalty_factor: float = 0.55,
    ) -> dict:
        video_ids = [v for v in (video_ids or []) if v]
        scoped_ids = video_ids or None

        if mode == "vector":
            candidates, used_full_fallback = self._recall_vector(
                query, db_conn, top_k, scoped_ids, subspaces=subspaces
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
        # refine 显式控制：True=强制启用 LLM 精排；False=跳过 LLM 精排（仅用初筛排序）。
        # None=保持原有行为（llm_only 强制启用；其余按候选数量自动决定）。
        if refine is True:
            force_llm = True
        elif refine is False:
            force_llm = False
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

        # 跨段去重降权（P2）：整篇多段匹配时，前文已选用的片段在此处降权，
        # 使推荐位让给未用过的素材；候选仍保留（不删除），供手动改选。
        # 降权取「乘系数再扣固定分」：既覆盖 LLM 的 0~10 分制（差距可达数分），
        # 也覆盖无 LLM 时的位次分（1.0/0.95/0.9 这种小差距序列）。
        if penalize_clip_ids:
            penalize_set = {str(x) for x in penalize_clip_ids if x}
            touched = False
            for c in candidates:
                if str(c.get("clip_id", "")) in penalize_set:
                    try:
                        old_score = float(c.get("score", 0) or 0)
                    except (TypeError, ValueError):
                        old_score = 0.0
                    c["score"] = round(max(0.0, old_score * penalty_factor - 1.0), 3)
                    c["reason"] = f"{c.get('reason') or ''}；已降权（前文已选用该片段）".lstrip("；")
                    touched = True
            if touched:
                candidates.sort(
                    key=lambda c: float(c.get("score", 0) or 0), reverse=True
                )
                logger.info(
                    "[Matcher] 跨段去重降权：%d 个已用片段被降权", len(penalize_set)
                )

        _attach_media_urls(candidates, api_base_url)

        # 阈值过滤（P2 宁缺毋滥）：仅作用于「推荐」列表，candidates 仍全量返回供手动选用。
        # 同时低于 LLM 评分阈值与文本相似度阈值才剔除，避免误杀单一信号不佳但整体相关的片段。
        # text_sim 用四路（含 enrich）相似度，作为向量模式 L2 之外的可解释补充信号。
        if not used_full_fallback and (min_llm_score > 0 or min_similarity > 0):
            q = (query or "").strip()
            for c in candidates:
                ts = _clip_text_score(q, c) if q else 0.0
                c["text_sim"] = round(ts, 3)
            kept = []
            for c in candidates:
                llm_ok = c.get("score", 0) >= min_llm_score if min_llm_score > 0 else True
                sim_ok = c.get("text_sim", 0) >= min_similarity if min_similarity > 0 else True
                if llm_ok or sim_ok:
                    kept.append(c)
            if kept:
                candidates = kept
            else:
                logger.info("[Matcher] 阈值过滤后全部被剔除，保留原候选以免推荐为空")

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
