from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Iterable

import aiosqlite
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.llm import LLMClient, LLMConfig
from app.core.llm.response_utils import extract_json_object
from app.db.database import DB_PATH
from app.models.summary import (
    SummaryGenerateRequest,
    SummaryTemplate,
    SummaryTemplateUpsertRequest,
    VideoSummary,
    VideoSummaryUpdateRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/summary", tags=["summary"])


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _fingerprint(parts: Iterable[str]) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8", errors="ignore"))
        h.update(b"\n---\n")
    return h.hexdigest()[:24]


def _chunk_text(text: str, *, max_chars: int, overlap_chars: int, max_chunks: int) -> list[str]:
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


def _fmt_time(s: float | None) -> str:
    if s is None:
        return "?:??"
    try:
        m, sec = divmod(int(float(s)), 60)
        return f"{m}:{sec:02d}"
    except Exception:
        return "?:??"


async def _load_template(db: aiosqlite.Connection, template_id: str) -> SummaryTemplate:
    cur = await db.execute(
        """
        SELECT id, name, description, system_prompt, user_prompt_template, output_schema_hint, created_at, updated_at
        FROM summary_templates
        WHERE id = ?
        """,
        (template_id,),
    )
    row = await cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"总结模板不存在: {template_id}")
    return SummaryTemplate(**dict(row))


async def _build_video_context(db: aiosqlite.Connection, *, video_id: str, mode: str) -> str:
    # 拉齐 clips，按 start_time 排序，保留可追溯信息
    cur = await db.execute(
        """
        SELECT c.id, c.start_time, c.end_time, c.asr_text, c.vlm_description
        FROM clips c
        WHERE c.video_id = ?
          AND (
            TRIM(COALESCE(c.asr_text, '')) <> ''
            OR TRIM(COALESCE(c.vlm_description, '')) <> ''
          )
        ORDER BY c.start_time
        """,
        (video_id,),
    )
    rows = await cur.fetchall()
    if not rows:
        return "（未找到有效的 ASR 或 VLM 识别内容）"

    lines: list[str] = [f"【video_id】{video_id}", "【内容片段】"]
    for r in rows:
        t0 = _fmt_time(r["start_time"])
        t1 = _fmt_time(r["end_time"])
        parts: list[str] = []
        if mode in ("asr", "asr_vlm"):
            asr = (r["asr_text"] or "").strip()
            if asr:
                parts.append(f"台词：{asr}")
        if mode in ("vlm", "asr_vlm"):
            vlm = (r["vlm_description"] or "").strip()
            if vlm:
                parts.append(f"画面：{vlm}")
        if not parts:
            continue
        lines.append(f"- [clip_id={r['id']}] [{t0}→{t1}] " + " | ".join(parts))
    return "\n".join(lines).strip()


def _render_vars(req: SummaryGenerateRequest) -> dict[str, Any]:
    return {
        "user_goal": (req.user_goal or "").strip(),
        "extra_instructions": (req.extra_instructions or "").strip(),
        **(req.prompt_vars or {}),
    }


def _apply_vars(template: str, vars_: dict[str, Any]) -> str:
    out = template or ""
    for k, v in vars_.items():
        token = "{{" + str(k) + "}}"
        out = out.replace(token, "" if v is None else str(v))
    return out


def _json_to_markdown(data: dict[str, Any]) -> str:
    title = str(data.get("title") or "").strip() or "视频总结"
    overview = str(data.get("overview") or "").strip()
    key_points = data.get("key_points") or []
    highlights = data.get("highlights") or []
    quotes = data.get("quotes") or []
    action_items = data.get("action_items") or []
    tags = data.get("tags") or []
    chapters = data.get("chapters") or []

    lines: list[str] = [f"## {title}"]
    if overview:
        lines += ["", "### 总览", overview]
    if isinstance(chapters, list) and chapters:
        lines.append("")
        lines.append("### 章节")
        for i, ch in enumerate(chapters, start=1):
            if not isinstance(ch, dict):
                continue
            ct = str(ch.get("title") or "").strip() or f"章节 {i}"
            cs = str(ch.get("summary") or "").strip()
            lines += ["", f"#### {ct}"]
            if cs:
                lines.append(cs)
            kp = ch.get("key_points") or []
            if isinstance(kp, list) and kp:
                lines.append("")
                lines.append("要点：")
                lines += [f"- {str(x)}" for x in kp if str(x).strip()]
            ev = ch.get("evidence") or []
            if isinstance(ev, list) and ev:
                lines.append("")
                lines.append("依据：")
                lines += [f"- {str(x)}" for x in ev if str(x).strip()]

    def _list_section(name: str, items: Any):
        if isinstance(items, list) and any(str(x).strip() for x in items):
            lines.append("")
            lines.append(f"### {name}")
            lines.extend([f"- {str(x)}" for x in items if str(x).strip()])

    _list_section("重点", key_points)
    _list_section("高光片段", highlights)
    _list_section("金句", quotes)
    _list_section("行动项", action_items)
    _list_section("标签", tags)
    return "\n".join(lines).strip() + "\n"


