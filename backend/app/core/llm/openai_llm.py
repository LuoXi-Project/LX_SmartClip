import json
import logging
from typing import Callable, List, Optional

from app.core.llm.base import ILLM
from app.core.retry import retry_sync
from app.core.metrics.token_usage import TokenUsage, extract_usage

logger = logging.getLogger(__name__)


class OpenAILLM(ILLM):
    """OpenAI 兼容 LLM 实现，用于片段精排"""

    def __init__(self, base_url: str, model: str, api_key: str):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("请安装 openai: pip install openai")

        self.model = model
        self.base_url = base_url
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        logger.info("初始化 OpenAILLM: model=%s", model)

    def rank(
        self,
        query: str,
        candidates: List[dict],
        *,
        on_usage: Optional[Callable[[Optional[TokenUsage]], None]] = None,
    ) -> List[dict]:
        """
        使用 LLM 对候选片段精排。

        每个 candidate 期望包含:
            clip_id, asr_text, vlm_description

        返回列表每项新增:
            score (float 0-10), reason (str)
        """
        if not candidates:
            return []

        # 构造候选列表文本
        cand_lines = []
        for i, c in enumerate(candidates):
            asr = (c.get("asr_text") or "").strip()
            vlm = (c.get("vlm_description") or "").strip()
            summary = (c.get("abstract_summary") or "").strip()
            kw = c.get("keywords")
            if isinstance(kw, str):
                kw = kw.strip()
            elif isinstance(kw, list):
                kw = "、".join(str(x).strip() for x in kw if str(x).strip())
            else:
                kw = ""
            em = c.get("emotion_tags")
            if isinstance(em, str):
                em = em.strip()
            elif isinstance(em, list):
                em = "、".join(str(x).strip() for x in em if str(x).strip())
            else:
                em = ""
            extra = ""
            if summary or kw or em:
                parts = []
                if summary:
                    parts.append(f"适配旁白摘要: {summary}")
                if kw:
                    parts.append(f"关键词: {kw}")
                if em:
                    parts.append(f"情绪: {em}")
                extra = "\n    " + "；".join(parts)
            cand_lines.append(
                f"[{i+1}] clip_id={c['clip_id']}\n"
                f"    台词: {asr or '（无）'}\n"
                f"    画面: {vlm or '（无）'}{extra}"
            )
        cand_text = "\n".join(cand_lines)

        system_prompt = (
            "你是一位资深的影视解说剪辑师。用户提供的是「旁白解说文案」——"
            "这是创作者视角的抽象叙述（如「相恋多年的感情终究敌不过现实重压」），"
            "候选片段提供的是「原片台词」和「画面描述」——这是场景视角的具体内容"
            "（如「女人愤怒摔门离开」），并附带「适配旁白摘要/关键词/情绪」标注。\n"
            "你的核心任务：判断每段旁白在语义上适合配合哪个画面。"
            "重点注意——文案与画面常常处于不同抽象层级、用词几乎不重叠，"
            "你必须做「跨层语义对齐」，而不是字面匹配：\n"
            "  - 情节/主题吻合度：旁白描述的情节、主题、事件是否与画面内容呼应"
            "（抽象表述可对应具体场景，如「决然离去」对应「摔门离开」）；\n"
            "  - 情绪/氛围契合度：旁白的情感基调是否与画面的情绪/情绪标签一致；\n"
            "  - 解说适配性：该画面是否适合作为这段旁白的解说画面（视觉信息量、相关性）。\n"
            "评分范围 0-10（保留一位小数）：\n"
            "  - 9-10 几乎完美匹配（情节+情绪双吻合，是理想解说画面）；\n"
            "  - 6-8 较好匹配（主题或情绪其一吻合，可用）；\n"
            "  - 3-5 弱相关（勉强沾边但不够贴切）；\n"
            "  - 0-2 不相关。\n"
            "请以 JSON 数组格式返回结果，每项包含 clip_id、score（0-10 浮点数）、"
            "reason（中文简短理由，说明对齐依据）。按分数从高到低排列。只返回 JSON 数组，不要任何额外文字。"
        )

        user_prompt = (
            f"旁白解说文案：\n{query}\n\n"
            f"候选片段（共 {len(candidates)} 个）：\n{cand_text}\n\n"
            "请基于「跨层语义对齐」原则对所有片段评分，返回按分数降序排列的 JSON 数组。"
        )

        try:
            logger.info("LLM 精排: query_len=%d, candidates=%d", len(query), len(candidates))

            def _call_api():
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.2,
                    max_tokens=20480,
                )

            resp = retry_sync(_call_api)
            if on_usage is not None:
                try:
                    on_usage(extract_usage(resp))
                except Exception:
                    pass
            choices = getattr(resp, "choices", None)
            if not choices:
                raise RuntimeError("LLM 返回无 choices（可能为空响应）")
            message = getattr(choices[0], "message", None)
            content = getattr(message, "content", None) if message is not None else None
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("LLM 返回 content 为空或非字符串")
            raw = content.strip()
            logger.debug("LLM 原始返回: %r", raw[:500])

            # 去除 thinking 模型的 <think>...</think> 块（含变体格式）
            import re
            raw = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()

            # 提取 JSON（兼容 markdown 代码块）
            if "```" in raw:
                parts = raw.split("```")
                raw = parts[1] if len(parts) > 1 else parts[0]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            # 兜底：直接定位 JSON 数组范围
            start = raw.find("[")
            end = raw.rfind("]")
            if start != -1 and end != -1 and end > start:
                raw = raw[start:end + 1]

            logger.debug("LLM 提取后 JSON: %r", raw[:500])

            try:
                ranked = json.loads(raw)
            except json.JSONDecodeError:
                # 尝试用 json_repair 修复
                try:
                    from json_repair import repair_json
                    ranked = json.loads(repair_json(raw))
                    logger.warning("LLM 返回 JSON 格式有误，已自动修复")
                except Exception:
                    raise

            # 与候选数据合并
            clip_map = {c["clip_id"]: c for c in candidates}
            result = []
            for item in ranked:
                cid = item.get("clip_id")
                if cid and cid in clip_map:
                    merged = dict(clip_map[cid])
                    merged["score"] = float(item.get("score", 0))
                    merged["reason"] = item.get("reason", "")
                    result.append(merged)

            # 补充未被 LLM 返回的片段（score=0）
            returned_ids = {r["clip_id"] for r in result}
            for c in candidates:
                if c["clip_id"] not in returned_ids:
                    merged = dict(c)
                    merged["score"] = 0.0
                    merged["reason"] = "未被模型评分"
                    result.append(merged)

            result.sort(key=lambda x: x["score"], reverse=True)
            logger.info("LLM 精排完成: %d 个结果", len(result))
            return result

        except Exception as e:
            logger.error("LLM 精排失败: %s", e)
            # 降级：直接返回候选，score 均为 0
            fallback = [dict(c, score=0.0, reason=f"LLM 精排失败: {e}") for c in candidates]
            return fallback

    def get_model_info(self) -> dict:
        return {
            "provider": "openai",
            "model": self.model,
            "base_url": self.base_url,
        }
