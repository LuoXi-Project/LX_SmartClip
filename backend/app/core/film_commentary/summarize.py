from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from app.core.llm import LLMClient
from app.core.llm.response_utils import extract_json_object
from app.core.film_commentary.prompts import summarize_system_prompt, summarize_user_prompt

logger = logging.getLogger(__name__)

_BATCH_SIZE = 18


def _clip_payload_line(c: dict, *, mode: str) -> str:
    parts = [f"clip_id={c['id']}", f"时长={c.get('duration') or 0:.1f}s"]
    asr = (c.get("asr_text") or "").strip()
    if asr:
        parts.append(f"台词={asr[:400]}")
    vlm = (c.get("vlm_description") or "").strip()
    if mode == "precise" and vlm:
        parts.append(f"画面={vlm[:500]}")
    return " | ".join(parts)


async def summarize_clips(
    *,
    llm: LLMClient,
    clips: List[dict],
    mode: str,
) -> List[Dict[str, Any]]:
    """L2：单切片剧情摘要。"""
    out: List[Dict[str, Any]] = []
    for i in range(0, len(clips), _BATCH_SIZE):
        batch = clips[i : i + _BATCH_SIZE]
        lines = [_clip_payload_line(c, mode=mode) for c in batch]
        user = summarize_user_prompt("\n".join(lines))
        raw = await llm.chat(
            [
                {"role": "system", "content": summarize_system_prompt(mode=mode)},
                {"role": "user", "content": user},
            ],
            temperature=0.4,
        )
        try:
            data = json.loads(extract_json_object(raw))
        except Exception as e:
            logger.warning("摘要批次解析失败，使用兜底: %s", e)
            data = []
        if isinstance(data, dict):
            data = data.get("summaries") or data.get("items") or []
        if not isinstance(data, list):
            data = []
        by_id = {str(x.get("clip_id")): x for x in data if isinstance(x, dict)}
        for c in batch:
            item = by_id.get(c["id"])
            if item:
                out.append(
                    {
                        "clip_id": c["id"],
                        "summary": (item.get("summary") or "").strip()[:200],
                        "role": (item.get("role") or "过渡").strip(),
                        "mood": (item.get("mood") or "").strip(),
                        "start_time": c.get("start_time"),
                    }
                )
            else:
                fallback = (c.get("asr_text") or c.get("vlm_description") or "无对白画面")[:80]
                out.append(
                    {
                        "clip_id": c["id"],
                        "summary": fallback,
                        "role": "过渡",
                        "mood": "",
                        "start_time": c.get("start_time"),
                    }
                )
    out.sort(key=lambda x: float(x.get("start_time") or 0))
    return out
