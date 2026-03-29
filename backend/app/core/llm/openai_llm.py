import json
import logging
from typing import List

from app.core.llm.base import ILLM
from app.core.retry import retry_sync

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

    def rank(self, query: str, candidates: List[dict]) -> List[dict]:
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
            cand_lines.append(
                f"[{i+1}] clip_id={c['clip_id']}\n"
                f"    台词: {asr or '（无）'}\n"
                f"    画面: {vlm or '（无）'}"
            )
        cand_text = "\n".join(cand_lines)

        system_prompt = (
            "你是一位专业的视频剪辑顾问。"
            "用户提供了一段文案，你需要从候选视频片段中挑选最匹配的片段并给出评分。\n"
            "评分标准：\n"
            "  - 内容相关性（文案与台词/画面的语义匹配程度）\n"
            "  - 情感一致性（视频情绪与文案情感的契合度）\n"
            "  - 视觉适配性（画面内容是否适合配合文案呈现）\n"
            "请以 JSON 数组格式返回结果，每项包含 clip_id、score（0-10浮点数）、reason（中文简短理由）。"
            "只返回 JSON，不要任何额外文字。"
        )

        user_prompt = (
            f"用户文案：\n{query}\n\n"
            f"候选片段（共 {len(candidates)} 个）：\n{cand_text}\n\n"
            "请对所有片段评分并按分数从高到低排列，返回 JSON 数组。"
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
                    max_tokens=1024,
                )

            resp = retry_sync(_call_api)
            raw = resp.choices[0].message.content.strip()
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
