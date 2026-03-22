import os
import base64
import logging
from typing import List
from app.core.vlm.base import IVLM

logger = logging.getLogger(__name__)


class OpenAIVLM(IVLM):
    """OpenAI Vision API VLM 实现"""

    def __init__(self, base_url: str, model: str, api_key: str):
        """
        初始化 OpenAI VLM
        
        Args:
            base_url: OpenAI API 基础 URL
            model: 模型名称（gpt-4o, gpt-4-vision 等）
            api_key: API Key
        """
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("请安装 openai: pip install openai")

        self.base_url = base_url
        self.model = model
        self.api_key = api_key

        # 初始化 OpenAI 客户端
        self.client = OpenAI(api_key=api_key, base_url=base_url)

        logger.info(f"初始化 OpenAI VLM: model={model}, base_url={base_url}")

    def generate_description(self, frame_paths: List[str]) -> str:
        """
        根据图像帧生成描述
        
        Args:
            frame_paths: 图像文件路径列表
            
        Returns:
            生成的描述文本
        """
        if not frame_paths:
            raise ValueError("必须提供至少一个图像文件")

        logger.info(f"生成描述: {len(frame_paths)} 张图像")

        # 构建图像内容
        content = [
            {
                "type": "text",
                "text": "请简洁地描述这些图像的内容，包括场景、人物、物体和动作。用中文回答，不超过 200 字。",
            }
        ]

        # 添加图像
        for frame_path in frame_paths:
            if not os.path.exists(frame_path):
                logger.warning(f"图像文件不存在: {frame_path}")
                continue

            # 读取图像并转换为 base64
            with open(frame_path, "rb") as f:
                image_data = base64.standard_b64encode(f.read()).decode("utf-8")

            # 获取图像格式
            ext = os.path.splitext(frame_path)[1].lower()
            media_type = "image/jpeg" if ext in [".jpg", ".jpeg"] else "image/png"

            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{media_type};base64,{image_data}",
                    },
                }
            )

        try:
            # 调用 OpenAI API
            logger.info(f"调用 OpenAI API: model={self.model}")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": content,
                    }
                ],
                max_tokens=500,
                temperature=0.7,
            )

            description = response.choices[0].message.content.strip()
            logger.info(f"描述生成成功: {len(description)} 个字符")
            return description

        except Exception as e:
            logger.error(f"生成描述失败: {e}")
            raise RuntimeError(f"生成描述失败: {str(e)}")

    def get_model_info(self) -> dict:
        """获取模型信息"""
        return {
            "provider": "openai",
            "model": self.model,
            "base_url": self.base_url,
            "type": "vision",
        }
