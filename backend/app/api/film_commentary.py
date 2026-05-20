"""影视解说专区 API — 一键成片任务。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from app.api.process_db import get_video
from app.core.film_commentary.db import (
    create_job,
    get_job_row,
    list_jobs,
    row_to_job,
)
from app.core.film_commentary.pipeline import request_cancel, schedule_job
from app.models.film_commentary import (
    FilmCommentaryCreateRequest,
    FilmCommentaryJob,
    FilmCommentaryJobListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/film", tags=["film-commentary"])


@router.get("/jobs", response_model=FilmCommentaryJobListResponse)
async def list_film_jobs(limit: int = Query(30, ge=1, le=200)):
    rows = await list_jobs(limit=limit)
    items = [row_to_job(r) for r in rows]
    return FilmCommentaryJobListResponse(items=items, total=len(items))


@router.get("/jobs/{job_id}", response_model=FilmCommentaryJob)
async def get_film_job(job_id: str):
    row = await get_job_row(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    return row_to_job(row)


@router.post("/jobs", response_model=FilmCommentaryJob)
async def create_film_job(req: FilmCommentaryCreateRequest):
    video = await get_video(req.video_id)
    if not video:
        raise HTTPException(status_code=404, detail="视频不存在，请先在素材库上传")

    job_id = await create_job(
        video_id=req.video_id,
        mode=req.mode,
        style=req.style,
        target_duration_sec=req.target_duration_sec,
        auto_render=req.auto_render,
        include_subtitle=req.include_subtitle,
    )
    schedule_job(job_id)
    row = await get_job_row(job_id)
    return row_to_job(row)  # type: ignore[arg-type]


@router.post("/jobs/{job_id}/cancel")
async def cancel_film_job(job_id: str):
    row = await get_job_row(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    request_cancel(job_id)
    return {"ok": True, "job_id": job_id}


@router.post("/jobs/{job_id}/retry", response_model=FilmCommentaryJob)
async def retry_film_job(job_id: str):
    row = await get_job_row(job_id)
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    from app.core.film_commentary.db import update_job_fields

    await update_job_fields(job_id, status="pending", error_message=None, finished_at=None)
    schedule_job(job_id)
    row = await get_job_row(job_id)
    return row_to_job(row)  # type: ignore[arg-type]
