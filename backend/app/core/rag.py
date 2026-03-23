import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class RAGSearcher:
    """RAG 初筛：Embedding + 向量检索"""

    def __init__(self, embedder, vector_db):
        self.embedder = embedder
        self.vector_db = vector_db

    def search(self, query: str, top_k: int = 12, video_ids: Optional[List[str]] = None) -> List[str]:
        query_vec = self.embedder.embed(query)
        clip_ids = self.vector_db.search(query_vec, top_k=top_k, video_ids=video_ids)
        logger.info("RAG 初筛完成: query_len=%d, top_k=%d, return=%d", len(query), top_k, len(clip_ids))
        return clip_ids
