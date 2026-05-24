from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Tuple

from app.core.llm import LLMClient
from app.core.llm.response_utils import extract_json_object
from app.core.film_commentary.prompts import screenplay_system_prompt, screenplay_user_prompt
from app.models.film_commentary import FilmSentence

logger = logging.getLogger(__name__)


def _summaries_to_text(summaries: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for s in summaries:
        lines.append(
            f"[{s.get('clip_id')}] ({s.get('role','')}) {s.get('summary','')}"
        )
    return "\n".join(lines)


async def generate_screenplay(
    *,
    llm: LLMClient,
    summaries: List[Dict[str, Any]],
    video_name: str,
    style: str,
    target_duration_sec: int,
    system_prompt: str | None = None,
    user_prompt_template: str | None = None,
) -> Tuple[Dict[str, Any], List[FilmSentence]]:
    """L3：六段式故事线 + 分句解说文案。"""
    sys_content = (system_prompt or "").strip() or screenplay_system_prompt(
        style=style,
        target_duration_sec=target_duration_sec,
    )
    user = screenplay_user_prompt(
        summaries_text=_summaries_to_text(summaries),
        video_name=video_name,
        template=user_prompt_template,
    )
    raw = await llm.chat(
        [
            {"role": "system", "content": sys_content},
            {"role": "user", "content": user},
        ],
        temperature=0.75,
    )
    data = json.loads(extract_json_object(raw))
    storyline = data.get("storyline") if isinstance(data, dict) else {}
    if not isinstance(storyline, dict):
        storyline = {}

    sentences_raw = data.get("sentences") if isinstance(data, dict) else []
    sentences: List[FilmSentence] = []
    if isinstance(sentences_raw, list):
        for i, row in enumerate(sentences_raw, start=1):
            if not isinstance(row, dict):
                continue
            text = (row.get("text") or "").strip()
            if not text:
                continue
            sentences.append(
                FilmSentence(
                    index=int(row.get("index") or i),
                    text=text,
                    tag=(row.get("tag") or "").strip() or None,
                )
            )
    if not sentences:
        # 兜底：用故事线拼几句
        for k, v in storyline.items():
            if v and isinstance(v, str):
                sentences.append(FilmSentence(index=len(sentences) + 1, text=v[:120], tag=k))
    sentences.sort(key=lambda s: s.index)
    return storyline, sentences
