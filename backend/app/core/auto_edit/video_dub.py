"""视频配音：保留原片时间轴与镜头编排，仅替换/生成旁白并 TTS 合成。"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Literal, Sequence

import aiosqlite

from app.core.auto_edit.mix_edit import _extract_asr_sentence_segments, _row_vlm, classify_clip_tier
from app.core.auto_edit.mix_edit_tts_balance import (
    CHARS_PER_SEC_TTS,
    SegmentTtsBudget,
    clamp_script_texts_to_budgets,
    max_chars_for_video_dub_duration,
    segment_video_duration_sec,
)
from app.core.llm import LLMClient
from app.core.llm.response_utils import extract_json_object
from app.models.auto_edit import (
    ClipRef,
    Constraints,
    Plan,
    PlanKeepFlags,
    SegmentPlan,
    SubtitlePlan,
    TimingHint,
)

logger = logging.getLogger(__name__)

VideoDubContentSource = Literal["asr_rewrite", "asr_literal", "vlm_narrate", "auto"]
_MIN_GAP_FILL_SEC = 0.12


def _segment_from_range(
    *,
    row: Any,
    order: int,
    st_abs: float,
    et_abs: float,
    text: str,
    audio_mode: Literal["tts", "mute", "original"],
    subtitle_strategy: Literal["asr", "rewrite", "none", "auto"] = "asr",
    subtitle_source: Literal["asr", "llm", "vlm", "user"] = "asr",
) -> SegmentPlan | None:
    cid = str(row["id"])
    vid = str(row["video_id"])
    clip_base = float(row["start_time"] or 0.0)
    dur = et_abs - st_abs
    if dur <= 0.05:
        return None
    st_rel = max(0.0, st_abs - clip_base)
    return SegmentPlan(
        id=f"vdub_{order:04d}_{cid[:8]}",
        order=order,
        clip_group=[ClipRef(clip_id=cid, video_id=vid, weight=1.0)],
        selected_clip_ids=[cid],
        start_time_sec=st_abs,
        end_time_sec=et_abs,
        override_duration_sec=dur,
        clip_start_offset_sec=st_rel,
        audio_mode=audio_mode,
        subtitle=SubtitlePlan(
            strategy=subtitle_strategy,
            text=text,
            source=subtitle_source,
            timing_hint=TimingHint(start=st_abs, end=et_abs),
        ),
    )


def _vlm_narration_stub(row: Any) -> str:
    vlm = (_row_vlm(row) or "").strip()
    if vlm:
        return vlm[:280]
    return "（根据画面内容解说）"


def _build_vlm_narrate_full_timeline(
    clip_rows: Sequence[Any],
) -> tuple[list[SegmentPlan], dict[str, int]]:
    """
    画面解说：每个 clip 都进入成片（有 VLM 则配音，无 VLM 则保留画面静音），
    避免只导出「有标注的碎片」导致总时长远短于原片。
    """
    tier_counts: dict[str, int] = {}
    segments: list[SegmentPlan] = []
    order = 0
    for row in clip_rows:
        try:
            asr_val = row["asr_text"]
        except (KeyError, IndexError, TypeError):
            asr_val = None
        tier = classify_clip_tier(asr_text=asr_val, vlm_description=_row_vlm(row))
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

        clip_base = float(row["start_time"] or 0.0)
        clip_dur = float(row["duration"] or 0.0)
        if clip_dur <= 0.05:
            continue
        clip_end = clip_base + clip_dur
        has_vlm = bool((_row_vlm(row) or "").strip())

        if has_vlm:
            seg = _segment_from_range(
                row=row,
                order=order,
                st_abs=clip_base,
                et_abs=clip_end,
                text=_vlm_narration_stub(row),
                audio_mode="tts",
                subtitle_strategy="auto",
                subtitle_source="vlm",
            )
        else:
            seg = _segment_from_range(
                row=row,
                order=order,
                st_abs=clip_base,
                et_abs=clip_end,
                text="",
                audio_mode="mute",
                subtitle_strategy="none",
                subtitle_source="vlm",
            )
        if seg:
            segments.append(seg)
            order += 1
    return segments, tier_counts


def build_video_dub_timeline_segments(
    clip_rows: Sequence[Any],
    *,
    content_source: VideoDubContentSource,
    preserve_gaps: bool,
) -> tuple[list[SegmentPlan], dict[str, int]]:
    """按素材时间顺序生成段落，尽量保持原片编排；统计各 tier 数量。"""
    if content_source == "vlm_narrate":
        return _build_vlm_narrate_full_timeline(clip_rows)

    tier_counts: dict[str, int] = {}
    segments: list[SegmentPlan] = []
    order = 0

    for row in clip_rows:
        try:
            asr_val = row["asr_text"]
        except (KeyError, IndexError, TypeError):
            asr_val = None
        tier = classify_clip_tier(asr_text=asr_val, vlm_description=_row_vlm(row))
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

        clip_base = float(row["start_time"] or 0.0)
        clip_dur = float(row["duration"] or 0.0)
        clip_end = clip_base + max(0.0, clip_dur)

        use_asr = content_source in ("asr_rewrite", "asr_literal", "auto") and tier in (
            "asr_vlm",
            "asr_only",
        )
        use_vlm = content_source in ("vlm_narrate", "auto") and tier in ("asr_vlm", "vlm_only")

        if use_asr:
            spans = _extract_asr_sentence_segments(row)
            if spans:
                prev_et = clip_base
                for st_abs, et_abs, text in spans:
                    if preserve_gaps and st_abs - prev_et >= _MIN_GAP_FILL_SEC:
                        gap_seg = _segment_from_range(
                            row=row,
                            order=order,
                            st_abs=prev_et,
                            et_abs=st_abs,
                            text="",
                            audio_mode="mute",
                            subtitle_strategy="none",
                            subtitle_source="asr",
                        )
                        if gap_seg:
                            segments.append(gap_seg)
                            order += 1
                    seg = _segment_from_range(
                        row=row,
                        order=order,
                        st_abs=st_abs,
                        et_abs=et_abs,
                        text=text,
                        audio_mode="tts",
                        subtitle_strategy="asr",
                        subtitle_source="asr",
                    )
                    if seg:
                        segments.append(seg)
                        order += 1
                    prev_et = et_abs
                if preserve_gaps and clip_end - prev_et >= _MIN_GAP_FILL_SEC:
                    gap_seg = _segment_from_range(
                        row=row,
                        order=order,
                        st_abs=prev_et,
                        et_abs=clip_end,
                        text="",
                        audio_mode="mute",
                        subtitle_strategy="none",
                        subtitle_source="asr",
                    )
                    if gap_seg:
                        segments.append(gap_seg)
                        order += 1
                continue

        if use_vlm and clip_dur > 0:
            text = _vlm_narration_stub(row)
            seg = _segment_from_range(
                row=row,
                order=order,
                st_abs=clip_base,
                et_abs=clip_end,
                text=text,
                audio_mode="tts",
                subtitle_strategy="auto",
                subtitle_source="vlm",
            )
            if seg:
                segments.append(seg)
                order += 1
            continue

        if clip_dur > 0 and preserve_gaps:
            seg = _segment_from_range(
                row=row,
                order=order,
                st_abs=clip_base,
                et_abs=clip_end,
                text="",
                audio_mode="mute",
                subtitle_strategy="none",
                subtitle_source="asr",
            )
            if seg:
                segments.append(seg)
                order += 1

    return segments, tier_counts


def build_video_dub_plan(
    *,
    clip_rows: Sequence[Any],
    content_source: VideoDubContentSource,
    video_title_hint: str | None,
    preserve_gaps: bool = True,
) -> Plan:
    segments, tier_counts = build_video_dub_timeline_segments(
        clip_rows,
        content_source=content_source,
        preserve_gaps=preserve_gaps,
    )
    tts_count = sum(1 for s in segments if s.audio_mode == "tts")
    if tts_count == 0:
        raise ValueError(
            "无法生成配音方案：所选视频需至少有一段 ASR 或 VLM 标注。"
            "请先在素材处理中完成语音识别或画面理解。"
        )

    total = sum(
        float(s.override_duration_sec or 0)
        for s in segments
        if not s.exclude_from_output
    )
    src_label = {
        "asr_rewrite": "ASR 洗稿配音",
        "asr_literal": "ASR 原文配音",
        "vlm_narrate": "画面解说配音",
        "auto": "智能（ASR 优先，无则 VLM）",
    }[content_source]
    vt = (video_title_hint or "").strip()
    title = f"视频配音 · {src_label}" + (f" · {vt}" if vt else "")
    vlm_note = ""
    if content_source == "vlm_narrate":
        mute_n = sum(1 for s in segments if s.audio_mode == "mute")
        if mute_n:
            vlm_note = f" 无 VLM 的 {mute_n} 段保留画面（静音）。"
    summary = (
        f"保留原片时间轴：共 {len(segments)} 段（TTS {tts_count} 段），"
        f"预估画面时长约 {total:.1f}s；素材分级 {_format_tier(tier_counts)}。"
        f"{vlm_note} 建议对齐策略选「保留画面时长」；配音过长定格/循环，过短不裁画面。"
    )

    return Plan(
        plan_id=uuid.uuid4().hex[:8],
        title=title,
        summary=summary,
        video_title=vt or None,
        video_description=None,
        mode="voiceover",
        target_duration_sec=round(total, 2) if total > 0 else None,
        estimated_duration_sec=round(total, 2) if total > 0 else None,
        segments=segments,
        constraints=Constraints(
            match_strategy="asr+vlm",
            split_narration_by_sentence=False,
        ),
        keep_flags=PlanKeepFlags(),
        bgm=None,
    )


def _format_tier(tier_counts: dict[str, int]) -> str:
    parts = [f"{k}×{v}" for k, v in sorted(tier_counts.items()) if v > 0]
    return ", ".join(parts) if parts else "无"


def _budgets_for_segments(segments: list[SegmentPlan]) -> list[SegmentTtsBudget]:
    budgets: list[SegmentTtsBudget] = []
    for i, seg in enumerate(segments):
        video_sec = segment_video_duration_sec(seg)
        mc = max_chars_for_video_dub_duration(video_sec)
        cid = seg.selected_clip_ids[0] if seg.selected_clip_ids else "?"
        budgets.append(
            SegmentTtsBudget(
                index=i,
                clip_id=cid,
                video_sec=video_sec,
                max_chars=mc,
                max_tts_sec=round(mc / CHARS_PER_SEC_TTS, 2),
            )
        )
    return budgets


async def apply_video_dub_llm_rewrite(
    *,
    plan: Plan,
    user_prompt: str,
    llm_cfg: dict[str, Any],
) -> Plan:
    """按各段画面时长预算洗稿旁白，尽量贴合原句时长。"""
    up = (user_prompt or "").strip()
    if not up:
        raise ValueError("洗稿配音需要填写配音诉求")

    active = [
        s
        for s in plan.segments
        if not s.exclude_from_output
        and s.audio_mode == "tts"
        and s.subtitle.source in ("asr", "user")
    ]
    if not active:
        return plan

    budgets = _budgets_for_segments(active)
    manifest_lines: list[str] = []
    for i, seg in enumerate(active):
        orig = (seg.subtitle.text or "").strip()[:120]
        mc = budgets[i].max_chars
        lo = max(8, int(mc * 0.82))
        manifest_lines.append(
            f"段 {i}：画面约 {budgets[i].video_sec:.1f}s，"
            f"建议字数 {lo}~{mc} 字（目标约 {int(mc * 0.92)} 字）"
            + (f"\n  原 ASR：{orig}" if orig else "")
        )
    manifest = "\n\n".join(manifest_lines)

    system = (
        "你是短视频「原片重配音」文案师。用户要保持原镜头时长与编排，只替换口播文案。\n"
        "硬性规则：\n"
        "- 每条旁白字数须在清单「建议字数」区间内，尽量靠近上限（约 85%~100%），让口播铺满画面；\n"
        "- 用户若要求写满/详细/爆款，应更接近字数上限；\n"
        "- 按用户诉求改写语气/卖点/风格，但不要改变事实主体；\n"
        "- 口语化、适合 TTS；\n"
        "- 只输出 JSON：{\"scripts\":[{\"index\":0,\"text\":\"...\"}, ...]}\n"
        f"scripts 长度必须恰好为 {len(active)}，index 从 0 连续。"
    )
    user_msg = (
        f"【用户诉求】\n{up}\n\n"
        f"【各段建议字数与原文】\n{manifest}\n\n"
        "请为每段写新旁白，朗读时长尽量贴近对应画面段时长（字数接近建议上限）。"
    )

    llm = LLMClient(
        base_url=str(llm_cfg.get("base_url") or llm_cfg["base_url"]),
        api_key=str(llm_cfg.get("api_key") or llm_cfg["api_key"]),
        model=str(llm_cfg.get("model") or llm_cfg["model"]),
        temperature=float(llm_cfg.get("temperature") or 0.65),
        max_tokens=min(int(llm_cfg.get("max_tokens") or 8192), 65536),
        timeout=3600,
    )
    raw = await llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user_msg}]
    )
    cleaned = extract_json_object(raw if isinstance(raw, str) else "")
    try:
        data = json.loads(cleaned)
    except Exception as e:
        raise RuntimeError(f"LLM 返回的文案 JSON 无法解析: {e}") from e
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, list):
        raise RuntimeError("LLM 返回格式无效：缺少 scripts 数组")

    by_index: dict[int, str] = {}
    for item in scripts:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index"))
            text = str(item.get("text") or "").strip()
        except Exception:
            continue
        if text:
            by_index[idx] = text

    texts: list[str] = []
    for i in range(len(active)):
        texts.append(by_index.get(i, (active[i].subtitle.text or "").strip()))

    clamped = clamp_script_texts_to_budgets(texts, budgets)
    ai = 0
    new_segments: list[SegmentPlan] = []
    for seg in plan.segments:
        if (
            seg.exclude_from_output
            or seg.audio_mode != "tts"
            or seg.subtitle.source not in ("asr", "user")
        ):
            new_segments.append(seg)
            continue
        text = clamped[ai] if ai < len(clamped) else (seg.subtitle.text or "")
        ai += 1
        sub = seg.subtitle.model_copy(
            update={
                "text": text,
                "strategy": "rewrite",
                "source": "llm",
            }
        )
        new_segments.append(seg.model_copy(update={"subtitle": sub}))

    return plan.model_copy(update={"segments": new_segments})


async def apply_video_dub_vlm_narration(
    *,
    plan: Plan,
    user_prompt: str,
    llm_cfg: dict[str, Any],
) -> Plan:
    """为 VLM 来源段落生成口播（无 ASR 时）。"""
    up = (user_prompt or "").strip()
    active = [
        s
        for s in plan.segments
        if not s.exclude_from_output
        and s.audio_mode == "tts"
        and (s.subtitle.source == "vlm" or s.subtitle.strategy == "auto")
    ]
    if not active:
        return plan

    budgets = _budgets_for_segments(active)
    manifest_lines: list[str] = []
    for i, seg in enumerate(active):
        hint = (seg.subtitle.text or "").strip()[:200]
        mc = budgets[i].max_chars
        lo = max(8, int(mc * 0.82))
        manifest_lines.append(
            f"段 {i}：画面约 {budgets[i].video_sec:.1f}s，"
            f"建议字数 {lo}~{mc} 字（目标约 {int(mc * 0.92)} 字）\n  画面描述：{hint}"
        )
    manifest = "\n\n".join(manifest_lines)
    prompt_block = f"【用户诉求】\n{up}\n\n" if up else ""

    system = (
        "你是短视频「画面解说配音」文案师。根据每段画面描述写连续口播，成片会保留原镜头时长。\n"
        "硬性规则：\n"
        "- 每条旁白字数须在清单「建议字数」区间内，尽量靠近上限（约 85%~100%），解说要充实；\n"
        "- 用户若要求写满/详细/爆款/加长，应更接近字数上限，可补充合理推断的细节；\n"
        "- 不要照抄画面描述原文，要改写成可朗读的口播；\n"
        "- 只输出 JSON：{\"scripts\":[{\"index\":0,\"text\":\"...\"}, ...]}\n"
        f"scripts 长度必须恰好为 {len(active)}，index 从 0 连续。"
    )
    user_msg = (
        prompt_block
        + f"【各段画面与建议字数】\n{manifest}\n\n"
        "为每段写口播，字数尽量接近建议上限，使朗读时长贴近画面段时长。"
    )

    llm = LLMClient(
        base_url=str(llm_cfg.get("base_url") or llm_cfg["base_url"]),
        api_key=str(llm_cfg.get("api_key") or llm_cfg["api_key"]),
        model=str(llm_cfg.get("model") or llm_cfg["model"]),
        temperature=float(llm_cfg.get("temperature") or 0.65),
        max_tokens=min(int(llm_cfg.get("max_tokens") or 8192), 65536),
        timeout=3600,
    )
    raw = await llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user_msg}]
    )
    cleaned = extract_json_object(raw if isinstance(raw, str) else "")
    try:
        data = json.loads(cleaned)
    except Exception as e:
        raise RuntimeError(f"LLM 返回的文案 JSON 无法解析: {e}") from e
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, list):
        raise RuntimeError("LLM 返回格式无效：缺少 scripts 数组")

    by_index: dict[int, str] = {}
    for item in scripts:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index"))
            text = str(item.get("text") or "").strip()
        except Exception:
            continue
        if text:
            by_index[idx] = text

    texts = [by_index.get(i, (active[i].subtitle.text or "").strip()) for i in range(len(active))]
    clamped = clamp_script_texts_to_budgets(texts, budgets)
    ai = 0
    new_segments: list[SegmentPlan] = []
    for seg in plan.segments:
        if seg.exclude_from_output or seg.audio_mode != "tts":
            new_segments.append(seg)
            continue
        if seg.subtitle.source != "vlm" and seg.subtitle.strategy != "auto":
            new_segments.append(seg)
            continue
        text = clamped[ai] if ai < len(clamped) else (seg.subtitle.text or "")
        ai += 1
        sub = seg.subtitle.model_copy(
            update={"text": text, "strategy": "rewrite", "source": "llm"}
        )
        new_segments.append(seg.model_copy(update={"subtitle": sub}))

    return plan.model_copy(update={"segments": new_segments})


async def load_video_dub_clips(
    db: aiosqlite.Connection,
    video_ids: list[str],
) -> list[Any]:
    rows: list[Any] = []
    for vid in video_ids:
        async with db.execute(
            "SELECT id, video_id, start_time, duration, asr_text, asr_segments, vlm_description "
            "FROM clips WHERE video_id = ? ORDER BY start_time ASC, id ASC",
            (vid,),
        ) as cur:
            rows.extend(await cur.fetchall())
    return rows
