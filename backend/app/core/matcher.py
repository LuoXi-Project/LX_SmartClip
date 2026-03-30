import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class Matcher:
    """
    三级匹配引擎

    Level 1 — 向量初筛：用 Embedder 将文案向量化，FAISS 检索 top_k 候选
    Level 2 — LLM 精排：将候选片段的 asr_text + vlm_description 送给 LLM 评分排序
    Level 3 — 返回结果：输出 top_n 推荐 + 完整候选列表
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
        # ── Level 1：向量初筛 ──────────────────────────────────────────
        logger.info("[Matcher] Level-1 向量初筛: query_len=%d, top_k=%d", len(query), top_k)
        query_vec = self.embedder.embed(query)
        candidate_ids = self.vector_db.search(query_vec, top_k=top_k, video_ids=video_ids)

        if not candidate_ids:
            logger.warning("[Matcher] 向量初筛无结果")
            return {"query": query, "top_n": top_n, "recommended": [], "candidates": []}

        # ── 拉取片段元数据 ─────────────────────────────────────────────
        placeholders = ",".join("?" * len(candidate_ids))
        rows = db_conn.execute(
            f"SELECT id AS clip_id, video_id, clip_path, start_time, end_time, "
            f"duration, asr_text, vlm_description "
            f"FROM clips WHERE id IN ({placeholders})",
            candidate_ids,
        ).fetchall()

        # 保持向量搜索的排序顺序
        row_map = {r["clip_id"]: dict(r) for r in rows}
        candidates = [row_map[cid] for cid in candidate_ids if cid in row_map]

        logger.info("[Matcher] 初筛候选: %d 个片段", len(candidates))

        # ── Level 2：LLM 精排 ──────────────────────────────────────────
        if self.llm is not None:
            logger.info("[Matcher] Level-2 LLM 精排...")
            try:
                candidates = self.llm.rank(query, candidates)
            except Exception as e:
                logger.warning("[Matcher] LLM 精排异常，使用向量排序: %s", e)
                for i, c in enumerate(candidates):
                    c.setdefault("score", round(1.0 - i * 0.05, 3))
                    c.setdefault("reason", "向量相似度排序")
        else:
            # 无 LLM：用向量顺序生成分数
            for i, c in enumerate(candidates):
                c.setdefault("score", round(1.0 - i * 0.05, 3))
                c.setdefault("reason", "向量相似度排序")

        # ── Level 3：补充预览/封面 URL 并返回 ───────────────────────────
        base_url = api_base_url.rstrip("/") if api_base_url else ""
        for c in candidates:
            clip_id = c.get("clip_id")
            video_id = c.get("video_id")
            c["preview_url"] = f"{base_url}/api/videos/clips/{clip_id}/stream" if base_url else f"/api/videos/clips/{clip_id}/stream"
            c["thumbnail_url"] = f"{base_url}/api/videos/{video_id}/thumbnail" if base_url else f"/api/videos/{video_id}/thumbnail"

        recommended = candidates[:top_n]
        logger.info("[Matcher] 匹配完成: 推荐 %d 个，候选共 %d 个", len(recommended), len(candidates))
        return {
            "query": query,
            "top_n": top_n,
            "recommended": recommended,
            "candidates": candidates,
        }
