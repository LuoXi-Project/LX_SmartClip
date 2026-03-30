"""字幕时间轴生成：规则法 & LLM 法，以及依赖的工具函数。"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request as _urllib
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 代理 & 配置读取
# ---------------------------------------------------------------------------

def get_proxy() -> str | None:
    """从系统代理设置中获取 HTTPS/HTTP 代理地址。"""
    p = _urllib.getproxies()
    return p.get("https") or p.get("http") or None


async def read_cfg(db, key: str, default: str = "") -> str:
    """从 config 表读取配置值。"""
    async with db.execute("SELECT value FROM config WHERE key = ?", (key,)) as c:
        row = await c.fetchone()
    return row[0] if row else default


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


# ---------------------------------------------------------------------------
# LLM 法时间轴
# ---------------------------------------------------------------------------

_LLM_SYS_PROMPT = (
    "你是专业的视频字幕时间轴生成器。根据文案和时长生成字幕时间轴，时间全局连续累加。\n"
    "规则: 1.不超出片段时长 2.超20字拆多条每条<=20字 3.每条0.3-6秒条间0.05秒 "
    '4.输出JSON:{"entries":[{"clip_id":"...","start":0.0,"end":2.5,"text":"..."}]} 5.只输出JSON'
)


async def llm_timeline(
    segments,
    durations: list[float],
    base_url: str,
    api_key: str,
    model: str,
) -> list:
    """
    调用 LLM 生成字幕时间轴。
    返回 [{clip_id, start, end, text}, ...]
    """
    info = []
    cum = 0.0
    for seg, dur in zip(segments, durations):
        info.append(f'clip_id={seg.clip_id} start={cum:.3f}s dur={dur:.3f}s text="{seg.copy_text}"')
        cum += dur
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _LLM_SYS_PROMPT},
            {"role": "user", "content": "生成时间轴:\n" + "\n".join(info)},
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
    }
    async with httpx.AsyncClient(timeout=60, proxy=get_proxy()) as c:
        r = await c.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
        )
    if r.status_code != 200:
        raise RuntimeError(f"LLM {r.status_code}: {r.text[:200]}")
    raw = r.json()["choices"][0]["message"]["content"]
    try:
        p = json.loads(raw)
        entries = p.get("entries", []) if isinstance(p, dict) else p
        if not entries and isinstance(p, dict):
            entries = next((v for v in p.values() if isinstance(v, list)), [])
    except json.JSONDecodeError:
        m2 = re.search(r"\[.*\]", raw, re.DOTALL)
        entries = json.loads(m2.group()) if m2 else []
    return entries
