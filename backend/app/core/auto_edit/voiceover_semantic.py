"""口播智能快剪：基于 ASR 句子 + LLM 分块筛选，含保护策略与上下文分片。"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Set

import aiosqlite

from app.core.llm import LLMClient
from app.core.llm.prompts.voiceover_semantic import CHUNK_SYSTEM_PROMPT, FINAL_SYSTEM_PROMPT
from app.core.llm.response_utils import extract_json_object, is_llm_unauthorized_error
from app.core.auto_edit_v2.template_config import get_memory_style_profile, normalize_content_style
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


def _cap_kept_units_to_duration(units: List[SentenceUnit], max_sec: float) -> List[SentenceUnit]:
    """
    在保持时间顺序前提下，从末尾删句直到语音时长合计 ≤ max_sec。
    （合并段落的 BUFFER 可能使成片略超几秒，max_sec 为句子级近似。）
    """
    if not units or max_sec <= 0:
        return units
    ordered = list(units)
    total = sum(u.dur for u in ordered)
    if total <= max_sec + 0.05:
        return ordered
    dropped = 0
    while len(ordered) > 1 and total > max_sec + 0.05:
        ordered.pop()
        dropped += 1
        total = sum(u.dur for u in ordered)
    if total > max_sec + 0.05 and len(ordered) == 1:
        logger.warning(
            "智能快剪时长压制：单句时长 %.1fs 已超过目标 %.1fs，保留该句（请考虑改文案或切 ASR）",
            total,
            max_sec,
        )
    elif dropped:
        logger.info(
            "智能快剪时长压制：目标≤%.1fs，从末尾移除 %d 条句子，剩余约 %.1fs",
            max_sec,
            dropped,
            total,
        )
    return ordered


# 分块：按 token 上下文预算切批，避免上下文溢出
MIN_UNITS_PER_CHUNK = 6
MERGE_GAP_SEC = 0.25
BUFFER_SEC = 0.08
DEFAULT_CHAPTER_TARGET_SEC = 150.0
MIN_CHAPTERS = 3
MAX_CHAPTERS = 10

# 兼容旧实现的字符级退化切批（当 token 预算异常时使用）
MAX_CHUNK_BODY_CHARS = 9000

# token 估算：默认按 1 token ≈ 4 个字符；可由设置页透传覆盖
DEFAULT_TOKENS_PER_CHAR = 1 / 4
LLM_INPUT_SAFETY_TOKENS = 400
LLM_OUTPUT_RESERVE_TOKENS_CAP = 2048

DEFAULT_LLM_CONTEXT_TOKENS = 128000
_GENERIC_MEMORY_STYLE = get_memory_style_profile("generic")

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


@dataclass(frozen=True)
class ChapterWindow:
    chapter_id: str
    title: str
    start_sec: float
    end_sec: float
    units: tuple[SentenceUnit, ...]


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


def _estimate_tokens(s: str, *, tokens_per_char: float = DEFAULT_TOKENS_PER_CHAR) -> int:
    # 至少返回 1，避免空字符串导致预算计算异常
    tpc = tokens_per_char if tokens_per_char > 0 else DEFAULT_TOKENS_PER_CHAR
    return max(1, int(len(s) * tpc))


def chunk_units_by_token_budget(
    units: List[SentenceUnit],
    *,
    context_tokens: int,
    system_prompt: str,
    user_prefix: str,
    output_reserve_tokens: int,
    tokens_per_char: float = DEFAULT_TOKENS_PER_CHAR,
    input_safety_tokens: int = LLM_INPUT_SAFETY_TOKENS,
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
    sys_t = _estimate_tokens(system_prompt, tokens_per_char=tokens_per_char)
    prefix_t = _estimate_tokens(user_prefix, tokens_per_char=tokens_per_char)
    out_r = max(1, int(output_reserve_tokens))
    in_safe = max(1, int(input_safety_tokens))

    body_budget = ctx - sys_t - prefix_t - out_r - in_safe
    # 极端情况下预算为负：退化到小批处理
    if body_budget <= 0:
        return [units[i : i + max(3, MIN_UNITS_PER_CHUNK)] for i in range(0, len(units), max(3, MIN_UNITS_PER_CHUNK))]

    chunks: List[List[SentenceUnit]] = []
    cur: List[SentenceUnit] = []
    cur_t = 0

    def _line_tokens(u: SentenceUnit) -> int:
        line = f"{u.sid}\t{u.abs_start:.2f}\t{u.abs_start + u.dur:.2f}\t{u.text}"
        return _estimate_tokens(line, tokens_per_char=tokens_per_char)

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


def _resolve_chapter_count(total_dur: float, cfg: dict[str, Any]) -> int:
    raw = cfg.get("chapter_count")
    if raw is not None:
        try:
            n = int(raw)
            if n > 0:
                return min(MAX_CHAPTERS, max(1, n))
        except Exception:
            pass
    target = DEFAULT_CHAPTER_TARGET_SEC
    try:
        target = float(cfg.get("chapter_target_sec") or DEFAULT_CHAPTER_TARGET_SEC)
    except Exception:
        target = DEFAULT_CHAPTER_TARGET_SEC
    target = max(60.0, target)
    auto_n = int(max(1.0, round(total_dur / target)))
    # 长视频至少按 3 章处理，降低跨章节丢失概率
    return min(MAX_CHAPTERS, max(MIN_CHAPTERS, auto_n))


def _resolve_memory_style(cfg: dict[str, Any]) -> dict[str, Any]:
    raw = normalize_content_style(str(cfg.get("content_style") or cfg.get("video_style") or "generic"))
    preset = get_memory_style_profile(raw)

    # 可选自定义覆盖，保证不同业务线都能兼容扩展
    custom = cfg.get("memory_style")
    if isinstance(custom, dict):
        for k in (
            "happened_label",
            "open_label",
            "state_label",
            "happened_markers",
            "open_markers",
            "state_markers",
        ):
            if k in custom and custom[k]:
                preset[k] = custom[k]
    return preset


def _build_chapter_windows(
    units: List[SentenceUnit],
    *,
    chapter_count: int,
) -> List[ChapterWindow]:
    if not units:
        return []
    st = min(u.abs_start for u in units)
    et = max(u.abs_start + u.dur for u in units)
    total = max(1e-6, et - st)
    chapter_count = max(1, int(chapter_count))
    span = total / chapter_count
    windows: List[ChapterWindow] = []
    for i in range(chapter_count):
        cst = st + i * span
        cet = et if i == chapter_count - 1 else (st + (i + 1) * span)
        subset = [
            u for u in units
            if (u.abs_start + u.dur) > cst and u.abs_start < cet
        ]
        if not subset:
            continue
        windows.append(
            ChapterWindow(
                chapter_id=f"ch_{i + 1:02d}",
                title=f"第{i + 1}章",
                start_sec=cst,
                end_sec=cet,
                units=tuple(subset),
            )
        )
    return windows



def _compact_text(s: str, *, max_len: int = 42) -> str:
    t = " ".join((s or "").split())
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _build_chapter_memory(
    kept_units: List[SentenceUnit],
    memory_style: dict[str, Any],
    *,
    happened_max_points: int = 4,
    clue_max_points: int = 3,
    state_max_points: int = 3,
) -> str:
    """
    结构化章节记忆：
    - 已发生：本章核心事件
    - 待回收线索：疑问句/未完结表达
    - 人物状态：情绪或状态描述
    """
    happened_label = str(memory_style.get("happened_label") or "已发生")
    open_label = str(memory_style.get("open_label") or "待展开点")
    state_label = str(memory_style.get("state_label") or "表达状态")
    if not kept_units:
        return f"【{happened_label}】\n- （暂无）\n【{open_label}】\n- （暂无）\n【{state_label}】\n- （暂无）"

    scored = sorted(
        kept_units,
        key=lambda u: (_heuristic_score(u.text), u.dur),
        reverse=True,
    )
    happened: list[str] = []
    clues: list[str] = []
    states: list[str] = []
    seen: set[str] = set()

    state_markers = tuple(memory_style.get("state_markers") or _GENERIC_MEMORY_STYLE["state_markers"])
    clue_markers = tuple(memory_style.get("open_markers") or _GENERIC_MEMORY_STYLE["open_markers"])
    happened_markers = tuple(memory_style.get("happened_markers") or ())

    for u in scored:
        text = _compact_text(u.text, max_len=36)
        if not text or text in seen:
            continue
        seen.add(text)

        if len(clues) < clue_max_points and any(m in text for m in clue_markers):
            clues.append(f"- {text}")
        if len(states) < state_max_points and any(m in text for m in state_markers):
            states.append(f"- {text}")
        if len(happened) < happened_max_points and (not happened_markers or any(m in text for m in happened_markers)):
            happened.append(f"- {text}")

        if (
            len(happened) >= happened_max_points
            and len(clues) >= clue_max_points
            and len(states) >= state_max_points
        ):
            break

    if not happened:
        # 未命中业务 marker 时，退回通用高分句兜底
        for u in scored[:happened_max_points]:
            happened.append(f"- {_compact_text(u.text, max_len=36)}")
        if not happened:
            happened = ["- （暂无）"]
    if not clues:
        clues = ["- （暂无）"]
    if not states:
        states = ["- （暂无）"]

    return (
        f"【{happened_label}】\n"
        + "\n".join(happened)
        + f"\n【{open_label}】\n"
        + "\n".join(clues)
        + f"\n【{state_label}】\n"
        + "\n".join(states)
    )


def _pick_chapter_opening_anchors(
    chapter_units: List[SentenceUnit],
    current_kept: Set[str],
    continuity_memory: str,
    *,
    min_anchor_count: int,
) -> Set[str]:
    """
    章节首句锚点约束：在章节前段补入可承接上文记忆的 1~N 句。
    """
    if min_anchor_count <= 0 or not chapter_units:
        return set()

    # 只在章节前段挑选，避免“锚点”跑到章节中后部
    head_pool = sorted(chapter_units, key=lambda u: u.abs_start)[: max(8, min(20, len(chapter_units)))]

    # 用上文记忆抽取关键词做轻量相似度打分
    memory_keywords = {
        tk
        for tk in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", continuity_memory)
        if len(tk) >= 2 and tk != "暂无"
    }

    def _anchor_score(u: SentenceUnit) -> float:
        t = u.text or ""
        overlap = sum(1 for tk in memory_keywords if tk in t)
        # 越靠前越有利
        pos_bonus = max(0.0, 3.0 - (u.abs_start - head_pool[0].abs_start) * 0.2)
        return overlap * 3.0 + _heuristic_score(t) * 0.2 + pos_bonus

    ranked = sorted(head_pool, key=_anchor_score, reverse=True)
    anchors: Set[str] = set()

    # 优先保留已入选的前段句子作为锚点
    for u in ranked:
        if u.sid in current_kept:
            anchors.add(u.sid)
            if len(anchors) >= min_anchor_count:
                return anchors

    # 不足则从前段高分句补齐，保证有承接开头
    for u in ranked:
        anchors.add(u.sid)
        if len(anchors) >= min_anchor_count:
            break
    return anchors


async def _llm_keep_for_chunk(
    *,
    llm: LLMClient,
    user_prompt: str,
    chunk: List[SentenceUnit],
    chunk_index: int,
    chunk_total: int,
    max_tokens: int,
    chapter_title: str,
    chapter_range: str,
    continuity_memory: str,
) -> Set[str]:
    valid = {u.sid for u in chunk}
    lines = []
    for u in chunk:
        lines.append(f"{u.sid}\t{u.abs_start:.2f}\t{u.abs_start + u.dur:.2f}\t{u.text}")
    body = "\n".join(lines)
    sys = CHUNK_SYSTEM_PROMPT
    user = (
        f"【章节】{chapter_title}（{chapter_range}）\n"
        f"【批次】第 {chunk_index + 1}/{chunk_total} 批（长素材已自动分块处理，避免上下文溢出）\n\n"
        f"【上文记忆】\n{continuity_memory}\n\n"
        f"【用户诉求】\n{user_prompt.strip()}\n\n"
        f"【本批句子】\n{body}"
    )
    raw = await llm.chat(
        [{"role": "system", "content": sys}, {"role": "user", "content": user}],
        temperature=0.25,
        max_tokens=max_tokens,
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
    max_tokens: int,
    chapter_title: str,
    chapter_range: str,
    continuity_memory: str,
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
        f"【章节】{chapter_title}（{chapter_range}）\n"
        f"【合并阶段】第 {chunk_index + 1}/{chunk_total} 批（候选句子来自前面批次 union，需最终筛选并保持连贯）\n\n"
        f"【上文记忆】\n{continuity_memory}\n\n"
        f"【用户诉求】\n{user_prompt.strip()}\n\n"
        f"【所有候选句子】\n{body}"
    )
    raw = await llm.chat(
        [{"role": "system", "content": sys}, {"role": "user", "content": user}],
        temperature=0.2,
        max_tokens=max_tokens,
    )
    return _parse_keep_json(raw, valid)

# 构建智能快剪计划
async def build_semantic_voiceover_plan(
    *,
    clip_groups: Sequence[Sequence[aiosqlite.Row]],
    user_prompt: str,
    cfg: dict[str, Any],
    video_title_hint: str | None,
    video_ids_order: Optional[List[str]] = None,
    target_duration_sec: Optional[float] = None,
) -> Plan:
    def _cfg_int(name: str, default: int) -> int:
        try:
            return int(cfg.get(name) or default)
        except (TypeError, ValueError):
            return int(default)

    def _cfg_float(name: str, default: float) -> float:
        try:
            return float(cfg.get(name) or default)
        except (TypeError, ValueError):
            return float(default)

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

    context_tokens = max(1, _cfg_int("context_tokens", DEFAULT_LLM_CONTEXT_TOKENS))
    llm_max_tokens = max(1, _cfg_int("max_tokens", 65536))
    llm_output_reserve = min(max(1, _cfg_int("output_reserve_tokens", llm_max_tokens)), LLM_OUTPUT_RESERVE_TOKENS_CAP)
    tokens_per_char = _cfg_float("tokens_per_char", DEFAULT_TOKENS_PER_CHAR)
    input_safety_tokens = max(1, _cfg_int("input_safety_tokens", LLM_INPUT_SAFETY_TOKENS))
    chapter_anchor_min = max(0, _cfg_int("chapter_anchor_min", 1))
    memory_style = _resolve_memory_style(cfg)

    target_cap: Optional[float] = None
    if target_duration_sec is not None:
        try:
            tv = float(target_duration_sec)
            if tv > 0:
                target_cap = tv
        except (TypeError, ValueError):
            target_cap = None

    raw_up = (user_prompt or "").strip()
    duration_note = ""
    if target_cap is not None:
        duration_note = (
            f"\n\n【成片时长约束】所选句子的语音时长（各句「结束秒−开始秒」之和）合计不得超过约 {target_cap:.0f} 秒；"
            "宁可少保留也不要超出；难以取舍时优先保留最贴合诉求、信息密度最高的句子。"
        )
    llm_prompt_body = raw_up + duration_note

    user_prefix_for_chunk = "【用户诉求】\n" + llm_prompt_body + "\n\n【本批句子】\n"

    llm = LLMClient(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        temperature=float(cfg.get("temperature") or 0.3),
        max_tokens=llm_max_tokens,
        timeout=3600.0,
    )

    vo = video_ids_order or []
    order_map = {str(vid): i for i, vid in enumerate(vo)}
    id_order = {u.sid: i for i, u in enumerate(units)}
    ordered_units = sorted(
        units,
        key=lambda u: (order_map.get(u.video_id, 10**9), u.abs_start, id_order[u.sid]),
    )
    total_speech = _total_speech_duration(ordered_units)
    chapter_count = _resolve_chapter_count(total_speech, cfg)
    chapter_windows = _build_chapter_windows(ordered_units, chapter_count=chapter_count)
    if not chapter_windows:
        chapter_windows = [
            ChapterWindow(
                chapter_id="ch_01",
                title="第1章",
                start_sec=min(u.abs_start for u in ordered_units),
                end_sec=max(u.abs_start + u.dur for u in ordered_units),
                units=tuple(ordered_units),
            )
        ]

    logger.info(
        "口播快剪（长视频模式）：句子数=%d, 语音时长=%.1fs, 章节数=%d",
        len(ordered_units),
        total_speech,
        len(chapter_windows),
    )

    sem = asyncio.Semaphore(3)
    final_kept: Set[str] = set()
    chapter_meta: list[dict[str, Any]] = []
    continuity_memory = _build_chapter_memory([], memory_style)

    for cw in chapter_windows:
        chapter_units = list(cw.units)
        chapter_range = f"{cw.start_sec:.1f}s-{cw.end_sec:.1f}s"
        chapter_prefix_for_chunk = (
            f"【章节】{cw.title}（{chapter_range}）\n"
            + user_prefix_for_chunk
        )
        chunks = chunk_units_by_token_budget(
            chapter_units,
            context_tokens=context_tokens,
            system_prompt=CHUNK_SYSTEM_PROMPT,
            user_prefix=chapter_prefix_for_chunk,
            output_reserve_tokens=llm_output_reserve,
            tokens_per_char=tokens_per_char,
            input_safety_tokens=input_safety_tokens,
        )
        logger.info(
            "口播快剪（长视频模式）：%s 分块阶段：句子数=%d 分批数=%d",
            cw.chapter_id,
            len(chapter_units),
            len(chunks),
        )

        async def _one(i: int, ch: List[SentenceUnit]) -> Set[str]:
            async with sem:
                return await _llm_keep_for_chunk(
                    llm=llm,
                    user_prompt=llm_prompt_body,
                    chunk=ch,
                    chunk_index=i,
                    chunk_total=len(chunks),
                    max_tokens=llm_max_tokens,
                    chapter_title=cw.title,
                    chapter_range=chapter_range,
                    continuity_memory=continuity_memory,
                )

        results = await asyncio.gather(*[_one(i, ch) for i, ch in enumerate(chunks)], return_exceptions=True)
        kept_stage1: Set[str] = set()
        first_stage1_error: Exception | None = None
        for r in results:
            if isinstance(r, Exception):
                logger.warning("智能快剪分块 LLM 失败(%s): %s", cw.chapter_id, r)
                if is_llm_unauthorized_error(r):
                    raise RuntimeError(f"LLM 鉴权失败：{r}")
                if first_stage1_error is None:
                    first_stage1_error = r
                continue
            kept_stage1 |= r

        if not kept_stage1:
            if first_stage1_error is not None:
                raise RuntimeError(f"智能快剪失败（LLM 分块阶段异常）：{first_stage1_error}")
            logger.warning("智能快剪：%s stage1 空结果，使用启发式兜底", cw.chapter_id)
            scored = sorted(chapter_units, key=lambda u: _heuristic_score(u.text), reverse=True)
            kept_stage1 = set()
            total = 0.0
            for u in scored[:40]:
                kept_stage1.add(u.sid)
                total += u.dur
                if len(kept_stage1) >= 6 and total >= 12.0:
                    break

        candidate_units = [u for u in chapter_units if u.sid in kept_stage1]
        chapter_prefix_for_final = (
            f"【章节】{cw.title}（{chapter_range}）\n"
            + "【用户诉求】\n"
            + llm_prompt_body
            + "\n\n【所有候选句子】\n"
        )
        final_chunks = chunk_units_by_token_budget(
            candidate_units,
            context_tokens=context_tokens,
            system_prompt=FINAL_SYSTEM_PROMPT,
            user_prefix=chapter_prefix_for_final,
            output_reserve_tokens=llm_output_reserve,
            tokens_per_char=tokens_per_char,
            input_safety_tokens=input_safety_tokens,
        )
        logger.info(
            "口播快剪（长视频模式）：%s 合并阶段：候选句子数=%d 分批数=%d",
            cw.chapter_id,
            len(candidate_units),
            len(final_chunks),
        )

        async def _final_one(i: int, ch: List[SentenceUnit]) -> Set[str]:
            async with sem:
                return await _llm_keep_for_final_chunk(
                    llm=llm,
                    user_prompt=llm_prompt_body,
                    chunk=ch,
                    chunk_index=i,
                    chunk_total=len(final_chunks),
                    max_tokens=llm_max_tokens,
                    chapter_title=cw.title,
                    chapter_range=chapter_range,
                    continuity_memory=continuity_memory,
                )

        chapter_final_kept: Set[str] = set()
        first_stage2_error: Exception | None = None
        if final_chunks:
            final_results = await asyncio.gather(
                *[_final_one(i, ch) for i, ch in enumerate(final_chunks)], return_exceptions=True
            )
            for r in final_results:
                if isinstance(r, Exception):
                    logger.warning("智能快剪合并阶段 LLM 失败(%s): %s", cw.chapter_id, r)
                    if is_llm_unauthorized_error(r):
                        raise RuntimeError(f"LLM 鉴权失败：{r}")
                    if first_stage2_error is None:
                        first_stage2_error = r
                    continue
                chapter_final_kept |= r

        if not chapter_final_kept:
            if first_stage2_error is not None:
                raise RuntimeError(f"智能快剪失败（LLM 合并阶段异常）：{first_stage2_error}")
            logger.warning("智能快剪：%s stage2 空结果，使用启发式兜底", cw.chapter_id)
            scored = sorted(candidate_units, key=lambda u: _heuristic_score(u.text), reverse=True)
            total = 0.0
            for u in scored[:40]:
                chapter_final_kept.add(u.sid)
                total += u.dur
                if len(chapter_final_kept) >= 6 and total >= 12.0:
                    break

        # 章节首句锚点约束：确保章节开头存在承接上文的句子
        anchor_ids = _pick_chapter_opening_anchors(
            chapter_units,
            chapter_final_kept,
            continuity_memory,
            min_anchor_count=chapter_anchor_min,
        )
        chapter_final_kept |= anchor_ids

        final_kept |= chapter_final_kept
        chapter_kept_units = [u for u in chapter_units if u.sid in chapter_final_kept]
        continuity_memory = _build_chapter_memory(chapter_kept_units, memory_style)
        chapter_meta.append(
            {
                "id": cw.chapter_id,
                "title": cw.title,
                "memory_style": normalize_content_style(
                    str(cfg.get("content_style") or cfg.get("video_style") or "generic")
                ),
                "range": [round(cw.start_sec, 2), round(cw.end_sec, 2)],
                "input_sentence_count": len(chapter_units),
                "candidate_sentence_count": len(candidate_units),
                "kept_sentence_count": len(chapter_final_kept),
                "anchor_sentence_count": len(anchor_ids),
                "continuity_memory": continuity_memory,
            }
        )

    kept_units = [u for u in ordered_units if u.sid in final_kept]
    if target_cap is not None:
        pre_dur = sum(u.dur for u in kept_units)
        kept_units = _cap_kept_units_to_duration(kept_units, target_cap)
        post_dur = sum(u.dur for u in kept_units)
        if pre_dur > post_dur + 0.1:
            final_kept = {u.sid for u in kept_units}

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
    cap_line = ""
    if target_cap is not None:
        cap_line = f"目标成片时长约 {target_cap:.0f}s；"
    summary = (
        f"智能快剪（长视频模式）：{cap_line}按 {len(chapter_windows)} 章分治筛选，"
        f"最终保留 {len(final_kept)}/{len(units)} 条句子；"
        f"成片约 {total_sec:.1f}s（按上下文预算切批并分章合并）。"
    )
    return Plan(
        plan_id=uuid.uuid4().hex[:8],
        title=title,
        summary=summary,
        video_title=vt or None,
        video_description=None,
        mode="original",
        target_duration_sec=target_cap,
        estimated_duration_sec=round(total_sec, 2) if total_sec > 0 else None,
        chapters=chapter_meta or None,
        segments=segments,
        bgm=BGMPlan(enabled=False),
        constraints=None,
        keep_flags=PlanKeepFlags(
            clips=False, subtitles=False, transitions=False, bgm=False
        ),
    )