def _build_section_prompts(base_user_prompt: str, schema_hint: str, stage_a: list[dict[str, Any]]) -> dict[str, str]:
    stage_a_json = json.dumps(stage_a, ensure_ascii=False)
    common = (
        f"{base_user_prompt}\n\n"
        f"【schema_hint】\n{schema_hint}\n\n"
        "【输入来源】StageA 分段摘要（已做长文本切分）\n"
        f"{stage_a_json}\n\n"
    )
    return {
        "overview": common
        + (
            "请只输出 JSON：\n"
            "{\n"
            '  "title": "string",\n'
            '  "overview": "string",\n'
            '  "tags": ["string"]\n'
            "}\n"
        ),
        "chapters": common
        + (
            "请只输出 JSON：\n"
            "{\n"
            '  "chapters": [\n'
            "    {\n"
            '      "title": "string",\n'
            '      "summary": "string",\n'
            '      "key_points": ["string"],\n'
            '      "evidence": ["string"]\n'
            "    }\n"
            "  ]\n"
            "}\n"
        ),
        "highlights": common
        + (
            "请只输出 JSON：\n"
            "{\n"
            '  "key_points": ["string"],\n'
            '  "highlights": ["string"],\n'
            '  "quotes": ["string"],\n'
            '  "action_items": ["string"]\n'
            "}\n"
        ),
    }


def _merge_sections_to_final_json(
    *,
    overview_data: dict[str, Any],
    chapters_data: dict[str, Any],
    highlights_data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "title": str(overview_data.get("title") or "视频总结").strip() or "视频总结",
        "overview": str(overview_data.get("overview") or "").strip(),
        "chapters": chapters_data.get("chapters") if isinstance(chapters_data.get("chapters"), list) else [],
        "key_points": highlights_data.get("key_points") if isinstance(highlights_data.get("key_points"), list) else [],
        "highlights": highlights_data.get("highlights") if isinstance(highlights_data.get("highlights"), list) else [],
        "quotes": highlights_data.get("quotes") if isinstance(highlights_data.get("quotes"), list) else [],
        "action_items": highlights_data.get("action_items") if isinstance(highlights_data.get("action_items"), list) else [],
        "tags": overview_data.get("tags") if isinstance(overview_data.get("tags"), list) else [],
    }


async def _call_llm_json(llm: LLMClient, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
    raw = await llm.chat(messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}])
    cleaned = extract_json_object(raw if isinstance(raw, str) else "")
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error("summary json parse failed: %s", e)
        raise HTTPException(status_code=502, detail="LLM 返回 JSON 解析失败")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="LLM 返回 JSON 非对象")
    return data


