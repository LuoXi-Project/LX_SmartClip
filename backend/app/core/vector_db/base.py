from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class IVectorDB(ABC):
    """向量数据库抽象接口

    多向量化（4 子空间）说明：
    - asr：asr_text + keywords，具体台词 + 实体
    - vlm：vlm_description，纯视觉画面
    - abstract：abstract_summary + emotion_tags，抽象主题 + 情绪（旁白命中主通道）
    - legacy：原 5 路混合向量（向后兼容旧库，不主动写入）

    单向量方法保留以向后兼容：get_embedding 返回 abstract 子空间（无则 legacy），
    add_embedding 写 abstract，search 返回多子空间 RRF 融合结果。
    """

    # 全部支持的子空间（顺序即默认检索顺序）
    SUBSPACES = ("asr", "vlm", "abstract", "legacy")

    @abstractmethod
    def add_embedding(self, clip_id: str, embedding: List[float]) -> None:
        """
        添加向量嵌入（单向量兼容入口，实际写入 abstract 子空间）

        Args:
            clip_id: 片段 ID
            embedding: 向量嵌入（浮点数列表）
        """
        pass

    @abstractmethod
    def search(
        self,
        embedding: List[float],
        top_k: int = 12,
        video_ids: Optional[List[str]] = None,
        subspaces: Optional[List[str]] = None,
    ) -> List[str]:
        """
        向量相似度搜索（多子空间 RRF 融合后的统一结果）

        Args:
            embedding: 查询向量
            top_k: 返回的最相似结果数量
            video_ids: 可选的视频 ID 列表，用于过滤搜索范围
            subspaces: 限定参与融合的子空间；None=自动选择所有有数据的子空间

        Returns:
            最相似的片段 ID 列表
        """
        pass

    @abstractmethod
    def get_embedding(self, clip_id: str) -> Optional[List[float]]:
        """获取片段向量嵌入（返回 abstract 子空间，无则 fallback legacy）"""
        pass

    @abstractmethod
    def delete_embedding(self, clip_id: str) -> None:
        """删除片段向量（删除所有子空间中的该 clip 向量）"""
        pass

    @abstractmethod
    def get_vector_dimension(self) -> int:
        """获取向量维度"""
        pass

    # ---- 多向量接口（子空间） ----

    def add_embedding_multi(self, clip_id: str, vectors: Dict[str, List[float]]) -> None:
        """
        批量写入一个 clip 的多个子空间向量。

        Args:
            clip_id: 片段 ID
            vectors: {subspace_name: embedding}，仅写入出现的子空间
        """
        raise NotImplementedError

    def search_multi(
        self,
        embedding: List[float],
        top_k: int = 12,
        video_ids: Optional[List[str]] = None,
        subspaces: Optional[List[str]] = None,
    ) -> Dict[str, List[str]]:
        """
        在指定子空间分别检索，返回每个子空间的 top_k 候选（未融合）。

        Returns:
            {subspace_name: [clip_id, ...]}
        """
        raise NotImplementedError

    def get_embedding_multi(self, clip_id: str) -> Dict[str, List[float]]:
        """获取一个 clip 在所有子空间的向量 {subspace: vec}（缺失子空间不出现）。"""
        raise NotImplementedError

    def delete_embedding_multi(self, clip_id: str) -> int:
        """删除一个 clip 在所有子空间的向量，返回实际删除的子空间数。"""
        raise NotImplementedError
