from abc import ABC, abstractmethod
from typing import List


class IVLM(ABC):
    """VLM（视觉语言模型）抽象接口"""

    @abstractmethod
    def generate_description(self, frame_paths: List[str]) -> str:
        """
        根据图像帧生成描述
        
        Args:
            frame_paths: 图像文件路径列表
            
        Returns:
            生成的描述文本
        """
        pass

    @abstractmethod
    def get_model_info(self) -> dict:
        """获取模型信息"""
        pass
