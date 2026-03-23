from abc import ABC, abstractmethod
from typing import List


class ILLM(ABC):
    """LLM 抽象接口，用于 LLM 精排"""

    @abstractmethod
    def rank(self, query: str, candidates: List[dict]) -> List[dict]:
        """
        对候选片段进行精排。

        Args:
            query: 用户文案（自然语言）
            candidates: 候选片段列表，每个元素包含 clip_id、asr_text、vlm_description 等字段

        Returns:
            精排后的片段列表（含 score、reason 字段），按相关度降序排列
        """

    @abstractmethod
    def get_model_info(self) -> dict:
        """返回模型信息"""
