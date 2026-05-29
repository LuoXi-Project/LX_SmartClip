"""视频总结页：基于笔记 / 大纲的内容问答。"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import aiosqlite
from fastapi import HTTPException

from app.core.llm import LLMClient, LLMConfig
from app.db.database import DB_PATH
from app.models.summary import SummaryAskRequest, SummaryAskSource

from .smart_outline_store import fetch_saved_outline

logger = logging.getLogger(__name__)

ASK_SYSTEM = """你是「视频内容问答助手」。你只能依据用户提供的视频笔记和/或智能大纲作答。

规则：
1. 只使用提供的参考资料；若材料中无相关信息，明确说明「根据现有笔记/大纲无法确定」，不要编造。
2. 使用简体中文，条理清晰；可用 Markdown（列表、加粗等）提升可读性。
3. 涉及时间、片段、话题时，尽量引用原文中的时间锚点或标题。
4. 可帮用户：查找细节、解释概念、对比段落、梳理结构、提炼要点、回答理解类问题。
5. 不要假装看过原视频画面；你的知识边界就是下方参考资料。"""

_MAX_CONTEXT_CHARS = 28000
_MAX_HISTORY_TURNS = 10


def _truncate(text: str, *, max_chars: int) -> str:
    s = (text or "").strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 20].rstrip() + "\n\n…（内容已截断）"


async def _load_video_title(db: aiosqlite.Connection, video_id: str) -> str:
    cur = await db.execute("SELECT name FROM videos WHERE id = ?", (video_id,))
    row = await cur.fetchone()
    if not row:
        return video_id
    return str(row["name"] or video_id).strip() or video_id


async def _load_latest_note_markdown(db: aiosqlite.Connection, video_id: str) -> Optional[str]:
    cur = await db.execute(
        """
        SELECT summary_markdown
        FROM video_summaries
        WHERE video_id = ?
          AND TRIM(COALESCE(summary_markdown, '')) <> ''
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (video_id,),
    )
    row = await cur.fetchone()
    if not row:
        return None
    md = (row["summary_markdown"] or "").strip()
    return md or None


def _outline_to_context(outline: Any) -> str:
    lines: list[str] = []
    title = getattr(outline, "video_title", None) or ""
    if title:
        lines.append(f"视频标题：{title}")
    md = (getattr(outline, "outline_markdown", None) or "").strip()
    if md:
        lines.append("【大纲正文】\n" + md)
    topics = getattr(outline, "topics", None) or []
    if topics:
        lines.append("【话题时间点】")
        for t in topics:
            title_t = getattr(t, "title", "") or ""
            start = getattr(t, "start_sec", 0)
            end = getattr(t, "end_sec", 0)
            summary = (getattr(t, "summary", None) or "").strip()
            line = f"- {title_t} [{start:.1f}s ~ {end:.1f}s]"
            if summary:
                line += f"：{summary}"
            lines.append(line)
    clip_scores = getattr(outline, "clip_scores", None) or []
    if clip_scores:
        top = sorted(clip_scores, key=lambda c: float(getattr(c, "excitement", 0) or 0), reverse=True)[:12]
        lines.append("【精彩片段评分（节选）】")
        for c in top:
            cid = getattr(c, "clip_id", "")
            exc = float(getattr(c, "excitement", 0) or 0)
            reason = (getattr(c, "reason", None) or "").strip()
            line = f"- clip {cid} 精彩度 {exc:.2f}"
            if reason:
                line += f"：{reason}"
            lines.append(line)
    return "\n".join(lines).strip()


