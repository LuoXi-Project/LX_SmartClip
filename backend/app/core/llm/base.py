from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, List, Optional
import logging

logger = logging.getLogger(__name__)


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


class LLMClient:
    """通用 LLM 客户端，支持 OpenAI 兼容 API"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 20480,
        timeout: float = 60.0,
    ):
        """
        初始化 LLM 客户端。

        Args:
            base_url: API 基础 URL
            api_key: API 密钥
            model: 模型名称
            temperature: 温度参数（0-2）
            max_tokens: 最大 token 数
            timeout: 请求超时时间（秒）
        """
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise ImportError("请安装 openai: pip install openai")

        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        logger.info(
            "初始化 LLMClient: model=%s, base_url=%s, temp=%.1f, max_tokens=%d",
            model,
            base_url,
            temperature,
            max_tokens,
        )

    async def chat(
        self,
        messages: List[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        调用 LLM 进行对话。

        Args:
            messages: 消息列表，格式 [{"role": "system|user|assistant", "content": "..."}]
            temperature: 覆盖默认温度
            max_tokens: 覆盖默认 max_tokens

        Returns:
            LLM 返回的文本内容
        """
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens

        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temp,
                max_tokens=tokens,
            )
            choices = getattr(resp, "choices", None)
            if not choices:
                resp_repr: Any
                try:
                    resp_repr = resp.model_dump()  # type: ignore[attr-defined]
                except Exception:
                    resp_repr = repr(resp)
                raise RuntimeError(f"LLM 返回无 choices（可能为空响应）: {resp_repr}")

            first = choices[0]
            message = getattr(first, "message", None)
            content = getattr(message, "content", None) if message is not None else None
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("LLM 返回 content 为空或非字符串")
            return content.strip()
        except Exception as e:
            logger.error("LLM 调用失败: %s", e)
            raise

    async def chat_stream(
        self,
        messages: List[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """
        流式对话：按模型返回顺序产出 content 文本片段（delta）。
        """
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens

        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temp,
                max_tokens=tokens,
                stream=True,
            )
            async for chunk in stream:
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                if delta is None:
                    continue
                piece = getattr(delta, "content", None)
                if isinstance(piece, str) and piece:
                    yield piece
        except Exception as e:
            logger.error("LLM 流式调用失败: %s", e)
            raise

    def get_config(self) -> dict:
        """返回客户端配置信息"""
        return {
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
        }
