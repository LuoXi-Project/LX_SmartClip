from abc import ABC, abstractmethod
from typing import List, Optional


class IVLM(ABC):
    """VLM（视觉语言模型）抽象接口"""

    @abstractmethod
    def generate_description(
        self,
        frame_paths: List[str],
        frame_times_sec: Optional[List[float]] = None,
    ) -> str:
        """
        根据图像帧生成描述

        Args:
            frame_paths: 图像文件路径列表
            frame_times_sec: 可选，与 frame_paths 等长的片内时间戳（秒），用于告知模型每张图的时刻

        Returns:
            生成的描述文本
        """
        pass

    @abstractmethod
    def get_model_info(self) -> dict:
        """获取模型信息"""
        pass
