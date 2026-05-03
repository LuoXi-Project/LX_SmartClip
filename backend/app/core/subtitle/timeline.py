"""字幕时间轴生成：规则法 & LLM 法，以及依赖的工具函数。"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import TYPE_CHECKING

from json_repair import repair_json

from app.core.llm import LLMClient
from app.core.llm.prompts.subtitle_timeline import _LLM_SYS_PROMPT
from app.utils.ffprobe_utils import probe_duration

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 音频时长
# ---------------------------------------------------------------------------

def audio_duration(path: str) -> float:
    """用 MoviePy AudioFileClip 读取音频时长，替代 ffprobe subprocess。"""
    try:
        from moviepy import AudioFileClip
        with AudioFileClip(path) as clip:
            return clip.duration
    except Exception as e:
        logger.warning("AudioFileClip duration failed %s: %s", path, e)
        return 0.0


# ---------------------------------------------------------------------------
# 时长解析
# ---------------------------------------------------------------------------

def _tts_file_duration(path: str) -> float:
    """与 burn_to_mp4 一致：优先 ffprobe，失败再 MoviePy。"""
    d = probe_duration(path, log_on_failure=True)
    if d > 0:
        return d
    d = audio_duration(path)
    if d > 0:
        logger.warning("字幕时长[TTS] ffprobe 无效，回退 MoviePy: %s=%.3f秒", path, d)
    return d


def resolve_durations(segments, clip_durations: dict, tts_audio_dir: str, use_tts: bool):
    """
    按优先级确定每个片段时长（须与 `burn_to_mp4` 实际输出的段落时长一致）。

    - 有 TTS 时：用 ffprobe 测长（与烧录相同），不用 MoviePy 单独值，避免与成片差几百毫秒。
    - 同时存在 `duration_sec` 与 TTS 时：取 min(TTS, manual)，与烧录里 `-t`/截断逻辑一致。
    - 无 TTS：manual 或 clip 时长。
    返回 (durations: list[float], source: str)
    """
    durs = []
    srcs = []
    for seg in segments:
        manual = getattr(seg, "duration_sec", None)
        try:
            manual_v = float(manual) if manual is not None else None
        except Exception:
            manual_v = None
        if manual_v is not None and manual_v <= 0:
            manual_v = None

        tl_raw = getattr(seg, "timeline_duration_sec", None)
        try:
            tl_v = float(tl_raw) if tl_raw is not None else None
        except Exception:
            tl_v = None
        if tl_v is not None and tl_v > 0.05:
            durs.append(tl_v)
            srcs.append("timeline_override")
            continue

        tts_d = None
        if use_tts and getattr(seg, "tts_filename", None):
            p = os.path.join(tts_audio_dir, os.path.basename(seg.tts_filename))
            tts_d = _tts_file_duration(p)

        if manual_v is not None:
            if tts_d is not None and tts_d > 0:
                durs.append(min(tts_d, manual_v))
                srcs.append("tts_manual_min")
            else:
                durs.append(manual_v)
                srcs.append("manual")
            continue

        if tts_d is not None and tts_d > 0:
            durs.append(tts_d)
            srcs.append("tts")
            logger.info("字幕时长[TTS] %s=%.3f秒", seg.tts_filename, tts_d)
            continue

        trims = getattr(seg, "clip_trims", None)
        if trims:
            # 按 trims 顺序累加（同一 clip_id 多段拼接时不能用 dict 去重覆盖）
            total_tr = 0.0
            for t in trims:
                try:
                    total_tr += max(0.05, float(getattr(t, "duration_sec", 0) or 0))
                except Exception:
                    total_tr += 0.05
            durs.append(max(total_tr, 0.05))
            srcs.append("clip_trims")
            continue

        durs.append(clip_durations.get(seg.clip_id, 5.0))
        srcs.append("clip")
    source = srcs[0] if len(set(srcs)) == 1 else "mixed"
    return durs, source


# ---------------------------------------------------------------------------
# 规则法时间轴
# ---------------------------------------------------------------------------

_WEIGHT_CHAR_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")


def _text_weight_chars(text: str) -> int:
    """
    用“可发音字符”的粗略数量作为时长权重：中文汉字 + 英文/数字。
    目的是在“匀速 TTS”场景下，让长句获得更长展示时长。
    """
    t = (text or "").strip()
    if not t:
        return 1
    n = len(_WEIGHT_CHAR_RE.findall(t))
    return n if n > 0 else 1


def _allocate_durations_by_weight(
    total_dur: float,
    weights: list[int],
    *,
    min_unit_dur: float = 0.18,
) -> list[float]:
    """
    将 total_dur 按 weights 分配到 N 条，保证：
    - 每条 >= min_unit_dur（总时长不足时自动回退到 total_dur / N）
    - 总和精确等于 total_dur（最后一条吸收浮点残差）
    """
    n = len(weights)
    if n <= 0:
        return []
    if n == 1:
        return [float(total_dur)]

    total = float(total_dur or 0.0)
    if total <= 0:
        # 兜底：保持与旧逻辑一致
        return [0.0 for _ in range(n)]

    min_d = float(min_unit_dur or 0.0)
    if min_d <= 0:
        min_d = 0.0
    if min_d * n > total:
        min_d = total / n

    base = [min_d for _ in range(n)]
    remain = total - (min_d * n)

    wsum = float(sum(max(1, int(w or 1)) for w in weights))
    if remain > 0 and wsum > 0:
        extras = [remain * (max(1, int(w or 1)) / wsum) for w in weights]
        out = [base[i] + extras[i] for i in range(n)]
    else:
        out = base

    # 吸收浮点残差，保证精确铺满段落
    diff = total - sum(out)
    out[-1] += diff
    return out


def rule_timeline(segments, durations: list[float], max_chars: int = 20) -> list:
    """
    基于规则将文案拆分到时间轴：优先整句/换行，过长再在句内标点处断行，无标点则按字数强切；时长按条数均分。
    返回 [{clip_id, start, end, text}, ...]
    """
    entries = []
    t = 0.0
    mc = int(max_chars or 0)
    for seg, dur in zip(segments, durations):
        text = seg.copy_text.strip()
        if not text:
            t += dur
            continue
        units = split_text_units_by_sentence_and_newline(text)
        chunks = _expand_units_with_char_limit(units, mc) if mc > 0 else [u.strip() for u in units if u.strip()]
        if not chunks:
            t += dur
            continue
        nchunk = len(chunks)
        cd = dur / nchunk
        ss = t
        for ci, chunk in enumerate(chunks):
            cs = ss + ci * cd
            # 与 rule_timeline_equal_units 一致：条与条首尾相接，铺满整段 TTS/段落时长（避免旧逻辑每条缩短 0.05s 造成与配音脱节）
            ce = ss + dur if ci == nchunk - 1 else ss + (ci + 1) * cd
            entries.append(
                {"clip_id": seg.clip_id, "start": round(cs, 3), "end": round(ce, 3), "text": chunk}
            )
        t += dur
    return entries


def rule_timeline_weighted_chars(
    segments,
    durations: list[float],
    max_chars: int = 20,
    *,
    min_unit_dur: float = 0.18,
) -> list:
    """
    规则法时间轴（按字数权重分配时长）：
    - 切分规则与 rule_timeline 一致
    - 段落总时长由 durations 决定（常来自 TTS 音频时长）
    - 段内每条字幕时长按“可发音字符数”加权分配，更贴近匀速 TTS
    返回 [{clip_id, start, end, text}, ...]
    """
    entries: list[dict] = []
    t = 0.0
    mc = int(max_chars or 0)
    for seg, dur in zip(segments, durations):
        seg_dur = float(dur or 0.0)
        text = (getattr(seg, "copy_text", "") or "").strip()
        if not text:
            t += seg_dur
            continue

        units = split_text_units_by_sentence_and_newline(text)
        chunks = _expand_units_with_char_limit(units, mc) if mc > 0 else [u.strip() for u in units if u.strip()]
        if not chunks:
            t += seg_dur
            continue

        weights = [_text_weight_chars(c) for c in chunks]
        dlist = _allocate_durations_by_weight(seg_dur, weights, min_unit_dur=min_unit_dur)
        ss = t
        cur = ss
        for i, chunk in enumerate(chunks):
            start = cur
            end = ss + seg_dur if i == len(chunks) - 1 else (cur + float(dlist[i] or 0.0))
            entries.append(
                {
                    "clip_id": seg.clip_id,
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": chunk,
                }
            )
            cur = end
        t += seg_dur
    return entries


def split_text_units_by_sentence_and_newline(text: str) -> list[str]:
    """
    将文本按“换行 + 句子结束符”切分为若干字幕单位。

    单位切分规则（尽量贴近产品语义）：
    - 先按换行拆行（空行忽略）
    - 再在每一行内按句子结束符拆分：。！？!?
    - 同时把省略号（… / ……）当做结束符处理
    """
    if text is None:
        return []
    # 统一换行
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")

    units: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue

        buf: list[str] = []
        i = 0
        while i < len(line):
            # 处理省略号
            if line.startswith("……", i):
                buf.append("……")
                units.append("".join(buf).strip())
                buf = []
                i += 2
                continue
            if line.startswith("…", i):
                buf.append("…")
                units.append("".join(buf).strip())
                buf = []
                i += 1
                continue

            ch = line[i]
            buf.append(ch)
            if ch in "。！？!?":
                units.append("".join(buf).strip())
                buf = []
            i += 1

        if buf:
            tail = "".join(buf).strip()
            if tail:
                units.append(tail)

    return [u for u in units if u]


# 句内可读断点：逗号、顿号、分号、冒号等（句末。！？已在上面拆过）
_INTRA_CLAUSE_BREAK_CHARS = frozenset("，、；;：")


def _is_dot_clause_break(s: str, i: int) -> bool:
    """英文句点作断点，但排除小数点。"""
    if s[i] != ".":
        return False
    if i > 0 and i + 1 < len(s) and s[i - 1].isdigit() and s[i + 1].isdigit():
        return False
    return True


def split_long_text_at_punctuation(text: str, max_chars: int) -> list[str]:
    """
    在单条字幕字数上限内切分：优先在句内标点处断行，其次英文单词边界（空格），最后强切。

    与「先整句、再短句、再无标点硬切」配合使用：调用方应先按句子/换行拆好，再对本函数处理超长片段。
    """
    text = (text or "").strip()
    if not text:
        return []
    mc = int(max_chars or 0)
    if mc <= 0 or len(text) <= mc:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= mc:
            chunks.append(remaining.strip())
            break

        window = remaining[:mc]
        cut = -1

        for i in range(len(window) - 1, -1, -1):
            ch = window[i]
            if ch in _INTRA_CLAUSE_BREAK_CHARS or ch in ",!?！？…":
                cut = i + 1
                break
            if _is_dot_clause_break(remaining, i):
                cut = i + 1
                break

        if cut <= 0:
            sp = window.rfind(" ")
            if sp >= max(mc // 3, 1):
                cut = sp + 1

        if cut <= 0:
            cut = mc

        piece = remaining[:cut]
        remaining = remaining[cut:].lstrip()
        piece = piece.rstrip()
        if piece:
            chunks.append(piece)
        elif not remaining:
            break

    return [c for c in chunks if c]


def _expand_units_with_char_limit(units: list[str], max_chars: int) -> list[str]:
    """句子级单位 → 按字数上限再拆（标点优先、最后强切）。"""
    if not units or max_chars <= 0:
        return [u.strip() for u in units if (u or "").strip()]
    out: list[str] = []
    for u in units:
        u = (u or "").strip()
        if not u:
            continue
        out.extend(split_long_text_at_punctuation(u, max_chars))
    return out


def rule_timeline_equal_units(segments, durations: list[float], max_chars: int = 20) -> list[dict]:
    """
    将每段文本切分为多个“单位”，并把该段的总时长平均分配到各单位。

    先按换行与句末标点拆句，再在超长句上按句内标点优先、最后强切以满足 `max_chars`。
    返回格式：[{start, end, text}, ...]
    """
    entries: list[dict] = []
    t = 0.0
    max_chars = int(max_chars or 0)

    for seg, seg_dur in zip(segments, durations):
        dur = float(seg_dur or 0.0)
        if dur <= 0:
            dur = 5.0

        units = split_text_units_by_sentence_and_newline(getattr(seg, "copy_text", "") or "")
        if max_chars > 0 and units:
            units = _expand_units_with_char_limit(units, max_chars)
        elif units:
            units = [u.strip() for u in units if (u or "").strip()]
        n = len(units)
        if n == 0:
            t += dur
            continue

        unit_dur = dur / n
        for i, unit in enumerate(units):
            start = t + i * unit_dur
            end = t + (i + 1) * unit_dur
            # 保证最后一个单位精确落在段尾（避免浮点误差）
            if i == n - 1:
                end = t + dur
            entries.append(
                {
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": unit.strip(),
                }
            )
        t += dur

    return entries


# ---------------------------------------------------------------------------
# LLM 法时间轴
# ---------------------------------------------------------------------------


async def llm_timeline(
    segments,
    durations: list[float],
    llm_client: LLMClient,
) -> list:
    """
    调用 LLM 生成字幕时间轴。
    
    Args:
        segments: 字幕段落列表
        durations: 每个段落的时长列表
        llm_client: LLMClient 实例
    
    Returns:
        [{clip_id, start, end, text}, ...]
    """
    info = []
    cum = 0.0
    for seg, dur in zip(segments, durations):
        info.append(f'clip_id={seg.clip_id} start={cum:.3f}s dur={dur:.3f}s text="{seg.copy_text}"')
        cum += dur

    messages = [
        {"role": "system", "content": _LLM_SYS_PROMPT},
        {"role": "user", "content": "生成时间轴:\n" + "\n".join(info)},
    ]

    try:
        raw = await llm_client.chat(messages, temperature=0.2, max_tokens=20480)
    except Exception as e:
        logger.error("LLM 时间轴生成失败: %s", e)
        raise RuntimeError(f"LLM 调用失败: {e}")

    # 第一步：尝试直接解析 JSON
    try:
        # logger.warning(f"raw: {raw}")
        p = json.loads(raw)
        entries = p.get("entries", []) if isinstance(p, dict) else p
        if not entries and isinstance(p, dict):
            entries = next((v for v in p.values() if isinstance(v, list)), [])
        return entries
    except json.JSONDecodeError:
        logger.debug("JSON 直接解析失败，尝试正则提取")

    # 第二步：尝试正则提取 JSON 数组
    try:
        m2 = re.search(r"\[.*\]", raw, re.DOTALL)
        if m2:
            entries = json.loads(m2.group())
            return entries
    except json.JSONDecodeError:
        logger.debug("正则提取后 JSON 解析失败，尝试 json_repair 修复")

    # 第三步：使用 json_repair 修复
    try:
        repaired = repair_json(raw)
        p = json.loads(repaired)
        entries = p.get("entries", []) if isinstance(p, dict) else p
        if not entries and isinstance(p, dict):
            entries = next((v for v in p.values() if isinstance(v, list)), [])
        logger.info("json_repair 修复成功")
        return entries
    except Exception as e:
        logger.error("json_repair 修复失败: %s", e)

    # 第四步：修复失败，输出原结果日志便于排查
    logger.error("JSON 解析最终失败，原始 LLM 输出: %s", raw)
    return []
