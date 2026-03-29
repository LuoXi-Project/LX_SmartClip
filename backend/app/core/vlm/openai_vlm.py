import os
import math
import base64
import logging
from typing import List
from app.core.vlm.base import IVLM
from app.core.retry import retry_sync

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

    @staticmethod
    def _calculate_image_tokens(width: int, height: int, detail: str = "auto") -> int:
        """
        计算图片消耗的 token 数量（参考阿里 Qwen-VL 及 OpenAI GPT-4o 计算方式）

        - detail="low"  : 固定 85 tokens
        - detail="high" : 将图片缩放到 2048×2048 以内，再以 768 短边为基准切块，
                          每块 512px → 170 tokens，最后加 85 tokens 基础费用
        - detail="auto" : 短边 ≤ 768 且长边 ≤ 2048 时等同 low，否则等同 high

        阿里 Qwen-VL 参考公式（patch_size=28）：
            tokens = ceil(h / 28) * ceil(w / 28)，上限 1225，下限 4
        """
        if detail == "low":
            return 85

        # 保存原始尺寸用于 auto 判断
        orig_width, orig_height = width, height

        # --- OpenAI high-detail 计算 ---
        # Step 1: 等比缩放到 2048×2048 以内
        max_size = 2048
        if width > max_size or height > max_size:
            scale = max_size / max(width, height)
            width = int(width * scale)
            height = int(height * scale)

        # Step 2: 等比缩放使短边 = 768
        short_side = min(width, height)
        if short_side > 768:
            scale = 768 / short_side
            width = int(width * scale)
            height = int(height * scale)

        # Step 3: 切成 512×512 的块，每块 170 tokens，基础 85 tokens
        tiles_x = math.ceil(width / 512)
        tiles_y = math.ceil(height / 512)
        tokens = tiles_x * tiles_y * 170 + 85

        if detail == "auto":
            # auto 模式：短边 ≤ 768 且长边 ≤ 2048 时直接用 low
            orig_short = min(orig_width, orig_height)
            orig_long = max(orig_width, orig_height)
            if orig_short <= 768 and orig_long <= 2048:
                return 85

        return tokens

    @staticmethod
    def _glm_image_tokens(width: int, height: int) -> int:
        """
        GLM-4V / SiliconFlow GLM series image token estimation.
        Scale to fit within 1120x1120, tile into 336x336 patches,
        256 tokens per patch + 256 base tokens.
        Example: 2K(2560x1440) -> 1120x630 -> 4*2=8 patches -> 8*256+256=2304 tokens/image
        """
        max_size, patch_size, patch_tokens, base_tokens = 1120, 336, 256, 256
        if width > max_size or height > max_size:
            scale = max_size / max(width, height)
            width = int(width * scale)
            height = int(height * scale)
        return math.ceil(width / patch_size) * math.ceil(height / patch_size) * patch_tokens + base_tokens

    @staticmethod
    def _qwen_image_tokens(width: int, height: int,
                           patch_size: int = 28,
                           min_tokens: int = 4,
                           max_tokens: int = 1225) -> int:
        """
        阿里 Qwen-VL 图片 token 估算：
        将图片等比缩放至像素总数在 [min_tokens, max_tokens] * patch_size^2 范围内，
        然后 tokens = ceil(h/patch_size) * ceil(w/patch_size)
        """
        max_pixels = max_tokens * patch_size * patch_size  # 1225 * 784 = 960400
        min_pixels = min_tokens * patch_size * patch_size  # 4 * 784 = 3136

        total_pixels = width * height
        if total_pixels > max_pixels:
            scale = math.sqrt(max_pixels / total_pixels)
            width = int(width * scale)
            height = int(height * scale)
        elif total_pixels < min_pixels:
            scale = math.sqrt(min_pixels / total_pixels)
            width = int(width * scale)
            height = int(height * scale)

        tokens = math.ceil(height / patch_size) * math.ceil(width / patch_size)
        return max(min_tokens, min(max_tokens, tokens))

    def estimate_total_tokens(self, frame_paths: List[str], detail: str = "auto") -> int:
        """
        估算一批图片消耗的总 token 数，同时输出 OpenAI 风格和 Qwen 风格的对比
        """
        try:
            from PIL import Image as PILImage
        except ImportError:
            logger.warning("PIL 未安装，无法估算图片 token，返回 0")
            return 0

        total_openai = 0
        total_qwen = 0
        total_glm = 0
        for path in frame_paths:
            if not os.path.exists(path):
                continue
            try:
                with PILImage.open(path) as img:
                    w, h = img.size
                openai_tokens = self._calculate_image_tokens(w, h, detail)
                qwen_tokens = self._qwen_image_tokens(w, h)
                glm_tokens = self._glm_image_tokens(w, h)
                logger.debug(
                    f"图片 token 估算 [{os.path.basename(path)}] "
                    f"{w}x{h} → OpenAI={openai_tokens}, Qwen={qwen_tokens}, GLM={glm_tokens}"
                )
                total_openai += openai_tokens
                total_qwen += qwen_tokens
                total_glm += glm_tokens
            except Exception as e:
                logger.warning(f"读取图片尺寸失败: {path}, {e}")
        logger.info(
            f"预计图片 token 总消耗 —— "
            f"OpenAI: {total_openai}, Qwen: {total_qwen}, GLM: {total_glm}"
        )
        is_glm = 'glm' in self.model.lower()
        return total_glm if is_glm else total_openai

    def generate_description(self, frame_paths: List[str], max_images: int = 0, context_length: int = 0) -> str:
        """
        根据图像帧生成描述

        Args:
            frame_paths: 图像文件路径列表
            max_images: 单次传入的最大图片数，0 表示不限制
            context_length: 模型上下文长度限制，0 表示不限制

        Returns:
            生成的描述文本
        """
        if not frame_paths:
            raise ValueError("必须提供至少一个图像文件")

        # 若设置了最大图片数，均匀采样以覆盖整个片段
        if max_images and max_images > 0 and len(frame_paths) > max_images:
            step = len(frame_paths) / max_images
            frame_paths = [frame_paths[int(i * step)] for i in range(max_images)]
            logger.info(f"按最大图片数限制采样: {len(frame_paths)} 张")

        logger.info(f"生成描述: {len(frame_paths)} 张图像")

        # 估算图片 token 消耗，若超出 context_length 则自动裁剪
        if context_length > 0 and len(frame_paths) > 1:
            is_glm = 'glm' in self.model.lower()
            is_qwen = any(k in self.model.lower() for k in ('qwen', 'glm')) and not is_glm

            def _tokens_per_img(w, h):
                if is_glm:
                    return self._glm_image_tokens(w, h)
                elif is_qwen:
                    return self._qwen_image_tokens(w, h)
                else:
                    return self._calculate_image_tokens(w, h)

            try:
                from PIL import Image as PILImage
                first_path = next((p for p in frame_paths if os.path.exists(p)), None)
                if first_path:
                    with PILImage.open(first_path) as img:
                        fw, fh = img.size
                    tpi = _tokens_per_img(fw, fh)
                    # 留 500 tokens 给提示词和输出的余量
                    budget = max(1, (context_length - 500) // tpi)
                    if len(frame_paths) > budget:
                        step = len(frame_paths) / budget
                        frame_paths = [frame_paths[int(i * step)] for i in range(budget)]
                        logger.warning(
                            f"token 予算限制：{tpi} tokens/张 * N > {context_length}，"
                            f"自动裁剪到 {len(frame_paths)} 张"
                        )
            except Exception as e:
                logger.warning(f"token 预算检查失败: {e}")

        self.estimate_total_tokens(frame_paths)

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
            with open(frame_path, 'rb') as f:
                image_data = base64.standard_b64encode(f.read()).decode('utf-8')

            # 获取图像格式
            ext = os.path.splitext(frame_path)[1].lower()
            media_type = 'image/jpeg' if ext in ['.jpg', '.jpeg'] else 'image/png'

            content.append(
                {
                    'type': 'image_url',
                    'image_url': {
                        'url': f'data:{media_type};base64,{image_data}',
                    },
                }
            )

        logger.info(f'调用 OpenAI VLM API: model={self.model}')

        def _call_api():
            return self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        'role': 'user',
                        'content': content,
                    }
                ],
                max_tokens=500,
                temperature=0.7,
            )

        try:
            response = retry_sync(_call_api)
            description = response.choices[0].message.content.strip()
            logger.info(f"描述生成成功: {len(description)} 个字符")
            return description

        except Exception as e:
            logger.error(f"生成描述失败: {e}")
            raise RuntimeError(f"生成描述失败: {str(e)}")

    def get_model_info(self) -> dict:
        """获取模型信息"""
        return {
            'provider': 'openai',
            'model': self.model,
            'base_url': self.base_url,
            'type': 'vision',
        }
