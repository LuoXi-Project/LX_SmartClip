"""
LLM 提示词集中目录。

约定：
- 不在此目录放“调用 LLM 的逻辑”，只放 system/user prompt 字符串、schema hint、以及轻量的 prompt builder。
- 业务模块通过 import 方式获取提示词，避免提示词散落在多处导致维护困难。
"""

__all__ = []

