from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, Set

from app.api.process_db import ProgressReporter, get_video
from app.api.process_pipeline import run_pipeline
from app.core.film_commentary.align import align_sentences_to_clips
from app.core.film_commentary.config_helpers import load_runtime_config
from app.core.film_commentary.db import (
    load_clips_for_video,
    row_to_job,
    update_job_fields,
    update_job_progress,
    get_job_row,
)
from app.core.film_commentary.plan_builder import build_plan_from_alignments
from app.core.film_commentary.render import render_plan_to_video
from app.core.film_commentary.screenplay import generate_screenplay
from app.core.film_commentary.summarize import summarize_clips

logger = logging.getLogger(__name__)

_cancel_events: Dict[str, asyncio.Event] = {}
_running_tasks: Dict[str, asyncio.Task] = {}


def request_cancel(job_id: str) -> None:
    ev = _cancel_events.get(job_id)
    if ev:
        ev.set()


def _check_cancel(job_id: str) -> None:
    ev = _cancel_events.get(job_id)
    if ev and ev.is_set():
        raise asyncio.CancelledError("任务已取消")


def _clips_pipeline_ready(clips: list, mode: str, vector_db) -> bool:
    if len(clips) < 2:
        return False
    asr_ok = sum(1 for c in clips if (c.get("asr_text") or "").strip()) >= max(2, len(clips) // 3)
    if not asr_ok:
        return False
    if mode == "precise":
        vlm_ok = sum(1 for c in clips if (c.get("vlm_description") or "").strip()) >= max(2, len(clips) // 4)
        if not vlm_ok:
            return False
    emb_ok = sum(1 for c in clips if vector_db.get_embedding(c["id"])) >= max(2, len(clips) // 3)
    return emb_ok


async def run_film_commentary_job(job_id: str) -> None:
    row = await get_job_row(job_id)
    if not row:
        return
    job = row_to_job(row)
    video_id = job.video_id
    mode = job.mode
    prompt_overrides: dict = {}
    raw_overrides = row.get("prompt_overrides_json")
    if raw_overrides:
        try:
            parsed = json.loads(raw_overrides)
            if isinstance(parsed, dict):
                prompt_overrides = parsed
        except Exception:
            prompt_overrides = {}
    _cancel_events[job_id] = asyncio.Event()

    try:
        video = await get_video(video_id)
        if not video:
            raise RuntimeError(f"视频不存在: {video_id}")

        runtime = await load_runtime_config()
        if not runtime.llm.api_key:
            raise RuntimeError("LLM API Key 未配置")
        if not getattr(runtime.embedder, "_api_key", ""):
            raise RuntimeError("Embedding API Key 未配置")

        # ── L1 解析 ──
        await update_job_fields(job_id, status="parsing", error_message=None)
        clips = await load_clips_for_video(video_id)
        if not _clips_pipeline_ready(clips, mode, runtime.vector_db):
            await update_job_progress(job_id, "parsing", "running", "正在理解原片（切片/识别/向量）…")
            skip = ["vlm"] if mode == "lightweight" else []
            reporter = ProgressReporter(ws=None, task_id=None)

            async def _run_parse():
                await run_pipeline(video_id, reporter, skip_steps=skip)

            await _run_parse()
            _check_cancel(job_id)
            clips = await load_clips_for_video(video_id)
            if not clips:
                raise RuntimeError("切片为空，请检查素材或处理配置")

        await update_job_progress(job_id, "parsing", "done", f"已就绪 {len(clips)} 个镜头")
        _check_cancel(job_id)

        # ── L2 摘要 ──
        await update_job_fields(job_id, status="scripting")
        await update_job_progress(job_id, "summarize", "running", "正在精炼剧情摘要…")
        summaries = await summarize_clips(
            llm=runtime.llm,
            clips=clips,
            mode=mode,
            system_prompt=prompt_overrides.get("summarize_system_prompt"),
        )
        await update_job_fields(
            job_id,
            clip_summaries_json=json.dumps(summaries, ensure_ascii=False),
        )
        await update_job_progress(job_id, "summarize", "done", f"完成 {len(summaries)} 段摘要")
        _check_cancel(job_id)

        # ── L3 编剧 ──
        await update_job_progress(job_id, "screenplay", "running", "正在撰写解说剧本…")
        storyline, sentences = await generate_screenplay(
            llm=runtime.llm,
            summaries=summaries,
            video_name=video.get("name") or "",
            style=job.style,
            target_duration_sec=job.target_duration_sec,
            system_prompt=prompt_overrides.get("screenplay_system_prompt"),
            user_prompt_template=prompt_overrides.get("screenplay_user_prompt_template"),
        )
        if not sentences:
            raise RuntimeError("解说文案生成为空")
        await update_job_fields(
            job_id,
            storyline_json=json.dumps(storyline, ensure_ascii=False),
            sentences_json=json.dumps([s.model_dump() for s in sentences], ensure_ascii=False),
        )
        await update_job_progress(job_id, "screenplay", "done", f"共 {len(sentences)} 句解说")
        _check_cancel(job_id)

        # ── L4 对齐 ──
        await update_job_fields(job_id, status="aligning")
        await update_job_progress(job_id, "align", "running", "正在匹配画面…")
        alignments = await align_sentences_to_clips(
            sentences=sentences,
            clips=clips,
            video_id=video_id,
            embedder=runtime.embedder,
            vector_db=runtime.vector_db,
            top_k=runtime.match_top_k,
        )
        if not alignments:
            raise RuntimeError("分句对齐失败，无可用镜头")
        await update_job_fields(
            job_id,
            alignments_json=json.dumps([a.model_dump() for a in alignments], ensure_ascii=False),
        )
        await update_job_progress(job_id, "align", "done", f"已对齐 {len(alignments)} 句")
        _check_cancel(job_id)

        # ── L5 方案 ──
        await update_job_fields(job_id, status="planning")
        await update_job_progress(job_id, "plan", "running", "正在生成剪辑方案…")
        plan = build_plan_from_alignments(
            video_id=video_id,
            video_name=video.get("name") or "影视解说",
            sentences=sentences,
            alignments=alignments,
            target_duration_sec=job.target_duration_sec,
            storyline=storyline,
        )
        await update_job_fields(
            job_id,
            plan_json=plan.model_dump_json(),
        )
        await update_job_progress(job_id, "plan", "done", f"方案 {len(plan.segments)} 段")
        _check_cancel(job_id)

        output_url = None
        output_path = None
        if job.auto_render:
            await update_job_fields(job_id, status="rendering")
            await update_job_progress(job_id, "render", "running", "正在 TTS 配音并合成成片…")
            fname, url = await render_plan_to_video(
                plan=plan,
                project_name=f"film_{video_id[:8]}",
                include_subtitle=job.include_subtitle,
            )
            output_path = fname
            output_url = url
            await update_job_progress(job_id, "render", "done", "成片已生成")

        from app.core.film_commentary.db import _now

        await update_job_fields(
            job_id,
            status="done",
            output_path=output_path,
            output_url=output_url,
            finished_at=_now(),
        )
        # 记录成片到 renders 表（异步，不阻塞）
        if output_url:
            asyncio.create_task(_record_film(output_url, video_id, video.get("name"), job, plan))
        logger.info("影视解说任务完成: %s", job_id)

    except asyncio.CancelledError:
        from app.core.film_commentary.db import _now

        await update_job_fields(
            job_id,
            status="cancelled",
            error_message="用户取消",
            finished_at=_now(),
        )
    except Exception as e:
        logger.exception("影视解说任务失败 %s: %s", job_id, e)
        from app.core.film_commentary.db import _now

        await update_job_fields(
            job_id,
            status="failed",
            error_message=str(e),
            finished_at=_now(),
        )
    finally:
        _cancel_events.pop(job_id, None)
        _running_tasks.pop(job_id, None)


def schedule_job(job_id: str) -> None:
    if job_id in _running_tasks and not _running_tasks[job_id].done():
        return
    task = asyncio.create_task(run_film_commentary_job(job_id))
    _running_tasks[job_id] = task


async def _record_film(
    public_url: str,
    material_id: str | None,
    material_title: str | None = None,
    job=None,
    plan=None,
) -> None:
    """把影视解说成片记录到 renders 表。

    携带原素材标题（video.name）与方案/方案内容快照（job.mode/style/target_duration
    + plan.storyline/sentences），供「一键发布」AI 文案生成时无需回查原任务即可拿到上下文。
    """
    try:
        from app.api.renders_db import record_render_from_path, extract_plan_snapshot
        from app.utils.paths import resolve_stored_path
        abs_path = resolve_stored_path(public_url)
        # 合并 job（mode/style/target_duration）与 plan（storyline/sentences）快照
        snap = extract_plan_snapshot(job) or {}
        plan_snap = extract_plan_snapshot(plan) or {}
        for k, v in plan_snap.items():
            snap.setdefault(k, v)
        plan_json = None
        if snap:
            plan_json = json.dumps(snap, ensure_ascii=False)
        await record_render_from_path(
            abs_path=abs_path, source="film_commentary", material_id=material_id,
            material_title=material_title, plan_json=plan_json,
        )
    except Exception:
        logger.debug("记录影视解说成片失败（忽略）", exc_info=True)
