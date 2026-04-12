import sqlite3
import json
import logging
from typing import List, Optional
from app.core.vector_db.base import IVectorDB

logger = logging.getLogger(__name__)


class SQLiteVSSDB(IVectorDB):
    """SQLite + sqlite-vss 向量数据库实现"""

    def __init__(self, db_path: str, vector_dimension: int = 1024):
        self.db_path = db_path
        self.vector_dimension = vector_dimension
        self._init_table()

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接并加载 vss 扩展"""
        import sqlite_vss
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        sqlite_vss.load(conn)
        return conn

    def _init_table(self) -> None:
        """初始化向量虚拟表和映射表"""
        try:
            conn = self._get_connection()
            conn.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS clip_embeddings USING vss0(
                    embedding({self.vector_dimension})
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS clip_embeddings_mapping (
                    rowid INTEGER PRIMARY KEY,
                    clip_id TEXT UNIQUE NOT NULL
                )
                """
            )
            conn.commit()
            logger.info(f"向量表初始化成功, dimension={self.vector_dimension}")
        except Exception as e:
            logger.error(f"向量表初始化失败: {e}")
            raise
        finally:
            conn.close()

    def add_embedding(self, clip_id: str, embedding: List[float]) -> None:
        """添加或更新片段向量"""
        if len(embedding) != self.vector_dimension:
            raise ValueError(f"向量维度不匹配: 期望 {self.vector_dimension}, 实际 {len(embedding)}")

        try:
            conn = self._get_connection()
            # 检查是否已存在
            row = conn.execute(
                "SELECT rowid FROM clip_embeddings_mapping WHERE clip_id = ?", (clip_id,)
            ).fetchone()

            vec_json = json.dumps(embedding)

            if row:
                rowid = row["rowid"]
                conn.execute(
                    "UPDATE clip_embeddings SET embedding = ? WHERE rowid = ?",
                    (vec_json, rowid),
                )
            else:
                cursor = conn.execute(
                    "INSERT INTO clip_embeddings(embedding) VALUES (?)", (vec_json,)
                )
                conn.execute(
                    "INSERT INTO clip_embeddings_mapping(rowid, clip_id) VALUES (?, ?)",
                    (cursor.lastrowid, clip_id),
                )
            conn.commit()
            logger.info(f"向量已写入: {clip_id}")
        except Exception as e:
            logger.error(f"写入向量失败: {e}")
            raise
        finally:
            conn.close()

    def search(
        self,
        embedding: List[float],
        top_k: int = 12,
        video_ids: Optional[List[str]] = None,
    ) -> List[str]:
        """向量相似度搜索，支持按 video_ids 过滤"""
        if len(embedding) != self.vector_dimension:
            raise ValueError(f"向量维度不匹配: 期望 {self.vector_dimension}, 实际 {len(embedding)}")

        try:
            conn = self._get_connection()
            vec_json = json.dumps(embedding)

            # 搜索时获取足够多的候选，再做过滤
            fetch_k = top_k * 5 if video_ids else top_k

            rows = conn.execute(
                f"""
                SELECT m.clip_id
                FROM clip_embeddings v
                JOIN clip_embeddings_mapping m ON v.rowid = m.rowid
                WHERE vss_search(v.embedding, vss_search_params(?, {fetch_k}))
                ORDER BY vss_distance_l2(v.embedding, ?) 
                LIMIT ?
                """,
                (vec_json, vec_json, fetch_k),
            ).fetchall()

            clip_ids = [r["clip_id"] for r in rows]

            # 按 video_ids 过滤
            if video_ids and clip_ids:
                placeholders_c = ",".join("?" * len(clip_ids))
                placeholders_v = ",".join("?" * len(video_ids))
                filtered = conn.execute(
                    f"SELECT id FROM clips WHERE id IN ({placeholders_c}) AND video_id IN ({placeholders_v})",
                    clip_ids + video_ids,
                ).fetchall()
                filtered_set = {r[0] for r in filtered}
                clip_ids = [cid for cid in clip_ids if cid in filtered_set]

            result = clip_ids[:top_k]
            logger.info(f"向量搜索完成: 返回 {len(result)} 个结果")
            return result
        except Exception as e:
            logger.error(f"向量搜索失败: {e}")
            raise
        finally:
            conn.close()

    def get_embedding(self, clip_id: str) -> Optional[List[float]]:
        """获取片段向量"""
        try:
            conn = self._get_connection()
            row = conn.execute(
                """
                SELECT v.embedding FROM clip_embeddings v
                JOIN clip_embeddings_mapping m ON v.rowid = m.rowid
                WHERE m.clip_id = ?
                """,
                (clip_id,),
            ).fetchone()
            return json.loads(row["embedding"]) if row else None
        finally:
            conn.close()

    def delete_embedding(self, clip_id: str) -> None:
        """删除片段向量"""
        try:
            conn = self._get_connection()
            row = conn.execute(
                "SELECT rowid FROM clip_embeddings_mapping WHERE clip_id = ?", (clip_id,)
            ).fetchone()
            if row:
                rowid = row["rowid"]
                conn.execute("DELETE FROM clip_embeddings WHERE rowid = ?", (rowid,))
                conn.execute("DELETE FROM clip_embeddings_mapping WHERE rowid = ?", (rowid,))
                conn.commit()
                logger.info(f"向量已删除: {clip_id}")
        finally:
            conn.close()

    def get_vector_dimension(self) -> int:
        return self.vector_dimension
