import logging
from typing import Any, Callable, Dict, List, Optional

import httpx

from app.core.metrics.token_usage import TokenUsage, extract_usage

logger = logging.getLogger(__name__)


def _coerce_volc_ark_dimensions(vector_dim: Optional[int]) -> int:
    """
    火山方舟多模态 embedding 仅支持 dimensions ∈ {1024, 2048}，默认 2048。
    与设置项 vector_dimension 对齐，避免入库维度与 API 输出不一致。
    """
    if vector_dim == 1024:
        return 1024
    if vector_dim == 2048:
        return 2048
    if vector_dim is not None and vector_dim not in (1024, 2048):
        logger.warning(
            "vector_dimension=%s 非 1024/2048，火山方舟请求将使用 dimensions=2048；请将 vector_dimension 设为 1024 或 2048",
            vector_dim,
        )
    return 2048


def _is_volcengine_ark_multimodal_embed_url(base_url: str) -> bool:
    """火山方舟多模态向量：POST .../api/v3/embeddings/multimodal，与 OpenAI /v1/embeddings 不同。"""
    u = (base_url or "").strip().lower()
    if "volces.com" not in u:
        return False
    return "embeddings/multimodal" in u


def _parse_embedding_vector(body: Dict[str, Any]) -> List[float]:
    data = body.get("data")
    # 火山方舟：data 为对象 { "embedding": [...], "object": "embedding" }
    if isinstance(data, dict):
        emb = data.get("embedding")
        if isinstance(emb, list) and emb:
            return [float(x) for x in emb]
    # OpenAI 风格：data 为 [{ "embedding": [...], "index": 0 }, ...]
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            emb = first.get("embedding")
            if isinstance(emb, list) and emb:
                return [float(x) for x in emb]
    emb = body.get("embedding")
    if isinstance(emb, list) and emb:
        return [float(x) for x in emb]
    raise RuntimeError(f"响应中未找到 embedding 数组: keys={list(body.keys())}")


class Embedder:
    """文本向量化：OpenAI 兼容 /v1/embeddings，或火山方舟 /embeddings/multimodal。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "text-embedding-3-small",
        request_timeout_sec: float = 120.0,
        volc_output_dimensions: Optional[int] = None,
    ):
        self.model = model
        self.request_timeout_sec = max(1.0, float(request_timeout_sec or 120.0))
        self._base_url = (base_url or "").strip()
        self._api_key = api_key
        self._volc_multimodal = _is_volcengine_ark_multimodal_embed_url(self._base_url)
        self._volc_dimensions = _coerce_volc_ark_dimensions(volc_output_dimensions)
        self.client = None

        if self._volc_multimodal:
            logger.info(
                "初始化 Embedder (火山方舟多模态): model=%s, dimensions=%s, timeout=%ss",
                model,
                self._volc_dimensions,
                self.request_timeout_sec,
            )
            return

        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError("请安装 openai: pip install openai") from e

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        logger.info("初始化 Embedder: model=%s, timeout=%ss", model, self.request_timeout_sec)

    def _embed_volcengine(self, text: str) -> tuple[List[float], Optional[Dict[str, Any]]]:
        url = self._base_url.rstrip("/")
        payload = {
            "model": self.model,
            "dimensions": self._volc_dimensions,
            "input": [{"type": "text", "text": text}],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self.request_timeout_sec) as client:
            r = client.post(url, json=payload, headers=headers)
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as e:
                snippet = (r.text or "")[:500]
                raise RuntimeError(f"火山方舟 Embedding HTTP {r.status_code}: {snippet}") from e
            body = r.json()
        if not isinstance(body, dict):
            raise RuntimeError("火山方舟 Embedding 响应不是 JSON 对象")
        vec = _parse_embedding_vector(body)
        return vec, body

    def embed(
        self,
        text: str,
        on_usage: Optional[Callable[[Optional[TokenUsage]], None]] = None,
    ) -> List[float]:
        if not text or not text.strip():
            raise ValueError("输入文本不能为空")

        if self._volc_multimodal:
            try:
                logger.info("生成 Embedding (火山方舟): %d 个字符", len(text))
                embedding, raw = self._embed_volcengine(text)
                if on_usage is not None:
                    try:
                        on_usage(extract_usage(raw))
                    except Exception:
                        pass
                logger.info("Embedding 生成成功: 维度=%d", len(embedding))
                return embedding
            except RuntimeError:
                raise
            except Exception as e:
                logger.error("生成 Embedding 失败: %s", e)
                raise RuntimeError(f"生成 Embedding 失败: {e!s}") from e

        try:
            logger.info("生成 Embedding: %d 个字符", len(text))
            response = self.client.embeddings.create(
                model=self.model,
                input=text,
                timeout=self.request_timeout_sec,
            )
            if on_usage is not None:
                try:
                    on_usage(extract_usage(response))
                except Exception:
                    pass
            embedding = response.data[0].embedding
            logger.info("Embedding 生成成功: 维度=%d", len(embedding))
            return embedding
        except Exception as e:
            logger.error("生成 Embedding 失败: %s", e)
            raise RuntimeError(f"生成 Embedding 失败: {e!s}") from e

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []

        if self._volc_multimodal:
            logger.info("批量生成 Embedding (火山方舟): %d 个文本", len(texts))
            out: List[List[float]] = []
            for t in texts:
                out.append(self.embed(t))
            logger.info("批量 Embedding 生成成功: %d 个向量", len(out))
            return out

        try:
            logger.info("批量生成 Embedding: %d 个文本", len(texts))
            response = self.client.embeddings.create(
                model=self.model,
                input=texts,
                timeout=self.request_timeout_sec,
            )
            embeddings = [item.embedding for item in response.data]
            logger.info("批量 Embedding 生成成功: %d 个向量", len(embeddings))
            return embeddings
        except Exception as e:
            logger.error("批量生成 Embedding 失败: %s", e)
            raise RuntimeError(f"批量生成 Embedding 失败: {e!s}") from e

    def get_model_info(self) -> dict:
        return {
            "provider": "volcengine" if self._volc_multimodal else "openai",
            "model": self.model,
        }

    def close(self) -> None:
        try:
            close_fn = getattr(self.client, "close", None)
            if callable(close_fn):
                close_fn()
        except Exception:
            pass
