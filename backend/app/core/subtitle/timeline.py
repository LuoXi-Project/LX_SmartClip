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

def resolve_durations(segments, clip_durations: dict, tts_audio_dir: str, use_tts: bool):
    """
    按优先级确定每个片段时长。
    优先使用 TTS 音频时长，回退至 clip 时长。
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
        if manual_v is not None and manual_v > 0:
            durs.append(manual_v)
            srcs.append("manual")
            continue
        if use_tts and seg.tts_filename:
            p = os.path.join(tts_audio_dir, os.path.basename(seg.tts_filename))
            d = audio_duration(p)
            if d > 0:
                durs.append(d)
                srcs.append("tts")
                logger.info("字幕时长[TTS] %s=%.3f秒", seg.tts_filename, d)
                continue
        durs.append(clip_durations.get(seg.clip_id, 5.0))
        srcs.append("clip")
    source = srcs[0] if len(set(srcs)) == 1 else "mixed"
    return durs, source


# ---------------------------------------------------------------------------
# 规则法时间轴
# ---------------------------------------------------------------------------

def rule_timeline(segments, durations: list[float], max_chars: int = 20) -> list:
    """
    基于规则将文案按字数均匀拆分到时间轴中。
    返回 [{clip_id, start, end, text}, ...]
    """
    entries = []
    t = 0.0
    for seg, dur in zip(segments, durations):
        text = seg.copy_text.strip()
        if not text:
            t += dur
            continue
        chunks = [text[i: i + max_chars] for i in range(0, len(text), max_chars)]
        cd = dur / len(chunks)
        ss = t
        for ci, chunk in enumerate(chunks):
            cs = ss + ci * cd
            ce = min(cs + max(cd - 0.05, 0.3), ss + dur - 0.05)
            entries.append(
                {"clip_id": seg.clip_id, "start": round(cs, 3), "end": round(ce, 3), "text": chunk}
            )
        t += dur
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


def rule_timeline_equal_units(segments, durations: list[float], max_chars: int = 20) -> list[dict]:
    """
    将每段文本切分为多个“单位”，并把该段的总时长平均分配到各单位。

    `max_chars` 用于对单位内容再做二次拆分，确保每条字幕文本尽量不超过该字符数。
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
            # 在“句子/换行单位”基础上按字符数继续拆分，保证字幕条数随长度约束增加。
            expanded_units: list[str] = []
            for u in units:
                u = (u or "").strip()
                if not u:
                    continue
                if len(u) <= max_chars:
                    expanded_units.append(u)
                else:
                    expanded_units.extend([u[i : i + max_chars] for i in range(0, len(u), max_chars)])
            units = expanded_units
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
