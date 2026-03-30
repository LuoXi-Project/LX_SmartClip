"""SRT 时间轴工具函数：时间格式化、构建、解析。"""
from __future__ import annotations

import re


def srt_time(s: float) -> str:
    """将秒数转换为 SRT 时间戳格式 HH:MM:SS,mmm。"""
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    sec, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def build_srt(entries: list) -> str:
    """从 entries 列表构建 SRT 字符串。每个 entry 含 start/end/text。"""
    out = []
    for i, e in enumerate(entries, 1):
        out += [str(i), f"{srt_time(e['start'])} --> {srt_time(e['end'])}", e["text"].strip(), ""]
    return "\n".join(out)


def parse_srt(srt: str) -> list:
    """解析 SRT 字符串，返回 [{start, end, text}, ...] 列表。"""
    entries = []
    for block in re.split(r"\n\s*\n", srt.strip()):
        ls = block.strip().splitlines()
        if len(ls) < 3:
            continue
        m = re.match(
            r"(\d+):(\d+):(\d+)[,\.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,\.](\d+)",
            ls[1].strip(),
        )
        if not m:
            continue

        def ts(h, mi, s, ms):
            return int(h) * 3600 + int(mi) * 60 + int(s) + int(ms) / 1000

        entries.append(
            {
                "start": ts(*m.group(1, 2, 3, 4)),
                "end": ts(*m.group(5, 6, 7, 8)),
                "text": " ".join(ls[2:]),
            }
        )
    return entries
