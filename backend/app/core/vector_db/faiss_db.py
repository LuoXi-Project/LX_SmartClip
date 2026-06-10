import json
import logging
import os
import sqlite3
from typing import Dict, List, Optional

import numpy as np

from app.core.vector_db.base import IVectorDB

logger = logging.getLogger(__name__)


class FaissVectorDB(IVectorDB):
    """FAISS 向量数据库实现（本地文件持久化）"""

    def __init__(self, db_path: str, vector_dimension: int = 1024):
        self.db_path = db_path
        self.vector_dimension = vector_dimension

        data_dir = os.path.dirname(os.path.abspath(db_path))
        self.index_path = os.path.join(data_dir, "clip_embeddings.faiss")
        self.mapping_path = os.path.join(data_dir, "clip_embeddings.json")

        self._faiss = self._load_faiss()
        self._index = self._faiss.IndexFlatL2(self.vector_dimension)
        self._embeddings: Dict[str, List[float]] = {}
        self._clip_ids: List[str] = []
        self._load()

    def _load_faiss(self):
        try:
            import faiss

            return faiss
        except ImportError as e:
            raise ImportError("请先安装 faiss-cpu: pip install faiss-cpu") from e

    def _load(self) -> None:
        if os.path.exists(self.mapping_path):
            with open(self.mapping_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._embeddings = data.get("embeddings", {})

        self._clip_ids = list(self._embeddings.keys())

        if os.path.exists(self.index_path):
            try:
                self._index = self._faiss.read_index(self.index_path)
                return
            except Exception as e:
                logger.warning("读取 FAISS 索引失败，改为重建: %s", e)

        self._rebuild_index(save=False)

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        self._faiss.write_index(self._index, self.index_path)
        with open(self.mapping_path, "w", encoding="utf-8") as f:
            json.dump({"embeddings": self._embeddings}, f, ensure_ascii=False)

    def _rebuild_index(self, save: bool = True) -> None:
        self._clip_ids = list(self._embeddings.keys())
        self._index = self._faiss.IndexFlatL2(self.vector_dimension)

        if self._clip_ids:
            matrix = np.array([self._embeddings[cid] for cid in self._clip_ids], dtype="float32")
            self._index.add(matrix)

        if save:
            self._save()

    def add_embedding(self, clip_id: str, embedding: List[float]) -> None:
        if len(embedding) != self.vector_dimension:
            raise ValueError(f"向量维度不匹配: 期望 {self.vector_dimension}, 实际 {len(embedding)}")

        self._embeddings[clip_id] = [float(x) for x in embedding]
        self._rebuild_index(save=True)
        logger.info("向量已写入(FAISS): %s", clip_id)

    def search(
        self,
        embedding: List[float],
        top_k: int = 12,
        video_ids: Optional[List[str]] = None,
    ) -> List[str]:
        if len(embedding) != self.vector_dimension:
            raise ValueError(f"向量维度不匹配: 期望 {self.vector_dimension}, 实际 {len(embedding)}")

        if not self._clip_ids:
            return []

        query = np.array([embedding], dtype="float32")

        def _search_filtered(fetch_k: int) -> List[str]:
            fk = min(max(int(fetch_k), 1), len(self._clip_ids))
            _distances, indices = self._index.search(query, fk)
            cids: List[str] = []
            for idx in indices[0].tolist():
                if idx == -1:
                    continue
                cids.append(self._clip_ids[idx])
            if video_ids and cids:
                conn = sqlite3.connect(self.db_path)
                try:
                    placeholders_c = ",".join("?" * len(cids))
                    placeholders_v = ",".join("?" * len(video_ids))
                    rows = conn.execute(
                        f"SELECT id FROM clips WHERE id IN ({placeholders_c}) AND video_id IN ({placeholders_v})",
                        cids + video_ids,
                    ).fetchall()
                    filtered_set = {r[0] for r in rows}
                    cids = [cid for cid in cids if cid in filtered_set]
                finally:
                    conn.close()
            return cids

        fetch_k = min(top_k * 5 if video_ids else top_k, len(self._clip_ids))
        clip_ids = _search_filtered(fetch_k)
        # 限定 video 时，仅用 top_k*5 的全局近邻容易全部被过滤掉；再按全索引顺序重试一次
        if video_ids and not clip_ids:
            logger.info("向量搜索(FAISS): video_ids 过滤后为空，改为全量向量序重试")
            clip_ids = _search_filtered(len(self._clip_ids))

        result = clip_ids[:top_k]
        logger.info("向量搜索完成(FAISS): 返回 %d 个结果", len(result))
        return result

    def get_embedding(self, clip_id: str) -> Optional[List[float]]:
        return self._embeddings.get(clip_id)

    def delete_embedding(self, clip_id: str) -> None:
        if clip_id not in self._embeddings:
            return

        self._embeddings.pop(clip_id, None)
        self._rebuild_index(save=True)
        logger.info("向量已删除(FAISS): %s", clip_id)

    def get_vector_dimension(self) -> int:
        return self.vector_dimension

    def embedding_count(self) -> int:
        return len(self._clip_ids)