def _get_section_content_map(rows: list[aiosqlite.Row]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = str(r["section_key"])
        raw = r["content_json"]
        try:
            out[key] = json.loads(raw) if raw else {}
        except Exception:
            out[key] = {}
    return out


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
    now = _now()
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
        tpl = await _load_template(db, tid)
        return tpl


@router.get("/videos/{video_id}/latest", response_model=VideoSummary | None)
async def get_latest_summary(video_id: str, template_id: str = "default_general", mode: str = "asr_vlm"):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
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
        row = await cur.fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get("summary_json"):
            try:
                d["summary_json"] = json.loads(d["summary_json"])
            except Exception:
                d["summary_json"] = None
        if d.get("prompt_snapshot_json"):
            try:
                d["prompt_snapshot_json"] = json.loads(d["prompt_snapshot_json"])
            except Exception:
                d["prompt_snapshot_json"] = None
        return VideoSummary(**d)


@router.get("/{summary_id}/sections")
async def get_summary_sections(summary_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT id, summary_id, section_key, status, content_json, content_markdown, created_at, updated_at
            FROM video_summary_sections
            WHERE summary_id = ?
            ORDER BY created_at ASC
            """,
            (summary_id,),
        )
        rows = await cur.fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            try:
                d["content_json"] = json.loads(d["content_json"]) if d.get("content_json") else None
            except Exception:
                d["content_json"] = None
            out.append(d)
        return {"summary_id": summary_id, "sections": out}


@router.post("/generate", response_model=VideoSummary)
async def generate_summary(req: SummaryGenerateRequest):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # 读取 LLM 配置与模板
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

        tpl = await _load_template(db, req.template_id)
        vars_ = _render_vars(req)

        context = await _build_video_context(db, video_id=req.video_id, mode=req.mode)
        context_chunks = _chunk_text(
            context,
            max_chars=req.chunk_max_chars,
            overlap_chars=req.chunk_overlap_chars,
            max_chunks=req.max_chunks,
        )
        if not context_chunks:
            raise HTTPException(status_code=400, detail="视频内容为空，无法总结（缺少 ASR/VLM）")

        llm = LLMClient(
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            model=cfg["model"],
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
            timeout=3600,
        )

        schema_hint = (tpl.output_schema_hint or "").strip()
        sys_prompt = tpl.system_prompt.strip()

        # StageA：分段摘要（JSON，但允许简化章节）
        stage_a: list[dict[str, Any]] = []
        for idx, chunk in enumerate(context_chunks, start=1):
            user_prompt = _apply_vars(
                tpl.user_prompt_template,
                {
                    **vars_,
                    "schema_hint": schema_hint,
                },
            )
            user = (
                f"{user_prompt}\n\n"
                f"【schema_hint】\n{schema_hint}\n\n"
                f"【阶段】StageA 分段摘要\n"
                f"【分段序号】{idx}/{len(context_chunks)}\n"
                "请只总结本分段内容，输出符合 schema 的 JSON，但 chapters 可以更少/更粗。\n\n"
                f"【本分段内容】\n{chunk}\n"
            )
            stage_a.append(await _call_llm_json(llm, system_prompt=sys_prompt, user_prompt=user))

        # StageB：分 section 生成（避免一次性生成过大）
        merge_user = _apply_vars(tpl.user_prompt_template, {**vars_, "schema_hint": schema_hint})
        section_prompts = _build_section_prompts(merge_user, schema_hint, stage_a)
        overview_data = await _call_llm_json(llm, system_prompt=sys_prompt, user_prompt=section_prompts["overview"])
        chapters_data = await _call_llm_json(llm, system_prompt=sys_prompt, user_prompt=section_prompts["chapters"])
        highlights_data = await _call_llm_json(llm, system_prompt=sys_prompt, user_prompt=section_prompts["highlights"])
        final_json = _merge_sections_to_final_json(
            overview_data=overview_data,
            chapters_data=chapters_data,
            highlights_data=highlights_data,
        )
        final_md = _json_to_markdown(final_json)

        now = _now()
        summary_id = f"sum_{uuid.uuid4().hex[:12]}"
        prompt_snapshot = {
            "template_id": tpl.id,
            "template_name": tpl.name,
            "system_prompt": sys_prompt,
            "user_prompt_template": tpl.user_prompt_template,
            "vars": vars_,
            "schema_hint": schema_hint,
            "mode": req.mode,
            "chunk_max_chars": req.chunk_max_chars,
            "chunk_overlap_chars": req.chunk_overlap_chars,
            "max_chunks": req.max_chunks,
        }
        fp = _fingerprint(
            [
                req.video_id,
                req.mode,
                tpl.id,
                json.dumps(vars_, ensure_ascii=False, sort_keys=True),
                context,
            ]
        )

        await db.execute(
            """
            INSERT INTO video_summaries
            (id, video_id, template_id, mode, status, input_fingerprint, summary_json, summary_markdown, prompt_snapshot_json, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                summary_id,
                req.video_id,
                tpl.id,
                req.mode,
                "done",
                fp,
                json.dumps(final_json, ensure_ascii=False),
                final_md,
                json.dumps(prompt_snapshot, ensure_ascii=False),
                now,
                now,
            ),
        )
        # 分 section 落库，便于后续“单章节重生/编辑”
        section_rows = [
            ("overview", overview_data),
            ("chapters", chapters_data),
            ("highlights", highlights_data),
        ]
        for skey, sjson in section_rows:
            await db.execute(
                """
                INSERT INTO video_summary_sections
                (id, summary_id, section_key, status, content_json, content_markdown, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    f"ssec_{uuid.uuid4().hex[:12]}",
                    summary_id,
                    skey,
                    "done",
                    json.dumps(sjson, ensure_ascii=False),
                    "",
                    now,
                    now,
                ),
            )
        await db.execute(
            """
            INSERT INTO video_summary_versions
            (id, summary_id, version, source, content_json, content_markdown, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                f"sumv_{uuid.uuid4().hex[:12]}",
                summary_id,
                1,
                "llm",
                json.dumps(final_json, ensure_ascii=False),
                final_md,
                now,
            ),
        )
        await db.commit()

        return VideoSummary(
            id=summary_id,
            video_id=req.video_id,
            template_id=tpl.id,
            mode=req.mode,
            status="done",
            input_fingerprint=fp,
            summary_json=final_json,
            summary_markdown=final_md,
            prompt_snapshot_json=prompt_snapshot,
            created_at=now,
            updated_at=now,
        )


@router.post("/generate-stream")
async def generate_summary_stream(req: SummaryGenerateRequest):
    async def _sse():
        try:
            yield ("data: " + json.dumps({"type": "status", "message": "开始准备总结..."}, ensure_ascii=False) + "\n\n").encode()
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
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

                tpl = await _load_template(db, req.template_id)
                vars_ = _render_vars(req)
                context = await _build_video_context(db, video_id=req.video_id, mode=req.mode)
                context_chunks = _chunk_text(
                    context,
                    max_chars=req.chunk_max_chars,
                    overlap_chars=req.chunk_overlap_chars,
                    max_chunks=req.max_chunks,
                )
                if not context_chunks:
                    raise HTTPException(status_code=400, detail="视频内容为空，无法总结（缺少 ASR/VLM）")

                llm = LLMClient(
                    base_url=cfg["base_url"],
                    api_key=cfg["api_key"],
                    model=cfg["model"],
                    temperature=cfg["temperature"],
                    max_tokens=cfg["max_tokens"],
                    timeout=3600,
                )
                schema_hint = (tpl.output_schema_hint or "").strip()
                sys_prompt = tpl.system_prompt.strip()

                # StageA
                stage_a: list[dict[str, Any]] = []
                for idx, chunk in enumerate(context_chunks, start=1):
                    yield ("data: " + json.dumps({"type": "status", "message": f"分段摘要 {idx}/{len(context_chunks)}"}, ensure_ascii=False) + "\n\n").encode()
                    user_prompt = _apply_vars(tpl.user_prompt_template, {**vars_, "schema_hint": schema_hint})
                    user = (
                        f"{user_prompt}\n\n"
                        f"【schema_hint】\n{schema_hint}\n\n"
                        f"【阶段】StageA 分段摘要\n"
                        f"【分段序号】{idx}/{len(context_chunks)}\n"
                        "请只总结本分段内容，输出符合 schema 的 JSON，但 chapters 可以更少/更粗。\n\n"
                        f"【本分段内容】\n{chunk}\n"
                    )
                    stage_a.append(await _call_llm_json(llm, system_prompt=sys_prompt, user_prompt=user))

                # StageB 分 section 逐步生成并实时回传
                merge_user = _apply_vars(tpl.user_prompt_template, {**vars_, "schema_hint": schema_hint})
                section_prompts = _build_section_prompts(merge_user, schema_hint, stage_a)

                yield ("data: " + json.dumps({"type": "status", "message": "生成总览..."}, ensure_ascii=False) + "\n\n").encode()
                overview_data = await _call_llm_json(llm, system_prompt=sys_prompt, user_prompt=section_prompts["overview"])
                yield ("data: " + json.dumps({"type": "section", "section_key": "overview", "content_json": overview_data}, ensure_ascii=False) + "\n\n").encode()

                yield ("data: " + json.dumps({"type": "status", "message": "生成章节..."}, ensure_ascii=False) + "\n\n").encode()
                chapters_data = await _call_llm_json(llm, system_prompt=sys_prompt, user_prompt=section_prompts["chapters"])
                yield ("data: " + json.dumps({"type": "section", "section_key": "chapters", "content_json": chapters_data}, ensure_ascii=False) + "\n\n").encode()

                yield ("data: " + json.dumps({"type": "status", "message": "生成重点与行动项..."}, ensure_ascii=False) + "\n\n").encode()
                highlights_data = await _call_llm_json(llm, system_prompt=sys_prompt, user_prompt=section_prompts["highlights"])
                yield ("data: " + json.dumps({"type": "section", "section_key": "highlights", "content_json": highlights_data}, ensure_ascii=False) + "\n\n").encode()

                final_json = _merge_sections_to_final_json(
                    overview_data=overview_data,
                    chapters_data=chapters_data,
                    highlights_data=highlights_data,
                )
                final_md = _json_to_markdown(final_json)
                yield ("data: " + json.dumps({"type": "markdown", "content": final_md}, ensure_ascii=False) + "\n\n").encode()

                now = _now()
                summary_id = f"sum_{uuid.uuid4().hex[:12]}"
                prompt_snapshot = {
                    "template_id": tpl.id,
                    "template_name": tpl.name,
                    "system_prompt": sys_prompt,
                    "user_prompt_template": tpl.user_prompt_template,
                    "vars": vars_,
                    "schema_hint": schema_hint,
                    "mode": req.mode,
                    "chunk_max_chars": req.chunk_max_chars,
                    "chunk_overlap_chars": req.chunk_overlap_chars,
                    "max_chunks": req.max_chunks,
                }
                fp = _fingerprint(
                    [req.video_id, req.mode, tpl.id, json.dumps(vars_, ensure_ascii=False, sort_keys=True), context]
                )
                await db.execute(
                    """
                    INSERT INTO video_summaries
                    (id, video_id, template_id, mode, status, input_fingerprint, summary_json, summary_markdown, prompt_snapshot_json, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        summary_id,
                        req.video_id,
                        tpl.id,
                        req.mode,
                        "done",
                        fp,
                        json.dumps(final_json, ensure_ascii=False),
                        final_md,
                        json.dumps(prompt_snapshot, ensure_ascii=False),
                        now,
                        now,
                    ),
                )
                for skey, sjson in [("overview", overview_data), ("chapters", chapters_data), ("highlights", highlights_data)]:
                    await db.execute(
                        """
                        INSERT INTO video_summary_sections
                        (id, summary_id, section_key, status, content_json, content_markdown, created_at, updated_at)
                        VALUES (?,?,?,?,?,?,?,?)
                        """,
                        (f"ssec_{uuid.uuid4().hex[:12]}", summary_id, skey, "done", json.dumps(sjson, ensure_ascii=False), "", now, now),
                    )
                await db.execute(
                    """
                    INSERT INTO video_summary_versions
                    (id, summary_id, version, source, content_json, content_markdown, created_at)
                    VALUES (?,?,?,?,?,?,?)
                    """,
                    (f"sumv_{uuid.uuid4().hex[:12]}", summary_id, 1, "llm", json.dumps(final_json, ensure_ascii=False), final_md, now),
                )
                await db.commit()
                payload = {
                    "id": summary_id,
                    "video_id": req.video_id,
                    "template_id": tpl.id,
                    "mode": req.mode,
                    "status": "done",
                    "input_fingerprint": fp,
                    "summary_json": final_json,
                    "summary_markdown": final_md,
                    "prompt_snapshot_json": prompt_snapshot,
                    "created_at": now,
                    "updated_at": now,
                }
                yield ("data: " + json.dumps({"type": "done", "summary": payload}, ensure_ascii=False) + "\n\n").encode()
                yield b"data: [DONE]\n\n"
        except Exception as e:
            logger.error("summary stream error: %s", e)
            yield ("data: " + json.dumps({"type": "error", "detail": str(e)}, ensure_ascii=False) + "\n\n").encode()

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{summary_id}/sections/{section_key}/regenerate")
async def regenerate_section(summary_id: str, section_key: str):
    if section_key not in {"overview", "chapters", "highlights"}:
        raise HTTPException(status_code=400, detail="仅支持重生 overview/chapters/highlights")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM video_summaries WHERE id = ?", (summary_id,))
        summary_row = await cur.fetchone()
        if not summary_row:
            raise HTTPException(status_code=404, detail="总结不存在")
        s = dict(summary_row)

        tpl = await _load_template(db, s["template_id"])
        mode = str(s.get("mode") or "asr_vlm")
        video_id = str(s.get("video_id") or "")

        # 尝试从快照恢复上下文参数；无则回退默认
        prompt_snapshot = {}
        try:
            prompt_snapshot = json.loads(s.get("prompt_snapshot_json") or "{}")
        except Exception:
            prompt_snapshot = {}
        vars_ = prompt_snapshot.get("vars") if isinstance(prompt_snapshot.get("vars"), dict) else {"user_goal": "通用视频总结", "extra_instructions": ""}
        chunk_max_chars = int(prompt_snapshot.get("chunk_max_chars") or 6000)
        chunk_overlap_chars = int(prompt_snapshot.get("chunk_overlap_chars") or 400)
        max_chunks = int(prompt_snapshot.get("max_chunks") or 30)

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

        context = await _build_video_context(db, video_id=video_id, mode=mode)
        context_chunks = _chunk_text(
            context,
            max_chars=chunk_max_chars,
            overlap_chars=chunk_overlap_chars,
            max_chunks=max_chunks,
        )
        if not context_chunks:
            raise HTTPException(status_code=400, detail="视频内容为空，无法重生 section")

        llm = LLMClient(
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            model=cfg["model"],
            temperature=cfg["temperature"],
            max_tokens=cfg["max_tokens"],
            timeout=3600,
        )
        schema_hint = (tpl.output_schema_hint or "").strip()
        sys_prompt = tpl.system_prompt.strip()
        user_prompt = _apply_vars(tpl.user_prompt_template, {**vars_, "schema_hint": schema_hint})

        stage_a: list[dict[str, Any]] = []
        for idx, chunk in enumerate(context_chunks, start=1):
            user = (
                f"{user_prompt}\n\n"
                f"【schema_hint】\n{schema_hint}\n\n"
                f"【阶段】StageA 分段摘要\n"
                f"【分段序号】{idx}/{len(context_chunks)}\n"
                "请只总结本分段内容，输出符合 schema 的 JSON，但 chapters 可以更少/更粗。\n\n"
                f"【本分段内容】\n{chunk}\n"
            )
            stage_a.append(await _call_llm_json(llm, system_prompt=sys_prompt, user_prompt=user))

        section_prompts = _build_section_prompts(user_prompt, schema_hint, stage_a)
        new_section_json = await _call_llm_json(llm, system_prompt=sys_prompt, user_prompt=section_prompts[section_key])

        # upsert section
        now = _now()
        cur_sec = await db.execute(
            "SELECT id FROM video_summary_sections WHERE summary_id = ? AND section_key = ? ORDER BY updated_at DESC LIMIT 1",
            (summary_id, section_key),
        )
        sec_row = await cur_sec.fetchone()
        if sec_row:
            await db.execute(
                "UPDATE video_summary_sections SET content_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(new_section_json, ensure_ascii=False), now, sec_row["id"]),
            )
        else:
            await db.execute(
                """
                INSERT INTO video_summary_sections
                (id, summary_id, section_key, status, content_json, content_markdown, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (f"ssec_{uuid.uuid4().hex[:12]}", summary_id, section_key, "done", json.dumps(new_section_json, ensure_ascii=False), "", now, now),
            )

        # 读取全部 section 并重建最终 markdown/json
        all_cur = await db.execute(
            """
            SELECT section_key, content_json
            FROM video_summary_sections
            WHERE summary_id = ?
            ORDER BY updated_at DESC
            """,
            (summary_id,),
        )
        all_rows = await all_cur.fetchall()
        section_map = _get_section_content_map(all_rows)
        final_json = _merge_sections_to_final_json(
            overview_data=section_map.get("overview", {}),
            chapters_data=section_map.get("chapters", {}),
            highlights_data=section_map.get("highlights", {}),
        )
        final_md = _json_to_markdown(final_json)

        await db.execute(
            "UPDATE video_summaries SET summary_json = ?, summary_markdown = ?, updated_at = ? WHERE id = ?",
            (json.dumps(final_json, ensure_ascii=False), final_md, now, summary_id),
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
            (f"sumv_{uuid.uuid4().hex[:12]}", summary_id, nextv, "llm", json.dumps(final_json, ensure_ascii=False), final_md, now),
        )
        await db.commit()
        return {
            "summary_id": summary_id,
            "section_key": section_key,
            "section_json": new_section_json,
            "summary_markdown": final_md,
            "summary_json": final_json,
            "updated_at": now,
        }


@router.patch("/{summary_id}", response_model=VideoSummary)
async def update_summary(summary_id: str, req: VideoSummaryUpdateRequest):
    now = _now()
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

        # 回读返回
        cur3 = await db.execute("SELECT * FROM video_summaries WHERE id = ?", (summary_id,))
        row3 = await cur3.fetchone()
        d = dict(row3)
        try:
            d["summary_json"] = json.loads(d["summary_json"]) if d.get("summary_json") else None
        except Exception:
            d["summary_json"] = None
        try:
            d["prompt_snapshot_json"] = json.loads(d["prompt_snapshot_json"]) if d.get("prompt_snapshot_json") else None
        except Exception:
            d["prompt_snapshot_json"] = None
        return VideoSummary(**d)

