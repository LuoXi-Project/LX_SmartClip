import logging
from typing import Callable, List, Optional
from app.core.metrics.token_usage import extract_usage, TokenUsage

logger = logging.getLogger(__name__)


class Embedder:
    """文本向量化器，调用 OpenAI Embedding API"""

    def __init__(self, base_url: str, api_key: str, model: str = "text-embedding-3-small"):
        """
        初始化 Embedder
        
        Args:
            base_url: OpenAI API 基础 URL
            api_key: API Key
            model: Embedding 模型名称
        """
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("请安装 openai: pip install openai")

        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        logger.info(f"初始化 Embedder: model={model}")

    def embed(
        self,
        text: str,
        on_usage: Optional[Callable[[Optional[TokenUsage]], None]] = None,
    ) -> List[float]:
        """
        生成文本的向量嵌入
        
        Args:
            text: 输入文本
            
        Returns:
            向量嵌入（浮点数列表）
        """
        if not text or not text.strip():
            raise ValueError("输入文本不能为空")

        try:
            logger.info(f"生成 Embedding: {len(text)} 个字符")
            response = self.client.embeddings.create(
                model=self.model,
                input=text,
            )
            if on_usage is not None:
                try:
                    on_usage(extract_usage(response))
                except Exception:
                    pass
            embedding = response.data[0].embedding
            logger.info(f"Embedding 生成成功: 维度={len(embedding)}")
            return embedding
        except Exception as e:
            logger.error(f"生成 Embedding 失败: {e}")
            raise RuntimeError(f"生成 Embedding 失败: {str(e)}")

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        批量生成文本的向量嵌入
        
        Args:
            texts: 输入文本列表
            
        Returns:
            向量嵌入列表
        """
        if not texts:
            return []

        try:
            logger.info(f"批量生成 Embedding: {len(texts)} 个文本")
            response = self.client.embeddings.create(
                model=self.model,
                input=texts,
            )
            embeddings = [item.embedding for item in response.data]
            logger.info(f"批量 Embedding 生成成功: {len(embeddings)} 个向量")
            return embeddings
        except Exception as e:
            logger.error(f"批量生成 Embedding 失败: {e}")
            raise RuntimeError(f"批量生成 Embedding 失败: {str(e)}")

    def get_model_info(self) -> dict:
        """获取模型信息"""
        return {
            "provider": "openai",
            "model": self.model,
        }

    def close(self) -> None:
        """显式关闭底层 HTTP 客户端（在短生命周期子进程中可避免退出阶段挂起）。"""
        try:
            close_fn = getattr(self.client, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass
