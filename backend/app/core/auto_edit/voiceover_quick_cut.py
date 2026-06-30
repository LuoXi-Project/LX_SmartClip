"""口播快剪：基于 clips.asr_segments（句子级）生成原声 Plan。"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any, List, Sequence

import aiosqlite

from app.models.auto_edit import (
    BGMPlan,
    ClipRef,
    Plan,
    PlanKeepFlags,
    SegmentPlan,
    SubtitlePlan,
    TimingHint,
)
from app.models.subtitle import ClipTrimPart
from app.utils.bin_paths import ffmpeg_bin
from app.utils.ffprobe_utils import probe_duration
from app.utils.paths import resolve_stored_path

logger = logging.getLogger(__name__)

# 同一 clip 内判断「已占用源时间」时的容差（秒）
_VO_OVERLAP_EPS_SEC = 0.05
_STANDARD_MERGE_GAP_SEC = 0.28
_STANDARD_BUFFER_SEC = 0.06
_STANDARD_DEFAULT_KEEP_RATIO = 0.62
_STANDARD_MIN_KEEP_SEC = 12.0
_STANDARD_MAX_DELETE_RATIO = 0.72

_FILLER_WORDS = (
    "嗯",
    "啊",
    "呃",
    "额",
    "哦",
    "这个",
    "那个",
    "就是",
    "然后",
    "其实",
    "就是说",
    "对吧",
    "是不是",
    "好吧",
)
_VALUE_KEYWORDS = (
    "重点",
    "关键",
    "核心",
    "推荐",
    "建议",
    "注意",
    "总结",
    "原因",
    "问题",
    "解决",
    "效果",
    "优势",
    "缺点",
    "对比",
    "价格",
    "优惠",
    "体验",
    "功能",
    "步骤",
    "方法",
    "技巧",
)


@dataclass(frozen=True)
class _StandardSentence:
    clip_id: str
    video_id: str
    clip_base: float
    clip_dur: float
    st_rel: float
    et_rel: float
    text: str
    source_index: int

    @property
    def dur(self) -> float:
        return max(0.0, self.et_rel - self.st_rel)

    @property
    def abs_start(self) -> float:
        return self.clip_base + self.st_rel


def _clip_has_asr(asr_text: str | None) -> bool:
    return bool((asr_text or "").strip())


def _merge_ranges(ranges: list[tuple[float, float]], eps_sec: float) -> list[tuple[float, float]]:
    if not ranges:
        return []
    rows = sorted(ranges, key=lambda x: x[0])
    out: list[tuple[float, float]] = []
    cs, ce = rows[0]
    for ns, ne in rows[1:]:
        if ns <= ce + eps_sec:
            ce = max(ce, ne)
        else:
            out.append((cs, ce))
            cs, ce = ns, ne
    out.append((cs, ce))
    return out


def detect_voice_ranges_by_silencedetect(
    *,
    clip_path: str,
    clip_dur: float,
    noise_db: float,
    min_silence_sec: float,
    min_keep_sec: float,
    merge_gap_sec: float,
    head_pad_sec: float,
    tail_pad_sec: float,
) -> list[tuple[float, float]]:
    dur = max(0.0, float(clip_dur or 0.0))
    if dur <= 0:
        # 未预处理视频/元数据缺失时，尝试直接探测真实媒体时长
        dur = max(0.0, float(probe_duration(clip_path, log_on_failure=True) or 0.0))
    if dur <= 0:
        return []
    cmd = [
        ffmpeg_bin(),
        "-hide_banner",
        "-nostats",
        "-i",
        clip_path,
        "-af",
        f"silencedetect=noise={noise_db:.2f}dB:d={max(0.05, float(min_silence_sec)):.3f}",
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
    if result.returncode != 0:
        logger.warning("silencedetect 失败，回退整段 clip: %s", clip_path)
        return [(0.0, dur)] if dur >= min_keep_sec else []

    stderr_txt = result.stderr.decode(errors="replace")
    st_re = re.compile(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)")
    ed_re = re.compile(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)")

    silences: list[tuple[float, float]] = []
    cur_sil_start: float | None = None
    for ln in stderr_txt.splitlines():
        m1 = st_re.search(ln)
        if m1:
            cur_sil_start = max(0.0, min(dur, float(m1.group(1))))
            continue
        m2 = ed_re.search(ln)
        if m2:
            end_t = max(0.0, min(dur, float(m2.group(1))))
            start_t = 0.0 if cur_sil_start is None else cur_sil_start
            if end_t > start_t:
                silences.append((start_t, end_t))
            cur_sil_start = None
    if cur_sil_start is not None and dur > cur_sil_start:
        silences.append((cur_sil_start, dur))

    silences = _merge_ranges(silences, 0.02)
    voices: list[tuple[float, float]] = []
    cursor = 0.0
    for ss, se in silences:
        if ss > cursor:
            voices.append((cursor, ss))
        cursor = max(cursor, se)
    if cursor < dur:
        voices.append((cursor, dur))

    padded: list[tuple[float, float]] = []
    for st, et in voices:
        pst = max(0.0, st - max(0.0, head_pad_sec))
        pet = min(dur, et + max(0.0, tail_pad_sec))
        if pet - pst >= max(0.1, min_keep_sec):
            padded.append((pst, pet))

    merged = _merge_ranges(padded, max(0.0, merge_gap_sec))
    return [(st, et) for st, et in merged if et - st >= max(0.1, min_keep_sec)]


def _parse_asr_segments(asr_segments_json: str | None) -> list[dict[str, Any]]:
    if not asr_segments_json:
        return []
    try:
        data = json.loads(asr_segments_json)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        # 允许 whisper/openai 结果里字段名稍有差异，但本项目约定为 start/end/text
        out.append(item)
    return out


def _merge_contiguous_asr_rows(
    rows: list[tuple[float, float, str]],
    eps_sec: float = 0.08,
) -> list[tuple[float, float, str]]:
    """
    同一 clip 内、按时间排序的句子行：若相邻行首尾相接（允许微小间隙/浮点误差），
    合并为一条，成片时只做一次 -ss/-t。
    """
    if not rows:
        return []
    out: list[tuple[float, float, str]] = []
    cs, ce, ct = rows[0]
    for ns, ne, nt in rows[1:]:
        gap = ns - ce
        if -0.05 <= gap <= eps_sec:
            t1 = ct.strip()
            t2 = nt.strip()
            ct = "\n".join(x for x in (t1, t2) if x)
            ce = max(ce, ne)
        else:
            out.append((cs, ce, ct))
            cs, ce, ct = ns, ne, nt
    out.append((cs, ce, ct))
    return out


def _is_meaningful_text(text: str | None) -> bool:
    if not text:
        return False
    t = str(text).strip()
    if not t:
        return False
    if t in ("…", "……", "..."):
        return False

    # 过滤“全是标点/符号”的单位，保留至少一个字母/数字/CJK 字
    meaningful = "".join(
        ch
        for ch in t
        if ch.isalnum() or ("\u4e00" <= ch <= "\u9fff")
    )
    return bool(meaningful)


def _compact_for_scoring(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?；;：:\-—]+", "", text or "")


def _standard_sentence_score(sentence: _StandardSentence, *, first_in_video: bool) -> float:
    text = (sentence.text or "").strip()
    compact = _compact_for_scoring(text)
    if not compact:
        return -100.0

    dur = sentence.dur
    length = len(compact)
    score = 0.0

    # 信息密度：太短多为口癖，过长容易拖节奏。
    score += min(18.0, length * 0.58)
    if 8 <= length <= 42:
        score += 3.0
    elif length < 4:
        score -= 8.0
    elif length > 70:
        score -= min(8.0, (length - 70) * 0.12)

    # 语速/密度：口播短视频更偏向信息密集片段。
    density = length / max(0.3, dur)
    if density >= 2.2:
        score += min(8.0, (density - 2.2) * 1.4)
    elif density < 0.9:
        score -= 3.0

    for word in _VALUE_KEYWORDS:
        if word in text:
            score += 3.2
    filler_hits = sum(1 for word in _FILLER_WORDS if word in text)
    score -= filler_hits * 2.1

    # 全句几乎都是口癖时直接重罚。
    stripped = compact
    for word in _FILLER_WORDS:
        stripped = stripped.replace(word, "")
    if len(stripped) <= 2 and filler_hits:
        score -= 20.0

    if text[-1:] in "。！？!?":
        score += 1.0
    if first_in_video and dur <= 8.0:
        score += 2.0

    if dur < 0.35:
        score -= 10.0
    elif dur > 18.0:
        score -= min(10.0, (dur - 18.0) * 0.5)

    return score


def _collect_standard_sentences(
    clip_groups: Sequence[Sequence[aiosqlite.Row | dict[str, Any]]],
) -> list[_StandardSentence]:
    sentences: list[_StandardSentence] = []
    source_index = 0
    for rows in clip_groups:
        for row in rows:
            cid = str(row["id"])
            vid = str(row["video_id"])
            clip_base = float(row["start_time"] or 0.0)
            clip_dur = float(row["duration"] or 0.0)
            seg_items = _parse_asr_segments(row["asr_segments"])

            if not seg_items:
                if not _clip_has_asr(row["asr_text"]):
                    continue
                text = (row["asr_text"] or "").strip()
                if not _is_meaningful_text(text):
                    continue
                et_rel = clip_dur if clip_dur > 0 else 1.0
                sentences.append(
                    _StandardSentence(
                        clip_id=cid,
                        video_id=vid,
                        clip_base=clip_base,
                        clip_dur=clip_dur,
                        st_rel=0.0,
                        et_rel=et_rel,
                        text=text,
                        source_index=source_index,
                    )
                )
                source_index += 1
                continue

            raw_rows: list[tuple[float, float, str]] = []
            for seg in seg_items:
                try:
                    st_rel = float(seg.get("start") or 0.0)
                    et_rel = float(seg.get("end") or st_rel)
                except Exception:
                    continue
                if et_rel <= st_rel:
                    continue
                text = str(seg.get("text") or "").strip()
                if not _is_meaningful_text(text):
                    continue
                raw_rows.append((st_rel, et_rel, text))

            raw_rows.sort(key=lambda r: r[0])
            for st_rel, et_rel, text in _merge_contiguous_asr_rows(raw_rows):
                if et_rel <= st_rel:
                    continue
                sentences.append(
                    _StandardSentence(
                        clip_id=cid,
                        video_id=vid,
                        clip_base=clip_base,
                        clip_dur=clip_dur,
                        st_rel=st_rel,
                        et_rel=et_rel,
                        text=text,
                        source_index=source_index,
                    )
                )
                source_index += 1
    return sentences


def _select_standard_sentences(
    sentences: list[_StandardSentence],
    *,
    target_duration_sec: float | None,
) -> tuple[list[_StandardSentence], dict[str, float]]:
    if not sentences:
        return [], {"total_speech_sec": 0.0, "target_sec": 0.0, "kept_speech_sec": 0.0}

    total = sum(s.dur for s in sentences)
    if target_duration_sec and target_duration_sec > 0:
        target = min(float(target_duration_sec), total)
    else:
        target = max(_STANDARD_MIN_KEEP_SEC, total * _STANDARD_DEFAULT_KEEP_RATIO)
    min_allowed = max(0.0, total * (1.0 - _STANDARD_MAX_DELETE_RATIO))
    target = max(min_allowed, min(target, total))

    seen_video: set[str] = set()
    scored: list[tuple[float, _StandardSentence]] = []
    for s in sentences:
        first_in_video = s.video_id not in seen_video
        seen_video.add(s.video_id)
        scored.append((_standard_sentence_score(s, first_in_video=first_in_video), s))

    scored.sort(key=lambda x: (x[0], x[1].dur), reverse=True)

    chosen: list[_StandardSentence] = []
    chosen_ids: set[int] = set()
    cur = 0.0
    for score, s in scored:
        if score < -2.0 and cur >= min_allowed:
            continue
        chosen.append(s)
        chosen_ids.add(id(s))
        cur += s.dur
        if cur >= target:
            break

    # 连贯性保护：入选句的前后短句如果间隔很小，自动补入，避免切得像断崖。
    by_clip: dict[str, list[_StandardSentence]] = {}
    for s in sentences:
        by_clip.setdefault(s.clip_id, []).append(s)
    for rows in by_clip.values():
        rows.sort(key=lambda x: x.st_rel)
        for i, s in enumerate(rows):
            if id(s) not in chosen_ids:
                continue
            for neighbor in (rows[i - 1] if i > 0 else None, rows[i + 1] if i + 1 < len(rows) else None):
                if neighbor is None or id(neighbor) in chosen_ids:
                    continue
                gap = min(abs(neighbor.et_rel - s.st_rel), abs(neighbor.st_rel - s.et_rel))
                if gap <= 0.18 and neighbor.dur <= 2.5:
                    chosen.append(neighbor)
                    chosen_ids.add(id(neighbor))
                    cur += neighbor.dur

    chosen.sort(key=lambda s: (s.source_index, s.abs_start))
    return chosen, {
        "total_speech_sec": round(total, 3),
        "target_sec": round(target, 3),
        "kept_speech_sec": round(sum(s.dur for s in chosen), 3),
    }


def _merge_standard_sentences_to_segments(sentences: list[_StandardSentence]) -> list[tuple[_StandardSentence, ...]]:
    if not sentences:
        return []
    ordered = sorted(sentences, key=lambda s: (s.source_index, s.abs_start))
    groups: list[list[_StandardSentence]] = []
    cur = [ordered[0]]
    for s in ordered[1:]:
        prev = cur[-1]
        same_clip = prev.clip_id == s.clip_id
        gap = s.st_rel - prev.et_rel
        if same_clip and gap <= _STANDARD_MERGE_GAP_SEC:
            cur.append(s)
        else:
            groups.append(cur)
            cur = [s]
    groups.append(cur)
    return [tuple(g) for g in groups]


def _build_standard_plan(
    *,
    clip_groups: Sequence[Sequence[aiosqlite.Row | dict[str, Any]]],
    video_title_hint: str | None,
    target_duration_sec: float | None,
    head_pad_sec: float = 0.0,
    tail_pad_sec: float = 0.0,
) -> Plan:
    # 句头/句尾补偿：用户显式设置 pad 时以 pad 为准；未设置时沿用历史默认 buffer（0.06s）保留原行为。
    effective_head = max(float(head_pad_sec or 0.0), _STANDARD_BUFFER_SEC)
    effective_tail = max(float(tail_pad_sec or 0.0), _STANDARD_BUFFER_SEC)
    sentences = _collect_standard_sentences(clip_groups)
    selected, stats = _select_standard_sentences(sentences, target_duration_sec=target_duration_sec)
    groups = _merge_standard_sentences_to_segments(selected)

    segments: list[SegmentPlan] = []
    total_sec = 0.0
    for order, group in enumerate(groups):
        first = group[0]
        last = group[-1]
        clip_dur = first.clip_dur
        st_rel = max(0.0, first.st_rel - effective_head)
        et_rel = min(clip_dur if clip_dur > 0 else last.et_rel, last.et_rel + effective_tail)
        if et_rel <= st_rel:
            et_rel = last.et_rel
        dur = max(0.0, et_rel - st_rel)
        if dur <= 0:
            continue
        text = "\n".join(s.text.strip() for s in group if s.text.strip())
        st_abs = first.clip_base + st_rel
        et_abs = first.clip_base + et_rel
        total_sec += dur
        segments.append(
            SegmentPlan(
                id=f"vq_{order:04d}_{first.clip_id[:6]}_std",
                order=order,
                clip_group=[ClipRef(clip_id=first.clip_id, video_id=first.video_id, weight=1.0)],
                selected_clip_ids=[first.clip_id],
                start_time_sec=st_abs,
                end_time_sec=et_abs,
                override_duration_sec=dur,
                clip_start_offset_sec=st_rel,
                audio_mode="original",
                subtitle=SubtitlePlan(
                    strategy="asr",
                    text=text,
                    source="asr",
                    timing_hint=TimingHint(start=st_abs, end=et_abs),
                ),
            )
        )

    vt = (video_title_hint or "").strip()
    title = f"口播快剪（标准）· {vt}" if vt else "口播快剪（标准）"
    summary = (
        "基于 ASR 句子质量评分的标准快剪："
        f"保留 {len(selected)}/{len(sentences)} 条句子；"
        f"语音保留约 {stats['kept_speech_sec']:.1f}/{stats['total_speech_sec']:.1f}s；"
        f"成片约 {total_sec:.1f}s。"
    )
    return Plan(
        plan_id=uuid.uuid4().hex[:8],
        title=title,
        summary=summary,
        video_title=vt or None,
        video_description=None,
        mode="original",
        target_duration_sec=target_duration_sec,
        estimated_duration_sec=round(total_sec, 2) if total_sec > 0 else None,
        chapters=[
            {
                "id": "standard_quality_score",
                "title": "标准快剪评分",
                "input_sentence_count": len(sentences),
                "kept_sentence_count": len(selected),
                "total_speech_sec": stats["total_speech_sec"],
                "target_sec": stats["target_sec"],
                "kept_speech_sec": stats["kept_speech_sec"],
            }
        ],
        segments=segments,
        bgm=BGMPlan(enabled=False),
        constraints=None,
        keep_flags=PlanKeepFlags(clips=False, subtitles=False, transitions=False, bgm=False),
    )


def _sum_segment_output_duration(segments: Sequence[SegmentPlan]) -> float:
    total = 0.0
    for s in segments:
        od = s.override_duration_sec
        if od is not None and od > 0:
            total += float(od)
        else:
            total += max(0.0, float(s.end_time_sec) - float(s.start_time_sec))
    return total


def _dedupe_overlaps_on_video_source_timeline(segments: List[SegmentPlan]) -> List[SegmentPlan]:
    """
    按成片顺序处理：同一 video_id（同一底层素材文件时间轴）下，若当前段 start 早于已占用源时间末尾，
    则向右裁切起点（并同步 clip_start_offset / override_duration / 字幕 timing），避免跨 clip 重复播同一段。
    裁切后有效时长过小则丢弃该段。
    """
    if not segments:
        return []
    sorted_segs = sorted(segments, key=lambda s: s.order)
    last_src_end: dict[str, float] = {}
    out: List[SegmentPlan] = []
    for s in sorted_segs:
        if not s.clip_group:
            out.append(s)
            continue
        ref = s.clip_group[0]
        key = str(ref.video_id)
        st = float(s.start_time_sec)
        et = float(s.end_time_sec)
        if et <= st + _VO_OVERLAP_EPS_SEC:
            continue
        prev_end = last_src_end.get(key, float("-inf"))
        if st + _VO_OVERLAP_EPS_SEC < prev_end:
            new_st = prev_end
            delta = new_st - st
            new_et = et
            if new_et <= new_st + _VO_OVERLAP_EPS_SEC:
                continue
            off = float(s.clip_start_offset_sec or 0.0) + delta
            new_dur = new_et - new_st
            th = s.subtitle.timing_hint
            new_sub = s.subtitle.model_copy(
                update={
                    "timing_hint": (
                        TimingHint(start=new_st, end=new_et)
                        if th is not None
                        else None
                    )
                }
            )
            s = s.model_copy(
                update={
                    "start_time_sec": new_st,
                    "end_time_sec": new_et,
                    "clip_start_offset_sec": off,
                    "override_duration_sec": new_dur,
                    "subtitle": new_sub,
                }
            )
            st, et = new_st, new_et
        last_src_end[key] = max(prev_end, et)
        out.append(s)
    for i, seg in enumerate(out):
        if seg.order != i:
            out[i] = seg.model_copy(update={"order": i})
    return out


def _round_src_t(t: float) -> float:
    return round(float(t), 3)


def _build_merged_voiceover_segment(*, order: int, parts: List[SegmentPlan]) -> SegmentPlan:
    """将同一 video、时间轴上相接/重叠的多段合并为一条 Plan（跨 clip 用 clip_trims）。"""
    assert len(parts) >= 2 and all(p.clip_group for p in parts)
    ref0 = parts[0].clip_group[0]
    vid = str(ref0.video_id)
    cid0 = str(ref0.clip_id)

    text_lines: List[str] = []
    for p in parts:
        tx = (p.subtitle.text or "").strip() if p.subtitle else ""
        if tx:
            text_lines.append(tx)
    merged_text = "\n".join(text_lines) if text_lines else "（间隙/环境声）"

    st_abs = _round_src_t(min(float(p.start_time_sec) for p in parts))
    et_abs = _round_src_t(max(float(p.end_time_sec) for p in parts))
    timing = TimingHint(start=st_abs, end=et_abs)

    cids = {str(p.clip_group[0].clip_id) for p in parts}
    all_same_clip = len(cids) == 1
    if all_same_clip:
        bases = [
            float(p.start_time_sec) - float(p.clip_start_offset_sec or 0.0) for p in parts
        ]
        if max(bases) - min(bases) > 0.02:
            all_same_clip = False
        else:
            base = bases[0]
            st_rel = min(float(p.start_time_sec) - base for p in parts)
            et_rel = max(float(p.end_time_sec) - base for p in parts)
            dur = max(0.0, _round_src_t(et_rel - st_rel))
            return SegmentPlan(
                id=f"vq_{order:04d}_{cid0[:6]}_mg",
                order=order,
                clip_group=[ClipRef(clip_id=cid0, video_id=vid, weight=1.0)],
                selected_clip_ids=[cid0],
                start_time_sec=_round_src_t(base + st_rel),
                end_time_sec=_round_src_t(base + et_rel),
                override_duration_sec=dur,
                clip_start_offset_sec=_round_src_t(st_rel),
                clip_trims=None,
                audio_mode=parts[0].audio_mode,
                subtitle=SubtitlePlan(
                    strategy=parts[0].subtitle.strategy if parts[0].subtitle else "asr",
                    text=merged_text,
                    source=parts[0].subtitle.source if parts[0].subtitle else "asr",
                    timing_hint=timing,
                ),
                transition=parts[-1].transition,
            )

    trims: List[ClipTrimPart] = []
    clip_group: List[ClipRef] = []
    selected: List[str] = []
    for p in parts:
        ref = p.clip_group[0]
        cid = str(ref.clip_id)
        cs = float(p.clip_start_offset_sec or 0.0)
        span = float(
            p.override_duration_sec
            if p.override_duration_sec is not None
            else max(0.0, float(p.end_time_sec) - float(p.start_time_sec))
        )
        span = _round_src_t(span)
        if span <= _VO_OVERLAP_EPS_SEC:
            continue
        trims.append(
            ClipTrimPart(
                clip_id=cid,
                clip_start_sec=_round_src_t(cs),
                duration_sec=span,
            )
        )
        clip_group.append(
            ClipRef(clip_id=cid, video_id=str(ref.video_id), weight=float(ref.weight or 1.0))
        )
        selected.append(cid)
    if not trims:
        return parts[0].model_copy(update={"order": order, "id": f"vq_{order:04d}_mgfb"})

    total_dur = _round_src_t(sum(float(t.duration_sec) for t in trims))
    return SegmentPlan(
        id=f"vq_{order:04d}_mg",
        order=order,
        clip_group=clip_group,
        selected_clip_ids=selected,
        start_time_sec=st_abs,
        end_time_sec=et_abs,
        override_duration_sec=total_dur,
        clip_start_offset_sec=_round_src_t(float(parts[0].clip_start_offset_sec or 0.0)),
        clip_trims=trims,
        audio_mode=parts[0].audio_mode,
        subtitle=SubtitlePlan(
            strategy=parts[0].subtitle.strategy if parts[0].subtitle else "asr",
            text=merged_text,
            source=parts[0].subtitle.source if parts[0].subtitle else "asr",
            timing_hint=timing,
        ),
        transition=parts[-1].transition,
    )


def _merge_touching_same_video_segments(segments: List[SegmentPlan]) -> List[SegmentPlan]:
    """
    成片顺序下：同一 video_id 且源时间轴相接（含去重后的紧挨）的连续段合并为一条，
    避免响应里出现多段「看起来还叠在一起」。
    """
    if len(segments) <= 1:
        return segments
    sorted_segs = sorted(segments, key=lambda s: s.order)
    out: List[SegmentPlan] = []
    i = 0
    while i < len(sorted_segs):
        cur = sorted_segs[i]
        if not cur.clip_group:
            out.append(cur)
            i += 1
            continue
        group: List[SegmentPlan] = [cur]
        j = i + 1
        vid0 = str(cur.clip_group[0].video_id)
        while j < len(sorted_segs):
            nxt = sorted_segs[j]
            if not nxt.clip_group:
                break
            if str(nxt.clip_group[0].video_id) != vid0:
                break
            prev = group[-1]
            if float(nxt.start_time_sec) > float(prev.end_time_sec) + _VO_OVERLAP_EPS_SEC:
                break
            group.append(nxt)
            j += 1
        if len(group) == 1:
            out.append(cur)
        else:
            out.append(_build_merged_voiceover_segment(order=len(out), parts=group))
        i = j
    for k, seg in enumerate(out):
        if seg.order != k:
            out[k] = seg.model_copy(update={"order": k})
    return out


def apply_voiceover_source_timeline_dedupe(plan: Plan, *, allow_overlaps: bool) -> Plan:
    """口播快剪：同一 video 源时间去重后，将相接段合并为单条 Plan（除非允许重叠）。"""
    if allow_overlaps:
        return plan
    new_segments = _dedupe_overlaps_on_video_source_timeline(list(plan.segments))
    new_segments = _merge_touching_same_video_segments(new_segments)
    total = _sum_segment_output_duration(new_segments)
    return plan.model_copy(
        update={
            "segments": new_segments,
            "estimated_duration_sec": round(total, 2) if total > 0 else None,
        }
    )


async def load_clip_groups_by_videos(
    db: aiosqlite.Connection,
    video_ids: List[str],
    *,
    include_raw_video_fallback: bool = False,
) -> List[List[aiosqlite.Row | dict[str, Any]]]:
    groups: List[List[aiosqlite.Row | dict[str, Any]]] = []
    for vid in video_ids:
        async with db.execute(
            "SELECT id, video_id, clip_path, start_time, duration, asr_text, asr_segments "
            "FROM clips WHERE video_id = ? ORDER BY start_time ASC, id ASC",
            (vid,),
        ) as cur:
            rows = await cur.fetchall()
        clip_rows = list(rows)
        if clip_rows or not include_raw_video_fallback:
            groups.append(clip_rows)
            continue

        # 音频粗剪兼容：未做预处理（无 clips）时，回退为“原视频单段 clip”参与静音检测。
        async with db.execute(
            "SELECT id, file_path, duration FROM videos WHERE id = ?",
            (vid,),
        ) as cur:
            vrow = await cur.fetchone()
        if not vrow:
            groups.append([])
            continue
        groups.append(
            [
                {
                    "id": f"raw_{vid}",
                    "video_id": str(vrow["id"]),
                    "clip_path": str(vrow["file_path"] or ""),
                    "start_time": 0.0,
                    "duration": float(vrow["duration"] or 0.0),
                    "asr_text": None,
                    "asr_segments": None,
                }
            ]
        )
    return groups


def build_plan_from_clip_groups(
    *,
    clip_groups: Sequence[Sequence[aiosqlite.Row]],
    strategy: str,
    video_title_hint: str | None,
    audio_activity_cfg: dict[str, float] | None = None,
    target_duration_sec: float | None = None,
    head_pad_sec: float = 0.0,
    tail_pad_sec: float = 0.0,
) -> Plan:
    if strategy not in ("asr_fast", "standard", "audio_activity_fast"):
        raise ValueError(f"unsupported strategy: {strategy}")

    if strategy == "standard":
        return _build_standard_plan(
            clip_groups=clip_groups,
            video_title_hint=video_title_hint,
            target_duration_sec=target_duration_sec,
            head_pad_sec=head_pad_sec,
            tail_pad_sec=tail_pad_sec,
        )

    if strategy == "asr_fast":
        label = "极速"
    else:
        label = "音频活动"

    aa_cfg = audio_activity_cfg or {}
    aa_noise_db = float(aa_cfg.get("db_threshold", -36.0))
    aa_min_sil = float(aa_cfg.get("min_silence_sec", 0.25))
    aa_min_keep = float(aa_cfg.get("min_keep_sec", 0.35))
    aa_merge_gap = float(aa_cfg.get("merge_gap_sec", 0.2))
    aa_head_pad = float(aa_cfg.get("head_pad_sec", 0.08))
    aa_tail_pad = float(aa_cfg.get("tail_pad_sec", 0.12))
    # keep_ranges: 前端预计算的“绝对保留区间”。注意：空数组 [] 也代表“用户明确要保留 0 段”，不能回退静音检测。
    keep_ranges = aa_cfg.get("keep_ranges", None)

    segments: List[SegmentPlan] = []
    total_sec = 0.0
    order = 0

    for rows in clip_groups:
        for row in rows:
            cid = str(row["id"])
            vid = str(row["video_id"])

            clip_base = float(row["start_time"] or 0.0)
            clip_dur = float(row["duration"] or 0.0)
            asr_segments_json = row["asr_segments"]
            seg_items = _parse_asr_segments(asr_segments_json)
            clip_path = resolve_stored_path(str(row["clip_path"] or ""))
            if clip_dur <= 0:
                clip_dur = max(0.0, float(probe_duration(clip_path, log_on_failure=True) or 0.0))

            if strategy == "audio_activity_fast":
                # 前端若提供了“绝对保留区间”，则直接按区间与 clip 求交生成 segments（无需后端再做静音检测）
                if keep_ranges is not None:
                    try:
                        kr = [
                            r
                            for r in keep_ranges
                            if isinstance(r, dict)
                            and str(r.get("video_id") or "") == vid
                        ]
                    except Exception:
                        kr = []
                    if not kr:
                        # 没有命中本 video_id 的保留区间：严格按 keep_ranges 输出为空（不回退静音检测）
                        continue

                    clip_abs_st = clip_base
                    clip_abs_et = clip_base + max(0.0, clip_dur)
                    for idx2, r in enumerate(kr):
                        try:
                            rs = float(r.get("start") or 0.0)
                            re2 = float(r.get("end") or rs)
                        except Exception:
                            continue
                        if re2 <= rs:
                            continue
                        st_abs2 = max(clip_abs_st, rs)
                        et_abs2 = min(clip_abs_et, re2)
                        if et_abs2 <= st_abs2:
                            continue
                        st_rel2 = max(0.0, st_abs2 - clip_base)
                        et_rel2 = max(st_rel2, et_abs2 - clip_base)
                        dur2 = et_rel2 - st_rel2
                        if dur2 < aa_min_keep:
                            continue
                        total_sec += dur2
                        segments.append(
                            SegmentPlan(
                                id=f"vq_{order:04d}_{cid[:6]}_p{idx2:03d}",
                                order=order,
                                clip_group=[ClipRef(clip_id=cid, video_id=vid, weight=1.0)],
                                selected_clip_ids=[cid],
                                start_time_sec=clip_base + st_rel2,
                                end_time_sec=clip_base + et_rel2,
                                override_duration_sec=dur2,
                                clip_start_offset_sec=st_rel2,
                                audio_mode="original",
                                subtitle=SubtitlePlan(
                                    strategy="none",
                                    text="（音高/活动保留片段）",
                                    source="asr",
                                    timing_hint=TimingHint(start=clip_base + st_rel2, end=clip_base + et_rel2),
                                ),
                            )
                        )
                        order += 1
                    continue
                detected = detect_voice_ranges_by_silencedetect(
                    clip_path=clip_path,
                    clip_dur=clip_dur,
                    noise_db=aa_noise_db,
                    min_silence_sec=aa_min_sil,
                    min_keep_sec=aa_min_keep,
                    merge_gap_sec=aa_merge_gap,
                    head_pad_sec=aa_head_pad,
                    tail_pad_sec=aa_tail_pad,
                )
                for idx, (st_rel, et_rel) in enumerate(detected):
                    dur = et_rel - st_rel
                    if dur <= 0:
                        continue
                    total_sec += dur
                    st_abs = clip_base + st_rel
                    et_abs = clip_base + et_rel
                    segments.append(
                        SegmentPlan(
                            id=f"vq_{order:04d}_{cid[:6]}_a{idx:03d}",
                            order=order,
                            clip_group=[ClipRef(clip_id=cid, video_id=vid, weight=1.0)],
                            selected_clip_ids=[cid],
                            start_time_sec=st_abs,
                            end_time_sec=et_abs,
                            override_duration_sec=dur,
                            clip_start_offset_sec=st_rel,
                            audio_mode="original",
                            subtitle=SubtitlePlan(
                                strategy="none",
                                text="（语音活动片段）",
                                source="asr",
                                timing_hint=TimingHint(start=st_abs, end=et_abs),
                            ),
                        )
                    )
                    order += 1
                continue

            # 回退：没有 segments，就按整段 clip（仍可通过 override_duration_sec=clip_dur 移除尾部静音，若 clips.duration 已裁剪对齐）
            if not seg_items:
                if not _clip_has_asr(row["asr_text"]):
                    continue
                st_rel = 0.0
                et_rel = clip_dur if clip_dur > 0 else st_rel + 1.0
                text = (row["asr_text"] or "").strip() or "（间隙/环境声）"
                dur = max(0.0, et_rel - st_rel)
                if dur <= 0:
                    continue
                total_sec += dur
                segments.append(
                    SegmentPlan(
                        id=f"vq_{order:04d}_{cid[:8]}",
                        order=order,
                        clip_group=[ClipRef(clip_id=cid, video_id=vid, weight=1.0)],
                        selected_clip_ids=[cid],
                        start_time_sec=clip_base + st_rel,
                        end_time_sec=clip_base + et_rel,
                        override_duration_sec=dur,
                        clip_start_offset_sec=st_rel,
                        audio_mode="original",
                        subtitle=SubtitlePlan(
                            strategy="asr",
                            text=text,
                            source="asr",
                            timing_hint=TimingHint(
                                start=clip_base + st_rel, end=clip_base + et_rel
                            ),
                        ),
                    )
                )
                order += 1
                continue

            raw_rows: list[tuple[float, float, str]] = []
            for seg in seg_items:
                try:
                    st_rel = float(seg.get("start") or 0.0)
                    et_rel = float(seg.get("end") or st_rel)
                except Exception:
                    continue
                if et_rel <= st_rel:
                    continue
                text = str(seg.get("text") or "").strip()
                if not _is_meaningful_text(text):
                    continue
                dur = et_rel - st_rel
                if dur <= 0:
                    continue
                raw_rows.append((st_rel, et_rel, text))

            raw_rows.sort(key=lambda r: r[0])
            for idx, (st_rel, et_rel, text) in enumerate(_merge_contiguous_asr_rows(raw_rows)):
                # 句头/句尾补偿：保留说话间隙，避免吃掉首字/尾音；约束在 clip 内（不越界）。
                pad_st = max(0.0, st_rel - max(0.0, head_pad_sec))
                pad_et = min(clip_dur if clip_dur > 0 else et_rel, et_rel + max(0.0, tail_pad_sec))
                if pad_et <= pad_st:
                    pad_et = et_rel
                dur = pad_et - pad_st
                if dur <= 0:
                    continue
                total_sec += dur

                st_abs = clip_base + pad_st
                et_abs = clip_base + pad_et
                segments.append(
                    SegmentPlan(
                        id=f"vq_{order:04d}_{cid[:6]}_{idx:03d}",
                        order=order,
                        clip_group=[ClipRef(clip_id=cid, video_id=vid, weight=1.0)],
                        selected_clip_ids=[cid],
                        # start/end 使用“绝对时间”，便于前端展示/预览；裁剪偏移用 clip_start_offset_sec 表示 clip 内起点
                        start_time_sec=st_abs,
                        end_time_sec=et_abs,
                        override_duration_sec=dur,
                        clip_start_offset_sec=pad_st,
                        audio_mode="original",
                        subtitle=SubtitlePlan(
                            strategy="asr",
                            text=text,
                            source="asr",
                            timing_hint=TimingHint(start=st_abs, end=et_abs),
                        ),
                    )
                )
                order += 1

    vt = (video_title_hint or "").strip()
    title = f"口播快剪（{label}）· {vt}" if vt else f"口播快剪（{label}）"
    if strategy == "audio_activity_fast":
        summary = (
            f"基于原音频活动检测（静音互补）粗剪：共 {len(segments)} 段，"
            f"预估总时长约 {total_sec:.1f}s（支持阈值/补偿参数微调）。"
        )
    else:
        summary = (
            f"基于 ASR 句子级 segments 的{label}快剪：共 {len(segments)} 段，"
            f"预估总时长约 {total_sec:.1f}s（按句子区间 -ss/-t 精确裁剪）。"
        )

    return Plan(
        plan_id=uuid.uuid4().hex[:8],
        title=title,
        summary=summary,
        video_title=vt or None,
        video_description=None,
        mode="original",
        target_duration_sec=None,
        estimated_duration_sec=round(total_sec, 2) if total_sec > 0 else None,
        segments=segments,
        bgm=BGMPlan(enabled=False),
        constraints=None,
        keep_flags=PlanKeepFlags(
            clips=False, subtitles=False, transitions=False, bgm=False
        ),
    )
