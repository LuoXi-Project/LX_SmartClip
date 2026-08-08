import json
import logging
import os
import sqlite3
import time
from typing import Dict, List, Optional

import numpy as np

from app.core.vector_db.base import IVectorDB

logger = logging.getLogger(__name__)

# RRF 常数：score(d) = Σ 1/(rank_i(d) + k)。60 是信息检索常用值，对 top 列表头部均衡。
_RRF_K = 60

# 前 3 个"新"子空间（新 clip 写入这些）；legacy 为旧混合向量兼容槽，不主动写入。
_NEW_SUBSPACES = ("asr", "vlm", "abstract")
_LEGACY_SUBSPACE = "legacy"


class FaissVectorDB(IVectorDB):
    """FAISS 向量数据库实现（多子空间，本地文件持久化）

    每个 clip 可拥有 4 个子空间向量：
      - asr / vlm / abstract：新拆分的子空间（解决旁白↔画面跨层检索）
      - legacy：旧 5 路混合向量（兼容现有 8901 条数据）

    检索时对每个有数据的子空间分别取 top_k，RRF 融合后返回统一结果。
    单向量接口保留向后兼容：get_embedding→abstract，add_embedding→abstract。
    """

    def __init__(self, db_path: str, vector_dimension: int = 1024):
        self.db_path = db_path
        self.vector_dimension = vector_dimension

        data_dir = os.path.dirname(os.path.abspath(db_path))
        self.data_dir = data_dir
        # legacy 复用原文件名（兼容旧库）；前 3 个子空间各自带后缀。
        self._index_paths = {
            "asr": os.path.join(data_dir, "clip_embeddings.asr.faiss"),
            "vlm": os.path.join(data_dir, "clip_embeddings.vlm.faiss"),
            "abstract": os.path.join(data_dir, "clip_embeddings.abstract.faiss"),
            "legacy": os.path.join(data_dir, "clip_embeddings.faiss"),
        }
        self._mapping_paths = {
            "asr": os.path.join(data_dir, "clip_embeddings.asr.json"),
            "vlm": os.path.join(data_dir, "clip_embeddings.vlm.json"),
            "abstract": os.path.join(data_dir, "clip_embeddings.abstract.json"),
            "legacy": os.path.join(data_dir, "clip_embeddings.json"),
        }

        self._faiss = self._load_faiss()
        # 每个子空间一个 IndexFlatL2 + 一个 {clip_id: vec} 映射
        self._indexes: Dict[str, object] = {}
        self._embeddings: Dict[str, Dict[str, List[float]]] = {
            s: {} for s in self.SUBSPACES
        }
        self._load()

    def _load_faiss(self):
        try:
            import faiss

            return faiss
        except ImportError as e:
            raise ImportError("请先安装 faiss-cpu: pip install faiss-cpu") from e

    # ---- 持久化加载/保存 ----

    def _load(self) -> None:
        """逐子空间加载：读映射 JSON → 建 index → 读 .faiss（若有）。"""
        for sub in self.SUBSPACES:
            self._load_subspace(sub)

    def _load_subspace(self, sub: str) -> None:
        mapping_path = self._mapping_paths[sub]
        index_path = self._index_paths[sub]
        embeddings: Dict[str, List[float]] = {}

        if os.path.exists(mapping_path):
            try:
                with open(mapping_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 兼容两种结构：旧 legacy 文件 {"embeddings": {...}}；新文件直接 {clip_id: [...]}
                raw = data.get("embeddings", data) if isinstance(data, dict) else {}
                if isinstance(raw, dict):
                    embeddings = {
                        cid: [float(x) for x in vec]
                        for cid, vec in raw.items()
                        if isinstance(vec, list)
                    }
            except (json.JSONDecodeError, OSError) as e:
                logger.error(
                    "映射文件损坏，回退为空并继续（FAISS 索引如完好可重建）：path=%s err=%s",
                    mapping_path,
                    e,
                )
                self._backup_corrupt(mapping_path)
                embeddings = {}

        self._embeddings[sub] = embeddings

        # 优先复用磁盘上已有的 .faiss 索引；损坏或不存在则从映射重建
        if embeddings and os.path.exists(index_path):
            try:
                self._indexes[sub] = self._faiss.read_index(index_path)
                # 索引向量数与映射不一致时（可能映射增删后未 rebuild），回退重建
                if self._indexes[sub].ntotal != len(embeddings):
                    logger.warning(
                        "子空间 %s 索引向量数(%d)与映射(%d)不一致，重建",
                        sub, self._indexes[sub].ntotal, len(embeddings),
                    )
                    self._rebuild_subspace(sub, save=False)
                return
            except Exception as e:
                logger.warning("读取子空间 %s FAISS 索引失败，改为重建: %s", sub, e)

        self._rebuild_subspace(sub, save=False)

    def _backup_corrupt(self, path: str) -> None:
        """把损坏的映射文件改名备份，便于事后排查或抢救数据。"""
        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            backup = f"{path}.corrupt.{ts}"
            os.replace(path, backup)
            logger.warning("损坏的映射文件已备份为: %s", backup)
        except OSError as backup_err:
            logger.error("备份损坏文件失败: %s", backup_err)

    def _atomic_write_text(self, path: str, data: str) -> None:
        """先写 .tmp 再 os.replace 原子替换。Windows 下 os.replace 偶发占用做短暂重试。"""
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        last_err = None
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except OSError as e:
                last_err = e
                time.sleep(0.1 * (attempt + 1))
        raise OSError(f"原子替换失败（重试 5 次）: {path} -> {last_err}")

    def _save_subspace(self, sub: str) -> None:
        os.makedirs(os.path.dirname(self._index_paths[sub]), exist_ok=True)
        index_path = self._index_paths[sub]
        tmp_index = f"{index_path}.tmp"
        # 空子空间不写 .faiss 文件（避免读到 0 向量索引）
        if sub in self._indexes and self._indexes[sub].ntotal > 0:
            self._faiss.write_index(self._indexes[sub], tmp_index)
            last_err = None
            for attempt in range(5):
                try:
                    os.replace(tmp_index, index_path)
                    break
                except OSError as e:
                    last_err = e
                    time.sleep(0.1 * (attempt + 1))
            else:
                raise OSError(f"FAISS 索引原子替换失败（重试 5 次）: {last_err}")
        elif os.path.exists(index_path):
            # 子空间变空：删除残留索引文件
            try:
                os.remove(index_path)
            except OSError:
                pass

        payload = json.dumps(self._embeddings[sub], ensure_ascii=False)
        self._atomic_write_text(self._mapping_paths[sub], payload)

    def _rebuild_subspace(self, sub: str, save: bool = True) -> None:
        embeddings = self._embeddings.get(sub) or {}
        index = self._faiss.IndexFlatL2(self.vector_dimension)
        if embeddings:
            matrix = np.array(list(embeddings.values()), dtype="float32")
            index.add(matrix)
        self._indexes[sub] = index
        if save:
            self._save_subspace(sub)

    def _rebuild_all(self, save: bool = True) -> None:
        for sub in self.SUBSPACES:
            self._rebuild_subspace(sub, save=save)

    # ---- 维度校验 ----

    def _check_dim(self, embedding: List[float]) -> None:
        if len(embedding) != self.vector_dimension:
            raise ValueError(
                f"向量维度不匹配: 期望 {self.vector_dimension}, 实际 {len(embedding)}"
            )

    # ---- 单向量接口（向后兼容） ----

    def add_embedding(self, clip_id: str, embedding: List[float]) -> None:
        """单向量兼容入口：写入 abstract 子空间。"""
        self._check_dim(embedding)
        self.add_embedding_multi(clip_id, {"abstract": embedding})

    def add_embeddings(self, items: List[tuple]) -> int:
        """单向量兼容入口批量写：全部写入 abstract 子空间。"""
        added = 0
        for clip_id, embedding in items:
            self._check_dim(embedding)
            self._embeddings["abstract"][clip_id] = [float(x) for x in embedding]
            added += 1
        if added:
            self._rebuild_subspace("abstract", save=True)
            logger.info("批量写入向量(FAISS, abstract): %d 个", added)
        return added

    # ---- 多向量接口 ----

    def add_embedding_multi(self, clip_id: str, vectors: Dict[str, List[float]]) -> None:
        """写入一个 clip 的多个子空间向量，仅写入出现的子空间。"""
        touched: List[str] = []
        for sub, vec in vectors.items():
            if sub not in self.SUBSPACES:
                logger.warning("跳过未知子空间 %s（clip %s）", sub, clip_id)
                continue
            self._check_dim(vec)
            self._embeddings[sub][clip_id] = [float(x) for x in vec]
            touched.append(sub)
        for sub in touched:
            self._rebuild_subspace(sub, save=True)
        logger.info("多向量已写入(FAISS): %s 子空间=%s", clip_id, touched)

    def get_embedding(self, clip_id: str) -> Optional[List[float]]:
        """返回 abstract 子空间向量；无则 fallback legacy。"""
        vec = self._embeddings["abstract"].get(clip_id)
        if vec is not None:
            return vec
        return self._embeddings["legacy"].get(clip_id)

    def get_embedding_multi(self, clip_id: str) -> Dict[str, List[float]]:
        out: Dict[str, List[float]] = {}
        for sub in self.SUBSPACES:
            vec = self._embeddings[sub].get(clip_id)
            if vec is not None:
                out[sub] = vec
        return out

    def delete_embedding(self, clip_id: str) -> None:
        self.delete_embedding_multi(clip_id)

    def delete_embeddings(self, clip_ids: List[str]) -> int:
        """批量删除（单向量接口保留）。返回至少被删一个子空间的 clip 数。"""
        removed = 0
        touched: set = set()
        for cid in clip_ids:
            hit = False
            for sub in self.SUBSPACES:
                if cid in self._embeddings[sub]:
                    self._embeddings[sub].pop(cid, None)
                    touched.add(sub)
                    hit = True
            if hit:
                removed += 1
        for sub in touched:
            self._rebuild_subspace(sub, save=True)
        if removed:
            logger.info("批量删除向量(FAISS): %d 个 clip", removed)
        return removed

    def delete_embedding_multi(self, clip_id: str) -> int:
        removed = 0
        touched: List[str] = []
        for sub in self.SUBSPACES:
            if clip_id in self._embeddings[sub]:
                self._embeddings[sub].pop(clip_id, None)
                touched.append(sub)
                removed += 1
        for sub in touched:
            self._rebuild_subspace(sub, save=True)
        if removed:
            logger.info("向量已删除(FAISS): %s 子空间=%s", clip_id, touched)
        return removed

    def delete_subspace(self, clip_id: str, sub: str) -> bool:
        """删除指定 clip 在单一子空间的向量。返回是否实际删除。"""
        if sub not in self.SUBSPACES:
            return False
        if clip_id not in self._embeddings[sub]:
            return False
        self._embeddings[sub].pop(clip_id, None)
        self._rebuild_subspace(sub, save=True)
        logger.info("子空间向量已删除(FAISS): %s sub=%s", clip_id, sub)
        return True

    def get_vector_dimension(self) -> int:
        return self.vector_dimension

    def embedding_count(self) -> int:
        """至少拥有一个子空间向量的 clip 数（去重）。"""
        all_ids: set = set()
        for sub in self.SUBSPACES:
            all_ids.update(self._embeddings[sub].keys())
        return len(all_ids)

    def subspace_count(self, sub: str) -> int:
        """指定子空间的向量数。"""
        return len(self._embeddings.get(sub, {}))

    # ---- 检索 ----

    def _active_subspaces(self, subspaces: Optional[List[str]]) -> List[str]:
        """返回有数据且被请求的子空间列表。"""
        if subspaces:
            subs = [s for s in subspaces if s in self.SUBSPACES]
        else:
            subs = list(self.SUBSPACES)
        return [s for s in subs if self._embeddings.get(s)]

    def _search_subspace_raw(
        self, sub: str, query: np.ndarray, fetch_k: int
    ) -> List[str]:
        """单个子空间的原始（未过滤）top 候选 clip_id 列表（按相似度降序）。"""
        embeddings = self._embeddings[sub]
        if not embeddings:
            return []
        fk = min(max(int(fetch_k), 1), len(embeddings))
        _distances, indices = self._indexes[sub].search(query, fk)
        cids: List[str] = []
        clip_ids = list(embeddings.keys())
        for idx in indices[0].tolist():
            if idx == -1 or idx >= len(clip_ids):
                continue
            cids.append(clip_ids[idx])
        return cids

    def _filter_by_video_ids(
        self, conn: sqlite3.Connection, cids: List[str], video_ids: List[str]
    ) -> List[str]:
        if not video_ids or not cids:
            return cids
        placeholders_c = ",".join("?" * len(cids))
        placeholders_v = ",".join("?" * len(video_ids))
        rows = conn.execute(
            f"SELECT id FROM clips WHERE id IN ({placeholders_c}) AND video_id IN ({placeholders_v})",
            cids + video_ids,
        ).fetchall()
        valid = {r[0] for r in rows}
        return [cid for cid in cids if cid in valid]

    def search_multi(
        self,
        embedding: List[float],
        top_k: int = 12,
        video_ids: Optional[List[str]] = None,
        subspaces: Optional[List[str]] = None,
    ) -> Dict[str, List[str]]:
        """在指定子空间分别检索，返回每个子空间的 top_k 候选（已按 video_ids 过滤）。

        注意：为支持 video_ids 过滤后仍有足够候选，每个子空间实际拉取
        max(top_k, top_k*5) 的近邻再过滤，最后截断 top_k。
        """
        self._check_dim(embedding)
        active = self._active_subspaces(subspaces)
        if not active:
            return {}

        query = np.array([embedding], dtype="float32")
        conn: Optional[sqlite3.Connection] = sqlite3.connect(self.db_path) if video_ids else None
        try:
            out: Dict[str, List[str]] = {}
            for sub in active:
                n = len(self._embeddings[sub])
                fetch_k = min(top_k * 5, n) if video_ids else min(top_k, n)
                cids = self._search_subspace_raw(sub, query, fetch_k)
                if conn is not None and cids:
                    cids = self._filter_by_video_ids(conn, cids, video_ids)
                out[sub] = cids[:top_k]
            return out
        finally:
            if conn is not None:
                conn.close()

    def search(
        self,
        embedding: List[float],
        top_k: int = 12,
        video_ids: Optional[List[str]] = None,
        subspaces: Optional[List[str]] = None,
    ) -> List[str]:
        """多子空间 RRF 融合检索。

        对每个有数据的子空间取 top_k 候选，按 score(d)=Σ 1/(rank+k) 融合后
        取 top_k 返回。仅一个子空间有数据时退化为该子空间排序。
        subspaces 限定参与融合的子空间；None=自动选择所有有数据的子空间。
        """
        self._check_dim(embedding)
        active = self._active_subspaces(subspaces)
        if not active:
            return []

        query = np.array([embedding], dtype="float32")
        conn: Optional[sqlite3.Connection] = sqlite3.connect(self.db_path) if video_ids else None
        try:
            # 每个子空间拉取候选并过滤，记录每个 clip 在各子空间的排名
            per_sub_cids: Dict[str, List[str]] = {}
            for sub in active:
                n = len(self._embeddings[sub])
                fetch_k = min(top_k * 5, n) if video_ids else min(top_k, n)
                cids = self._search_subspace_raw(sub, query, fetch_k)
                if conn is not None and cids:
                    cids = self._filter_by_video_ids(conn, cids, video_ids)
                per_sub_cids[sub] = cids

            # video_ids 过滤后某子空间可能全空：扩到全量再试一次
            if video_ids:
                for sub in active:
                    if not per_sub_cids[sub]:
                        n = len(self._embeddings[sub])
                        cids = self._search_subspace_raw(sub, query, n)
                        if conn is not None and cids:
                            cids = self._filter_by_video_ids(conn, cids, video_ids)
                        per_sub_cids[sub] = cids

            return self._rrf_fuse(per_sub_cids, top_k)
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _rrf_fuse(per_sub_cids: Dict[str, List[str]], top_k: int) -> List[str]:
        """RRF 倒数排名融合：score(d)=Σ 1/(rank_i(d)+k)，rank 从 0 起。"""
        scores: Dict[str, float] = {}
        for cids in per_sub_cids.values():
            for rank, cid in enumerate(cids):
                scores[cid] = scores.get(cid, 0.0) + 1.0 / (rank + _RRF_K)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return [cid for cid, _ in ranked[:top_k]]
