"""口播智能快剪：基于 ASR 句子 + LLM 分块筛选，含保护策略与上下文分片。"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Set

import aiosqlite

from app.core.llm import LLMClient
from app.core.llm.response_utils import extract_json_object, is_llm_unauthorized_error
from app.core.auto_edit.voiceover_quick_cut import (
    _clip_has_asr,
    _is_meaningful_text,
    _merge_contiguous_asr_rows,
    _parse_asr_segments,
)
from app.models.auto_edit import (
    BGMPlan,
    ClipRef,
    Plan,
    PlanKeepFlags,
    SegmentPlan,
    SubtitlePlan,
    TimingHint,
)

logger = logging.getLogger(__name__)

# 分块：按 token 上下文预算切批，避免上下文溢出
MIN_UNITS_PER_CHUNK = 6
MERGE_GAP_SEC = 0.25
BUFFER_SEC = 0.08

# 兼容旧实现的字符级退化切批（当 token 预算异常时使用）
MAX_CHUNK_BODY_CHARS = 9000

# token 估算：粗略按 1 token ≈ 4 个字符（中文为主时可适当偏大/偏小，这里用于“切批预算”，不要求极准）
TOKENS_PER_CHAR = 1 / 4
LLM_INPUT_SAFETY_TOKENS = 400
LLM_OUTPUT_RESERVE_TOKENS_CAP = 2048

DEFAULT_LLM_CONTEXT_TOKENS = 128000

_FILLER = ("嗯", "啊", "呃", "哦", "哎", "就是", "然后", "那个", "这个", "对吧", "好吧")
_KEYWORDS = (
    "推荐", "好用", "问题", "效果", "优惠", "价格", "重点", "注意", "总结", "建议",
    "产品", "功能", "体验", "对比", "优势", "缺点",
)


@dataclass(frozen=True)
class SentenceUnit:
    sid: str
    video_id: str
    clip_id: str
    clip_base: float
    clip_dur: float
    st_rel: float
    et_rel: float
    text: str

    @property
    def dur(self) -> float:
        return max(0.0, self.et_rel - self.st_rel)

    @property
    def abs_start(self) -> float:
        return self.clip_base + self.st_rel


def _heuristic_score(text: str) -> float:
    t = (text or "").strip()
    if not t:
        return 0.0
    score = min(18.0, len(t) * 0.12)
    for w in _KEYWORDS:
        if w in t:
            score += 2.5
    for w in _FILLER:
        if w in t:
            score -= 1.2
    if t[-1:] in "。！？；":
        score += 1.0
    return score


def flatten_sentence_units(clip_groups: Sequence[Sequence[aiosqlite.Row]]) -> List[SentenceUnit]:
    """与极速快剪相同的句子切分规则，产出带稳定 sid 的句子单元。"""
    units: List[SentenceUnit] = []
    n = 0
    for rows in clip_groups:
        for row in rows:
            cid = str(row["id"])
            vid = str(row["video_id"])
            clip_base = float(row["start_time"] or 0.0)
            clip_dur = float(row["duration"] or 0.0)
            asr_segments_json = row["asr_segments"]
            seg_items = _parse_asr_segments(asr_segments_json)

            if not seg_items:
                if not _clip_has_asr(row["asr_text"]):
                    continue
                st_rel = 0.0
                et_rel = clip_dur if clip_dur > 0 else st_rel + 1.0
                text = (row["asr_text"] or "").strip() or "（间隙/环境声）"
                sid = f"s_{n:06d}"
                n += 1
                units.append(
                    SentenceUnit(
                        sid=sid,
                        video_id=vid,
                        clip_id=cid,
                        clip_base=clip_base,
                        clip_dur=clip_dur,
                        st_rel=st_rel,
                        et_rel=et_rel,
                        text=text,
                    )
                )
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
                sid = f"s_{n:06d}"
                n += 1
                units.append(
                    SentenceUnit(
                        sid=sid,
                        video_id=vid,
                        clip_id=cid,
                        clip_base=clip_base,
                        clip_dur=clip_dur,
                        st_rel=st_rel,
                        et_rel=et_rel,
                        text=text,
                    )
                )
    return units


def chunk_units_by_budget(units: List[SentenceUnit]) -> List[List[SentenceUnit]]:
    if not units:
        return []
    chunks: List[List[SentenceUnit]] = []
    cur: List[SentenceUnit] = []
    cur_len = 0
    for u in units:
        line = f"{u.sid}\t{u.abs_start:.2f}\t{u.abs_start + u.dur:.2f}\t{u.text}\n"
        if (
            cur
            and cur_len + len(line) > MAX_CHUNK_BODY_CHARS
            and len(cur) >= MIN_UNITS_PER_CHUNK
        ):
            chunks.append(cur)
            cur = []
            cur_len = 0
        cur.append(u)
        cur_len += len(line)
    if cur:
        chunks.append(cur)
    return chunks


def _estimate_tokens(s: str) -> int:
    # 至少返回 1，避免空字符串导致预算计算异常
    return max(1, int(len(s) * TOKENS_PER_CHAR))


def chunk_units_by_token_budget(
    units: List[SentenceUnit],
    *,
    context_tokens: int,
    system_prompt: str,
    user_prefix: str,
    output_reserve_tokens: int,
) -> List[List[SentenceUnit]]:
    """
    根据“上下文输入预算”将句子单元切批。

    说明：
    - 我们把 system/user prefix 视为固定成本；
    - body 主要由句子行组成；
    - budget 受 context_tokens 与输出保留 tokens 影响。
    """
    if not units:
        return []

    ctx = max(1, int(context_tokens))
    sys_t = _estimate_tokens(system_prompt)
    prefix_t = _estimate_tokens(user_prefix)
    out_r = max(1, int(output_reserve_tokens))

    body_budget = ctx - sys_t - prefix_t - out_r - LLM_INPUT_SAFETY_TOKENS
    # 极端情况下预算为负：退化到小批处理
    if body_budget <= 0:
        return [units[i : i + max(3, MIN_UNITS_PER_CHUNK)] for i in range(0, len(units), max(3, MIN_UNITS_PER_CHUNK))]

    chunks: List[List[SentenceUnit]] = []
    cur: List[SentenceUnit] = []
    cur_t = 0

    def _line_tokens(u: SentenceUnit) -> int:
        line = f"{u.sid}\t{u.abs_start:.2f}\t{u.abs_start + u.dur:.2f}\t{u.text}"
        return _estimate_tokens(line)

    for u in units:
        lt = _line_tokens(u)
        if cur and cur_t + lt > body_budget and len(cur) >= MIN_UNITS_PER_CHUNK:
            chunks.append(cur)
            cur = []
            cur_t = 0
        cur.append(u)
        cur_t += lt

    if cur:
        chunks.append(cur)
    return chunks


def _parse_keep_json(raw: str, valid_ids: Set[str]) -> Set[str]:
    try:
        data = json.loads(extract_json_object(raw))
    except Exception:
        return set()
    if not isinstance(data, dict):
        return set()
    keep = data.get("keep")
    if not isinstance(keep, list):
        return set()
    out: Set[str] = set()
    for x in keep:
        if isinstance(x, str) and x in valid_ids:
            out.add(x)
    return out


CHUNK_SYSTEM_PROMPT = (
    "你是口播视频剪辑助手。根据【用户诉求】从【本批句子】中选出应保留的句子。"
    "每条句子格式：sid\\t开始秒\\t结束秒\\t文本。sid 必须原样出现在输出中。\n"
    "要求：\n"
    "- 只输出一个 JSON 对象，不要 Markdown，不要解释。格式：{\"keep\":[\"s_000001\",...]}\n"
    "- keep 数组中的 sid 必须全部来自本批列表，禁止编造 id。\n"
    "- 保留最符合【用户诉求】的句子集合；保留多少由用户诉求决定。\n"
    "- 保持语义连贯，避免断裂；如用户要求更完整/更长，可适当保留更多句子。\n"
)

FINAL_SYSTEM_PROMPT = (
    "你是口播视频剪辑助手。你已经看到前面各批次的候选句子（sid）。"
    "现在需要从【所有候选句子】中选出最终要保留的句子，并让整段剪辑更连贯、更符合【用户诉求】。"
    "每条句子格式：sid\\t开始秒\\t结束秒\\t文本。sid 必须原样出现在输出中。\n"
    "要求：\n"
    "- 只输出一个 JSON 对象，不要 Markdown，不要解释。格式：{\"keep\":[\"s_000001\",...]}\n"
    "- keep 数组中的 sid 必须全部来自本批列表，禁止编造 id。\n"
)


async def _llm_keep_for_chunk(
    *,
    llm: LLMClient,
    user_prompt: str,
    chunk: List[SentenceUnit],
    chunk_index: int,
    chunk_total: int,
) -> Set[str]:
    valid = {u.sid for u in chunk}
    lines = []
    for u in chunk:
        lines.append(f"{u.sid}\t{u.abs_start:.2f}\t{u.abs_start + u.dur:.2f}\t{u.text}")
    body = "\n".join(lines)
    sys = CHUNK_SYSTEM_PROMPT
    user = (
        f"【批次】第 {chunk_index + 1}/{chunk_total} 批（长素材已自动分块处理，避免上下文溢出）\n\n"
        f"【用户诉求】\n{user_prompt.strip()}\n\n"
        f"【本批句子】\n{body}"
    )
    raw = await llm.chat(
        [{"role": "system", "content": sys}, {"role": "user", "content": user}],
        temperature=0.25,
        max_tokens=20480,
    )
    return _parse_keep_json(raw, valid)

def _total_speech_duration(units: List[SentenceUnit]) -> float:
    return sum(u.dur for u in units)


def _merge_units_to_segments(
    ordered: List[SentenceUnit],
) -> List[tuple[SentenceUnit, ...]]:
    """同 clip、间隔极小的句子合并为一条成片 segment。"""
    if not ordered:
        return []
    groups: List[list[SentenceUnit]] = []
    cur_g: list[SentenceUnit] = [ordered[0]]
    for u in ordered[1:]:
        prev = cur_g[-1]
        same_clip = prev.clip_id == u.clip_id
        gap = u.st_rel - prev.et_rel
        if same_clip and gap <= MERGE_GAP_SEC:
            cur_g.append(u)
        else:
            groups.append(cur_g)
            cur_g = [u]
    groups.append(cur_g)
    return [tuple(g) for g in groups]


def _apply_buffer(group: tuple[SentenceUnit, ...]) -> tuple[float, float, str]:
    u0 = group[0]
    u1 = group[-1]
    clip_dur = u0.clip_dur
    st = max(0.0, u0.st_rel - BUFFER_SEC)
    et = min(clip_dur if clip_dur > 0 else u1.et_rel, u1.et_rel + BUFFER_SEC)
    if et <= st:
        et = u1.et_rel
    texts = "\n".join(x.text.strip() for x in group if x.text.strip())
    return st, et, texts


async def _llm_keep_for_final_chunk(
    *,
    llm: LLMClient,
    user_prompt: str,
    chunk: List[SentenceUnit],
    chunk_index: int,
    chunk_total: int,
) -> Set[str]:
    """
    最终合并阶段：从所有候选句子里选出最终 keep。

    注意：chunk 仍按 token 预算切批，因此“最终选择”可能分批完成；我们用 union 合并为全局最终 keep。
    """
    valid = {u.sid for u in chunk}
    lines: List[str] = []
    for u in chunk:
        lines.append(f"{u.sid}\t{u.abs_start:.2f}\t{u.abs_start + u.dur:.2f}\t{u.text}")
    body = "\n".join(lines)

    sys = FINAL_SYSTEM_PROMPT
    # 给模型一个明确的阶段说明，减少它把这个步骤当作“又来粗筛一遍”的误解
    user = (
        f"【合并阶段】第 {chunk_index + 1}/{chunk_total} 批（候选句子来自前面批次 union，需最终筛选并保持连贯）\n\n"
        f"【用户诉求】\n{user_prompt.strip()}\n\n"
        f"【所有候选句子】\n{body}"
    )
    raw = await llm.chat(
        [{"role": "system", "content": sys}, {"role": "user", "content": user}],
        temperature=0.2,
        max_tokens=20480,
    )
    return _parse_keep_json(raw, valid)


async def build_semantic_voiceover_plan(
    *,
    clip_groups: Sequence[Sequence[aiosqlite.Row]],
    user_prompt: str,
    cfg: dict[str, Any],
    video_title_hint: str | None,
    video_ids_order: Optional[List[str]] = None,
) -> Plan:
    units = flatten_sentence_units(list(clip_groups))
    if not units:
        return Plan(
            plan_id=uuid.uuid4().hex[:8],
            title="口播快剪（智能）",
            summary="无可用 ASR 句子",
            video_title=(video_title_hint or "").strip() or None,
            video_description=None,
            mode="original",
            target_duration_sec=None,
            estimated_duration_sec=None,
            segments=[],
            bgm=BGMPlan(enabled=False),
            constraints=None,
            keep_flags=PlanKeepFlags(
                clips=False, subtitles=False, transitions=False, bgm=False
            ),
        )

    context_tokens = int(cfg.get("context_tokens") or DEFAULT_LLM_CONTEXT_TOKENS)
    llm_output_reserve = min(int(cfg.get("max_tokens") or 20480), LLM_OUTPUT_RESERVE_TOKENS_CAP)

    user_prefix_for_chunk = (
        "【用户诉求】\n"
        + (user_prompt.strip() if user_prompt else "")
        + "\n\n【本批句子】\n"
    )

    llm = LLMClient(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        temperature=float(cfg.get("temperature") or 0.3),
        max_tokens=int(cfg.get("max_tokens") or 8192),
        timeout=3600.0,
    )

    # 第 1 阶段：分批筛选候选句子（由用户提示词驱动）
    chunks = chunk_units_by_token_budget(
        units,
        context_tokens=context_tokens,
        system_prompt=CHUNK_SYSTEM_PROMPT,
        user_prefix=user_prefix_for_chunk,
        output_reserve_tokens=llm_output_reserve,
    )
    logger.info(
        "voiceover semantic stage1: %d sentences, %d chunk(s), context_tokens=%d",
        len(units),
        len(chunks),
        context_tokens,
    )

    sem = asyncio.Semaphore(3)

    async def _one(i: int, ch: List[SentenceUnit]) -> Set[str]:
        async with sem:
            return await _llm_keep_for_chunk(
                llm=llm,
                user_prompt=user_prompt,
                chunk=ch,
                chunk_index=i,
                chunk_total=len(chunks),
            )

    results = await asyncio.gather(*[_one(i, ch) for i, ch in enumerate(chunks)], return_exceptions=True)
    kept_stage1: Set[str] = set()
    first_stage1_error: Exception | None = None
    for r in results:
        if isinstance(r, Exception):
            logger.warning("智能快剪分块 LLM 失败: %s", r)
            if is_llm_unauthorized_error(r):
                raise RuntimeError(f"LLM 鉴权失败：{r}")
            if first_stage1_error is None:
                first_stage1_error = r
            continue
        kept_stage1 |= r

    if not kept_stage1:
        if first_stage1_error is not None:
            raise RuntimeError(f"智能快剪失败（LLM 分块阶段异常）：{first_stage1_error}")
        logger.warning("智能快剪：LLM 未返回有效 keep，使用启发式兜底")
        scored = sorted(units, key=lambda u: _heuristic_score(u.text), reverse=True)
        # 不限制保留比例：兜底只保证“能剪”
        kept_stage1 = set()
        total = 0.0
        for u in scored[:80]:
            kept_stage1.add(u.sid)
            total += u.dur
            if len(kept_stage1) >= 10 and total >= 20.0:
                break

    # 第 2 阶段：合并候选句子后做最终筛选（仍由用户提示词驱动）
    id_order = {u.sid: i for i, u in enumerate(units)}
    kept_units = [u for u in units if u.sid in kept_stage1]

    # 兼容：kept_stage1 用于 stage2 候选；最终 kept 在 stage2 得出
    vo = video_ids_order or []
    order_map = {str(vid): i for i, vid in enumerate(vo)}
    kept_units.sort(key=lambda u: (order_map.get(u.video_id, 10**9), u.abs_start, id_order[u.sid]))

    candidate_units = kept_units

    user_prefix_for_final = (
        "【用户诉求】\n"
        + (user_prompt.strip() if user_prompt else "")
        + "\n\n【所有候选句子】\n"
    )
    final_chunks = chunk_units_by_token_budget(
        candidate_units,
        context_tokens=context_tokens,
        system_prompt=FINAL_SYSTEM_PROMPT,
        user_prefix=user_prefix_for_final,
        output_reserve_tokens=llm_output_reserve,
    )
    logger.info(
        "voiceover semantic stage2 final: candidate=%d, final_chunk(s)=%d",
        len(candidate_units),
        len(final_chunks),
    )

    async def _final_one(i: int, ch: List[SentenceUnit]) -> Set[str]:
        async with sem:
            return await _llm_keep_for_final_chunk(
                llm=llm,
                user_prompt=user_prompt,
                chunk=ch,
                chunk_index=i,
                chunk_total=len(final_chunks),
            )

    first_stage2_error: Exception | None = None
    if not final_chunks:
        final_kept: Set[str] = set()
    else:
        final_results = await asyncio.gather(
            *[_final_one(i, ch) for i, ch in enumerate(final_chunks)], return_exceptions=True
        )
        final_kept = set()
        for r in final_results:
            if isinstance(r, Exception):
                logger.warning("智能快剪合并阶段 LLM 失败: %s", r)
                if is_llm_unauthorized_error(r):
                    raise RuntimeError(f"LLM 鉴权失败：{r}")
                if first_stage2_error is None:
                    first_stage2_error = r
                continue
            final_kept |= r

    if not final_kept:
        # stage2 空结果：若此前出现异常则直接抛给前端
        # （否则可能是“可用句子太少/模型输出空”的正常情况）
        if first_stage2_error is not None:
            raise RuntimeError(f"智能快剪失败（LLM 合并阶段异常）：{first_stage2_error}")
        logger.warning("智能快剪：合并阶段未返回有效 keep，使用启发式兜底")
        scored = sorted(candidate_units, key=lambda u: _heuristic_score(u.text), reverse=True)
        final_kept = set()
        total = 0.0
        for u in scored[:80]:
            final_kept.add(u.sid)
            total += u.dur
            if len(final_kept) >= 10 and total >= 20.0:
                break

    kept_units = [u for u in units if u.sid in final_kept]
    kept_units.sort(key=lambda u: (order_map.get(u.video_id, 10**9), u.abs_start, id_order[u.sid]))

    merged_groups = _merge_units_to_segments(kept_units)
    segments: List[SegmentPlan] = []
    total_sec = 0.0
    for order, group in enumerate(merged_groups):
        st_rel, et_rel, text = _apply_buffer(group)
        u0 = group[0]
        cid = u0.clip_id
        vid = u0.video_id
        clip_base = u0.clip_base
        dur = max(0.0, et_rel - st_rel)
        if dur <= 0:
            continue
        total_sec += dur
        st_abs = clip_base + st_rel
        et_abs = clip_base + et_rel
        segments.append(
            SegmentPlan(
                id=f"vq_{order:04d}_{cid[:6]}",
                order=order,
                clip_group=[ClipRef(clip_id=cid, video_id=vid, weight=1.0)],
                selected_clip_ids=[cid],
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
    title = f"口播快剪（智能）· {vt}" if vt else "口播快剪（智能）"
    summary = (
        f"智能快剪：分 {len(chunks)} 批筛选候选句子，"
        f"合并阶段保留 {len(final_kept)}/{len(units)} 条句子；"
        f"成片约 {total_sec:.1f}s（已按 LLM 上下文预算分批与最终合并）。"
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
