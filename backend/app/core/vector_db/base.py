from abc import ABC, abstractmethod
from typing import List, Optional


class IVectorDB(ABC):
    """向量数据库抽象接口"""

    @abstractmethod
    def add_embedding(self, clip_id: str, embedding: List[float]) -> None:
        """
        添加向量嵌入
        
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
    ) -> List[str]:
        """
        向量相似度搜索
        
        Args:
            embedding: 查询向量
            top_k: 返回的最相似结果数量
            video_ids: 可选的视频 ID 列表，用于过滤搜索范围
            
        Returns:
            最相似的片段 ID 列表
        """
        pass

    @abstractmethod
    def get_embedding(self, clip_id: str) -> Optional[List[float]]:
        """获取片段的向量嵌入"""
        pass

    @abstractmethod
    def delete_embedding(self, clip_id: str) -> None:
        """删除片段的向量嵌入"""
        pass

    @abstractmethod
    def get_vector_dimension(self) -> int:
        """获取向量维度"""
        pass
