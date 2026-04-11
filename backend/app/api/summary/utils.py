"""视频总结：纯工具函数（时间、分块、指纹、提示变量）。"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Iterable

from app.models.summary import SummaryGenerateRequest


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def fingerprint(parts: Iterable[str]) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8", errors="ignore"))
        h.update(b"\n---\n")
    return h.hexdigest()[:24]


def chunk_text(text: str, *, max_chars: int, overlap_chars: int, max_chunks: int) -> list[str]:
    s = (text or "").strip()
    if not s:
        return []
    if max_chars <= 0:
        return [s]
    out: list[str] = []
    i = 0
    n = len(s)
    step = max(1, max_chars - max(0, overlap_chars))
    while i < n and len(out) < max_chunks:
        out.append(s[i : min(n, i + max_chars)])
        i += step
    return out


def fmt_time(s: float | None) -> str:
    if s is None:
        return "?:??"
    try:
        m, sec = divmod(int(float(s)), 60)
        return f"{m}:{sec:02d}"
    except Exception:
        return "?:??"


def render_prompt_vars(req: SummaryGenerateRequest) -> dict[str, Any]:
    return {
        "user_goal": (req.user_goal or "").strip(),
        "extra_instructions": (req.extra_instructions or "").strip(),
        **(req.prompt_vars or {}),
    }


def prompt_var_bool(pv: dict[str, Any] | None, key: str, default: bool = True) -> bool:
    if not pv or key not in pv:
        return default
    v = pv.get(key)
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("1", "true", "yes", "on")
    return bool(v)


def note_options_instructions(prompt_vars: dict[str, Any] | None) -> str:
    pv = prompt_vars or {}
    lines: list[str] = []
    if prompt_var_bool(pv, "note_toc", True):
        lines.append(
            "- **目录**：文首生成目录（TOC），链接到各主要 `##` / `###` 标题。"
        )
    else:
        lines.append("- **目录**：请勿在文首生成目录（TOC）。")

    if prompt_var_bool(pv, "note_time_jump", True):
        lines.append(
            "- **原片跳转**：使用 `[mm:ss](video-time:秒数)`，秒为从片头起的整数秒；可与 `*Content-[mm:ss]` 一致。"
        )
    else:
        lines.append("- **原片跳转**：请勿使用 `[mm:ss](video-time:…)` 或可点击时间链接。")

    if prompt_var_bool(pv, "note_screenshot", True):
        lines.append("- **原片截图位**：需要时使用 `*Screenshot-[mm:ss]`。")
    else:
        lines.append("- **原片截图位**：请勿输出 `*Screenshot-[mm:ss]`。")

    if prompt_var_bool(pv, "note_ai_summary", True):
        lines.append("- **AI 总结**：文末可加简短整片中文小结。")
    else:
        lines.append("- **AI 总结**：请勿单独写整段「AI Summary」。")

    return "【笔记版式（用户开关）】\n" + "\n".join(lines)


def strip_markdown_fences(raw: str) -> str:
    s = (raw or "").strip()
    if not s.startswith("```"):
        return s
    lines = s.split("\n")
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
