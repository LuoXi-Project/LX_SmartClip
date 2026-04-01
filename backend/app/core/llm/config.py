"""LLM 配置管理工具"""
import logging
from typing import Optional
import aiosqlite

logger = logging.getLogger(__name__)


class LLMConfig:
    """从数据库读取 LLM 配置的工具类"""

    @staticmethod
    async def read_config(db: aiosqlite.Connection, key: str, default: str = "") -> str:
        """从 config 表读取配置值"""
        async with db.execute("SELECT value FROM config WHERE key = ?", (key,)) as c:
            row = await c.fetchone()
        return row[0] if row else default

    @staticmethod
    async def get_llm_params(
        db: aiosqlite.Connection,
        base_url_key: str = "llm_base_url",
        api_key_key: str = "llm_api_key",
        model_key: str = "llm_model",
        fallback_model_key: str = "vlm_model",
    ) -> tuple[str, str, str]:
        """
        获取 LLM 必需的三个参数：base_url, api_key, model

        Args:
            db: 数据库连接
            base_url_key: base_url 配置键
            api_key_key: api_key 配置键
            model_key: 主模型配置键
            fallback_model_key: 备用模型配置键（当主模型为空时使用）

        Returns:
            (base_url, api_key, model) 元组

        Raises:
            ValueError: 如果任何必需参数缺失
        """
        base_url = await LLMConfig.read_config(db, base_url_key)
        api_key = await LLMConfig.read_config(db, api_key_key)
        model = await LLMConfig.read_config(db, model_key)

        if not model:
            model = await LLMConfig.read_config(db, fallback_model_key)

        if not base_url or not api_key or not model:
            missing = []
            if not base_url:
                missing.append(base_url_key)
            if not api_key:
                missing.append(api_key_key)
            if not model:
                missing.append(f"{model_key} 或 {fallback_model_key}")
            raise ValueError(f"LLM 配置缺失: {', '.join(missing)}")

        return base_url, api_key, model

    @staticmethod
    async def get_llm_params_with_defaults(
        db: aiosqlite.Connection,
        base_url_key: str = "llm_base_url",
        api_key_key: str = "llm_api_key",
        model_key: str = "llm_model",
        fallback_model_key: str = "vlm_model",
        temperature_key: str = "llm_temperature",
        max_tokens_key: str = "llm_max_tokens",
        default_temperature: float = 0.7,
        default_max_tokens: int = 20480,
    ) -> dict:
        """
        获取 LLM 的完整配置参数，包括可选的 temperature 和 max_tokens

        Args:
            db: 数据库连接
            base_url_key: base_url 配置键
            api_key_key: api_key 配置键
            model_key: 主模型配置键
            fallback_model_key: 备用模型配置键
            temperature_key: temperature 配置键
            max_tokens_key: max_tokens 配置键
            default_temperature: temperature 默认值
            default_max_tokens: max_tokens 默认值

        Returns:
            包含 base_url, api_key, model, temperature, max_tokens 的字典

        Raises:
            ValueError: 如果必需参数缺失
        """
        base_url, api_key, model = await LLMConfig.get_llm_params(
            db, base_url_key, api_key_key, model_key, fallback_model_key
        )

        temp_str = await LLMConfig.read_config(db, temperature_key, str(default_temperature))
        tokens_str = await LLMConfig.read_config(db, max_tokens_key, str(default_max_tokens))

        try:
            temperature = float(temp_str)
        except (ValueError, TypeError):
            logger.warning("无效的 temperature 配置: %s，使用默认值 %f", temp_str, default_temperature)
            temperature = default_temperature

        try:
            max_tokens = int(tokens_str)
        except (ValueError, TypeError):
            logger.warning("无效的 max_tokens 配置: %s，使用默认值 %d", tokens_str, default_max_tokens)
            max_tokens = default_max_tokens

        return {
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
