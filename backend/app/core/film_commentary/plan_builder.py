from __future__ import annotations

import uuid
from typing import List

from app.models.auto_edit import (
    ClipRef,
    Constraints,
    Plan,
    SegmentPlan,
    SubtitlePlan,
)
from app.models.film_commentary import FilmAlignment, FilmSentence


def build_plan_from_alignments(
    *,
    video_id: str,
    video_name: str,
    sentences: List[FilmSentence],
    alignments: List[FilmAlignment],
    target_duration_sec: int,
    storyline: dict | None,
) -> Plan:
    """L5：将分句对齐结果编译为 auto_edit Plan（TTS 解说轨）。"""
    sent_map = {s.index: s for s in sentences}
    segments: List[SegmentPlan] = []
    order = 0
    for al in alignments:
        sent = sent_map.get(al.sentence_index)
        if not sent:
            continue
        order += 1
        dur = max(2.5, min(12.0, len(sent.text) / 4.5))
        segments.append(
            SegmentPlan(
                id=f"film_seg_{order}",
                order=order,
                clip_group=[ClipRef(clip_id=al.clip_id, video_id=video_id, weight=1.0)],
                selected_clip_ids=[al.clip_id],
                start_time_sec=0.0,
                end_time_sec=dur,
                override_duration_sec=dur,
                audio_mode="tts",
                subtitle=SubtitlePlan(
                    strategy="rewrite",
                    text=sent.text,
                    source="llm",
                ),
            )
        )

    summary_parts = []
    if storyline:
        for k, v in storyline.items():
            if v:
                summary_parts.append(f"{k}: {v}")
    summary = " · ".join(summary_parts[:3]) if summary_parts else "影视解说一键成片"

    return Plan(
        plan_id=str(uuid.uuid4()),
        title=video_name or "影视解说",
        summary=summary[:500],
        mode="voiceover",
        target_duration_sec=float(target_duration_sec),
        estimated_duration_sec=float(sum(s.end_time_sec for s in segments)),
        segments=segments,
        constraints=Constraints(
            max_clip_per_segment=1,
            match_strategy="asr+vlm",
            respect_user_video_order=True,
            split_narration_by_sentence=True,
        ),
    )