async def build_ask_context(
    db: aiosqlite.Connection,
    *,
    video_id: str,
    source: SummaryAskSource,
) -> tuple[str, str, dict[str, bool]]:
    """返回 (system_context_block, video_title, availability)。"""
    video_title = await _load_video_title(db, video_id)
    has_note = False
    has_outline = False
    blocks: list[str] = [f"【视频】{video_title}（video_id={video_id}）"]

    if source in ("note", "both"):
        note_md = await _load_latest_note_markdown(db, video_id)
        if note_md:
            has_note = True
            blocks.append("【视频笔记】\n" + _truncate(note_md, max_chars=_MAX_CONTEXT_CHARS // 2))

    if source in ("outline", "both"):
        got = await fetch_saved_outline(db, video_id)
        if got:
            outline, _ = got
            outline_text = _outline_to_context(outline)
            if outline_text:
                has_outline = True
                blocks.append("【智能大纲】\n" + _truncate(outline_text, max_chars=_MAX_CONTEXT_CHARS // 2))

    context = _truncate("\n\n".join(blocks), max_chars=_MAX_CONTEXT_CHARS)
    return context, video_title, {"note": has_note, "outline": has_outline}


def _validate_source_available(source: SummaryAskSource, availability: dict[str, bool]) -> None:
    if source == "note" and not availability.get("note"):
        raise HTTPException(status_code=400, detail="当前视频暂无笔记，请先生成笔记或切换为「大纲/综合」")
    if source == "outline" and not availability.get("outline"):
        raise HTTPException(status_code=400, detail="当前视频暂无智能大纲，请先生成大纲或切换为「笔记/综合」")
    if source == "both" and not availability.get("note") and not availability.get("outline"):
        raise HTTPException(status_code=400, detail="当前视频暂无笔记和大纲，请至少生成其中一项后再提问")


def _build_messages(
    *,
    context_block: str,
    question: str,
    history: list[dict[str, str]],
) -> list[dict[str, str]]:
    system_content = ASK_SYSTEM + "\n\n---\n参考资料如下：\n\n" + context_block
    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]
    for item in history[-_MAX_HISTORY_TURNS * 2 :]:
        role = item.get("role", "")
        content = (item.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": question.strip()})
    return messages


async def stream_summary_ask(video_id: str, req: SummaryAskRequest):
    """生成 SSE 字节流。"""
    vid = (video_id or "").strip()
    if not vid:
        raise HTTPException(status_code=400, detail="video_id 无效")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        context_block, _, availability = await build_ask_context(db, video_id=vid, source=req.source)
        _validate_source_available(req.source, availability)
        try:
            cfg = await LLMConfig.get_llm_params_with_defaults(
                db,
                base_url_key="llm_base_url",
                api_key_key="llm_api_key",
                model_key="llm_model",
                fallback_model_key="vlm_model",
                default_temperature=0.4,
                default_max_tokens=4096,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    history = [{"role": m.role, "content": m.content} for m in req.history]
    messages = _build_messages(context_block=context_block, question=req.question, history=history)

    llm = LLMClient(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        temperature=cfg["temperature"],
        max_tokens=cfg["max_tokens"],
        timeout=600,
    )

    async def _sse():
        try:
            yield (
                "data: "
                + json.dumps(
                    {"type": "status", "message": "正在根据参考资料思考…", "availability": availability},
                    ensure_ascii=False,
                )
                + "\n\n"
            ).encode()
            accumulated = ""
            async for delta in llm.chat_stream(messages=messages):
                accumulated += delta
                yield (
                    "data: "
                    + json.dumps({"type": "content", "content": accumulated}, ensure_ascii=False)
                    + "\n\n"
                ).encode()
            yield ("data: " + json.dumps({"type": "done"}, ensure_ascii=False) + "\n\n").encode()
            yield b"data: [DONE]\n\n"
        except HTTPException as e:
            logger.error("summary ask stream error: %s", e.detail)
            yield ("data: " + json.dumps({"type": "error", "detail": e.detail}, ensure_ascii=False) + "\n\n").encode()
        except Exception as e:
            logger.error("summary ask stream error: %s", e)
            yield ("data: " + json.dumps({"type": "error", "detail": str(e)}, ensure_ascii=False) + "\n\n").encode()

    return _sse()
