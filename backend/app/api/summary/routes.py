"""视频总结 API：路由入口。"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

import aiosqlite
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.core.llm import LLMClient, LLMConfig
from app.db.database import DB_PATH
from app.models.smart_outline import (
    SmartOutlineBundle,
    SmartOutlineGenerateResponse,
)
from app.models.summary import (
    SummaryGenerateRequest,
    SummaryTemplate,
    SummaryTemplateUpsertRequest,
    VideoSummary,
    VideoSummaryUpdateRequest,
)

from .context import load_template
from .llm import call_llm_json
from .pipeline import (
    build_stage_a_user_message,
    build_stage_b_user_prompt,
    pipeline_stage_a_and_markdown,
    prepare_summary_context,
)
from .prompts import STAGE_A_SCHEMA_HINT, STAGE_A_SYSTEM, STAGE_B_SYSTEM
from .screenshots import cleanup_previous_summary_shots_for_video
from .smart_outline_store import fetch_saved_outline, generate_smart_outline_and_persist
from .store import parse_video_summary_row, persist_generated_summary
from .utils import now_iso, strip_markdown_fences

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/summary", tags=["summary"])


@router.get("/templates", response_model=list[SummaryTemplate])
async def list_templates():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, name, description, system_prompt, user_prompt_template, output_schema_hint, created_at, updated_at
            FROM summary_templates
            ORDER BY updated_at DESC
            """
        )
        rows = await cur.fetchall()
        return [SummaryTemplate(**dict(r)) for r in rows]


@router.post("/templates", response_model=SummaryTemplate)
async def upsert_template(req: SummaryTemplateUpsertRequest):
    tid = (req.id or "").strip() or f"tpl_{uuid.uuid4().hex[:10]}"
    now = now_iso()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """
            INSERT INTO summary_templates (id, name, description, system_prompt, user_prompt_template, output_schema_hint, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name,
              description=excluded.description,
              system_prompt=excluded.system_prompt,
              user_prompt_template=excluded.user_prompt_template,
              output_schema_hint=excluded.output_schema_hint,
              updated_at=excluded.updated_at
            """,
            (tid, req.name, req.description, req.system_prompt, req.user_prompt_template, req.output_schema_hint, now, now),
        )
        await db.commit()
        tpl = await load_template(db, tid)
        return tpl


@router.get("/videos/{video_id}/latest", response_model=VideoSummary | None)
async def get_latest_summary(
    video_id: str,
    template_id: Optional[str] = None,
    mode: str = "asr_vlm",
):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if template_id:
            cur = await db.execute(
                """
                SELECT *
                FROM video_summaries
                WHERE video_id = ? AND template_id = ? AND mode = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (video_id, template_id, mode),
            )
        else:
            cur = await db.execute(
                """
                SELECT *
                FROM video_summaries
                WHERE video_id = ? AND mode = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (video_id, mode),
            )
        row = await cur.fetchone()
        if not row:
            return None
        d = parse_video_summary_row(dict(row))
        return VideoSummary(**d)


