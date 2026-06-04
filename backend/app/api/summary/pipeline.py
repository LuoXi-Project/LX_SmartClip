"""视频总结：StageA / StageB 流水线编排。"""

from __future__ import annotations

import json
from typing import Any

import aiosqlite
from fastapi import HTTPException

from app.core.llm import LLMClient
from app.utils.logging_utils import stage_log
from app.models.summary import SummaryGenerateRequest

from .context import build_video_context, prompt_extra_vars
from .llm import call_llm_json, call_llm_markdown
from .prompts import (
    BASE_PROMPT,
    MERGE_PROMPT,
    PROMPT_AI_SUM,
    PROMPT_LINK,
    PROMPT_SCREENSHOT,
    PROMPT_TOC,
    STAGE_A_SCHEMA_HINT,
    STAGE_A_SYSTEM,
    STAGE_B_SYSTEM,
)
from .utils import (
    chunk_text,
    note_options_instructions,
    prompt_var_bool,
    render_prompt_vars,
)


def fill_base_prompt(*, video_title: str, tags: str, segment_text: str) -> str:
    return (
        BASE_PROMPT.replace("{video_title}", video_title)
        .replace("{tags}", tags)
        .replace("{segment_text}", segment_text)
    )


def build_stage_b_user_prompt(
    *,
    video_title: str,
    tags: str,
    segment_text: str,
    user_style: str,
    user_goal: str,
    stage_a: list[dict[str, Any]],
    prompt_vars: dict[str, Any] | None,
) -> str:
    base = fill_base_prompt(video_title=video_title, tags=tags, segment_text=segment_text)
    style_parts: list[str] = []
    ug = (user_goal or "").strip()
    if ug:
        style_parts.append(f"【用户目标】\n{ug}")
    st = (user_style or "").strip()
    if st:
        style_parts.append(st)
    else:
        style_parts.append("（用户未填写额外风格说明：按默认结构与详略输出即可。）")
    style_block = "\n\n".join(style_parts)

    extras: list[str] = []
    if prompt_var_bool(prompt_vars, "note_toc", True):
        extras.append(PROMPT_TOC)
    if prompt_var_bool(prompt_vars, "note_screenshot", True):
        extras.append(PROMPT_SCREENSHOT)
    if prompt_var_bool(prompt_vars, "note_time_jump", True):
        extras.append(PROMPT_LINK)
    if prompt_var_bool(prompt_vars, "note_ai_summary", True):
        extras.append(PROMPT_AI_SUM)

    stage_a_json = json.dumps(stage_a, ensure_ascii=False)
    tail = (
        f"\n\n{note_options_instructions(prompt_vars)}\n\n"
        f"【StageA 分段 JSON】\n{stage_a_json}\n\n"
        f"{MERGE_PROMPT}\n"
    )
    return f"{base}\n{style_block}\n\n" + ("\n\n".join(extras) + "\n\n" if extras else "") + tail


def build_stage_a_user_message(
    req: SummaryGenerateRequest,
    *,
    schema_hint: str,
    chunk: str,
    idx: int,
    total: int,
) -> str:
    goal_block = ""
    if (req.user_goal or "").strip():
        goal_block = f"【用户目标】\n{(req.user_goal or '').strip()}\n\n"
    style_block = ""
    if (req.extra_instructions or "").strip():
        style_block = f"【笔记风格/额外约束】\n{(req.extra_instructions or '').strip()}\n\n"
    return (
        f"{goal_block}{style_block}"
        f"【schema_hint】\n{schema_hint}\n\n"
        f"【阶段】StageA 分段摘要\n"
        f"【分段序号】{idx}/{total}\n"
        "请只总结本分段内容，输出符合 schema 的 JSON，但 chapters 可以更少/更粗。\n\n"
        f"【本分段内容】\n{chunk}\n"
    )


async def prepare_summary_context(
    db: aiosqlite.Connection, req: SummaryGenerateRequest
) -> tuple[dict[str, Any], str, list[str]]:
    """加载 vars、全文 context、分块列表；无有效内容时抛出 400。"""
    extra = await prompt_extra_vars(db, video_id=req.video_id, mode=req.mode)
    vars_: dict[str, Any] = {**render_prompt_vars(req), **extra}
    context = await build_video_context(db, video_id=req.video_id, mode=req.mode)
    context_chunks = chunk_text(
        context,
        max_chars=req.chunk_max_chars,
        overlap_chars=req.chunk_overlap_chars,
        max_chunks=req.max_chunks,
    )
    if not context_chunks:
        raise HTTPException(status_code=400, detail="视频内容为空，无法总结（缺少 ASR/VLM）")
    stage_log(
        "总结",
        f"上下文已就绪：mode={req.mode}，分 {len(context_chunks)} 段，约 {len(context)} 字",
        status="running",
    )
    return vars_, context, context_chunks


async def run_stage_a_chunks(
    llm: LLMClient,
    req: SummaryGenerateRequest,
    *,
    context_chunks: list[str],
    schema_hint: str,
    sys_prompt: str,
) -> list[dict[str, Any]]:
    stage_a: list[dict[str, Any]] = []
    total = len(context_chunks)
    stage_log("总结", f"StageA 分段摘要开始，共 {total} 段", status="running")
    for idx, chunk in enumerate(context_chunks, start=1):
        stage_log("总结", f"StageA 正在处理第 {idx}/{total} 段…", status="running")
        user = build_stage_a_user_message(req, schema_hint=schema_hint, chunk=chunk, idx=idx, total=total)
        stage_a.append(await call_llm_json(llm, system_prompt=sys_prompt, user_prompt=user))
    stage_log("总结", f"StageA 分段摘要完成，共 {len(stage_a)} 段结果", status="done")
    return stage_a


async def pipeline_stage_a_and_markdown(
    db: aiosqlite.Connection,
    req: SummaryGenerateRequest,
    llm: LLMClient,
) -> tuple[str, dict[str, Any], dict[str, Any], str, str, str]:
    """返回 final_md, summary_json_obj, vars_, context, stage_b_system, stage_a_schema_hint"""
    stage_log("总结", f"开始生成视频总结 video_id={req.video_id} mode={req.mode}", status="running")
    vars_, context, context_chunks = await prepare_summary_context(db, req)

    schema_hint = STAGE_A_SCHEMA_HINT
    sys_prompt = STAGE_A_SYSTEM

    stage_a = await run_stage_a_chunks(llm, req, context_chunks=context_chunks, schema_hint=schema_hint, sys_prompt=sys_prompt)

    stage_log("总结", "StageB 正在合并为完整 Markdown 笔记…", status="running")
    final_user = build_stage_b_user_prompt(
        video_title=str(vars_.get("video_title") or ""),
        tags=str(vars_.get("tags") or ""),
        segment_text=str(vars_.get("segment_text") or ""),
        user_style=(req.extra_instructions or "").strip(),
        user_goal=(req.user_goal or "").strip(),
        stage_a=stage_a,
        prompt_vars=req.prompt_vars,
    )
    final_md = await call_llm_markdown(llm, system_prompt=STAGE_B_SYSTEM, user_prompt=final_user)
    stage_log("总结", f"StageB 完成，笔记约 {len(final_md)} 字", status="done")
    summary_json_obj: dict[str, Any] = {
        "format": "markdown_note_v1",
        "stage_a": stage_a,
    }
    return final_md, summary_json_obj, vars_, context, STAGE_B_SYSTEM, STAGE_A_SCHEMA_HINT