@router.post("/generate", response_model=VideoSummary)
async def generate_summary(req: SummaryGenerateRequest):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await cleanup_previous_summary_shots_for_video(db, req.video_id, req.mode)
        try:
            cfg = await LLMConfig.get_llm_params_with_defaults(
                db,
                base_url_key="llm_base_url",
                api_key_key="llm_api_key",
                model_key="llm_model",
                fallback_model_key="vlm_model",
                default_temperature=0.3,
                default_max_tokens=20480,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        llm = LLMClient(
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            model=cfg["model"],
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
            timeout=3600,
        )

        final_md, summary_json_obj, vars_, context, _stage_b, schema_hint = await pipeline_stage_a_and_markdown(db, req, llm)

        return await persist_generated_summary(
            db,
            req=req,
            final_md=final_md,
            summary_json_obj=summary_json_obj,
            vars_=vars_,
            context=context,
            schema_hint=schema_hint,
        )


@router.post("/generate-stream")
async def generate_summary_stream(req: SummaryGenerateRequest):
    async def _sse():
        try:
            yield ("data: " + json.dumps({"type": "status", "message": "开始准备总结..."}, ensure_ascii=False) + "\n\n").encode()
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                await cleanup_previous_summary_shots_for_video(db, req.video_id, req.mode)
                try:
                    cfg = await LLMConfig.get_llm_params_with_defaults(
                        db,
                        base_url_key="llm_base_url",
                        api_key_key="llm_api_key",
                        model_key="llm_model",
                        fallback_model_key="vlm_model",
                        default_temperature=0.3,
                        default_max_tokens=20480,
                    )
                except ValueError as e:
                    raise HTTPException(status_code=400, detail=str(e))

                vars_, context, context_chunks = await prepare_summary_context(db, req)

                llm = LLMClient(
                    base_url=cfg["base_url"],
                    api_key=cfg["api_key"],
                    model=cfg["model"],
                    temperature=cfg["temperature"],
                    max_tokens=cfg["max_tokens"],
                    timeout=3600,
                )
                schema_hint = STAGE_A_SCHEMA_HINT
                sys_prompt = STAGE_A_SYSTEM

                stage_a: list = []
                total = len(context_chunks)
                for idx, chunk in enumerate(context_chunks, start=1):
                    yield (
                        "data: "
                        + json.dumps({"type": "status", "message": f"分段摘要 {idx}/{total}"}, ensure_ascii=False)
                        + "\n\n"
                    ).encode()
                    user = build_stage_a_user_message(req, schema_hint=schema_hint, chunk=chunk, idx=idx, total=total)
                    stage_a.append(await call_llm_json(llm, system_prompt=sys_prompt, user_prompt=user))

                yield ("data: " + json.dumps({"type": "status", "message": "生成完整 Markdown 笔记（流式）..."}, ensure_ascii=False) + "\n\n").encode()
                final_user = build_stage_b_user_prompt(
                    video_title=str(vars_.get("video_title") or ""),
                    tags=str(vars_.get("tags") or ""),
                    segment_text=str(vars_.get("segment_text") or ""),
                    user_style=(req.extra_instructions or "").strip(),
                    user_goal=(req.user_goal or "").strip(),
                    stage_a=stage_a,
                    prompt_vars=req.prompt_vars,
                )
                messages = [
                    {"role": "system", "content": STAGE_B_SYSTEM},
                    {"role": "user", "content": final_user},
                ]
                raw_accum = ""
                async for delta in llm.chat_stream(messages=messages):
                    raw_accum += delta
                    yield (
                        "data: "
                        + json.dumps({"type": "markdown", "content": raw_accum}, ensure_ascii=False)
                        + "\n\n"
                    ).encode()

                final_md = strip_markdown_fences(raw_accum.strip()).strip() + "\n"
                summary_json_obj: dict = {"format": "markdown_note_v1", "stage_a": stage_a}

                summary = await persist_generated_summary(
                    db,
                    req=req,
                    final_md=final_md,
                    summary_json_obj=summary_json_obj,
                    vars_=vars_,
                    context=context,
                    schema_hint=schema_hint,
                )
                payload = summary.model_dump()
                yield ("data: " + json.dumps({"type": "done", "summary": payload}, ensure_ascii=False) + "\n\n").encode()
                yield b"data: [DONE]\n\n"
        except HTTPException as e:
            logger.error("summary stream error: %s", e.detail)
            yield ("data: " + json.dumps({"type": "error", "detail": e.detail}, ensure_ascii=False) + "\n\n").encode()
        except Exception as e:
            logger.error("summary stream error: %s", e)
            yield ("data: " + json.dumps({"type": "error", "detail": str(e)}, ensure_ascii=False) + "\n\n").encode()

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.patch("/{summary_id}", response_model=VideoSummary)
async def update_summary(summary_id: str, req: VideoSummaryUpdateRequest):
    now = now_iso()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM video_summaries WHERE id = ?", (summary_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="总结不存在")

        old = dict(row)
        old_json = old.get("summary_json")
        old_md = old.get("summary_markdown")
        new_json_str = json.dumps(req.summary_json, ensure_ascii=False) if req.summary_json is not None else old_json
        new_md = req.summary_markdown if req.summary_markdown is not None else old_md

        await db.execute(
            "UPDATE video_summaries SET summary_json=?, summary_markdown=?, updated_at=? WHERE id=?",
            (new_json_str, new_md, now, summary_id),
        )

        cur2 = await db.execute("SELECT COALESCE(MAX(version), 0) FROM video_summary_versions WHERE summary_id = ?", (summary_id,))
        maxv = await cur2.fetchone()
        nextv = int(maxv[0] if maxv and maxv[0] is not None else 0) + 1
        await db.execute(
            """
            INSERT INTO video_summary_versions
            (id, summary_id, version, source, content_json, content_markdown, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                f"sumv_{uuid.uuid4().hex[:12]}",
                summary_id,
                nextv,
                req.source,
                new_json_str,
                new_md,
                now,
            ),
        )
        await db.commit()

        cur3 = await db.execute("SELECT * FROM video_summaries WHERE id = ?", (summary_id,))
        row3 = await cur3.fetchone()
        d = parse_video_summary_row(dict(row3))
        return VideoSummary(**d)


@router.get("/videos/{video_id}/smart-outline", response_model=SmartOutlineBundle)
async def get_smart_outline_bundle(video_id: str):
    """读取已保存的智能大纲（无记录时 outline 为 null）。"""
    vid = (video_id or "").strip()
    if not vid:
        raise HTTPException(status_code=400, detail="video_id 无效")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        got = await fetch_saved_outline(db, vid)
    if not got:
        return SmartOutlineBundle(outline=None, updated_at=None)
    outline, updated_at = got
    return SmartOutlineBundle(outline=outline, updated_at=updated_at)


@router.post("/videos/{video_id}/smart-outline/generate", response_model=SmartOutlineGenerateResponse)
async def generate_smart_outline_route(
    video_id: str,
    max_clips: int = Query(120, ge=1, le=200),
):
    """基于 ASR（主）+ 可选 VLM 生成智能大纲并写入 video_smart_outlines。"""
    response, updated = await generate_smart_outline_and_persist(
        (video_id or "").strip(),
        max_clips,
    )
    return SmartOutlineGenerateResponse(**response.model_dump(), updated_at=updated)
