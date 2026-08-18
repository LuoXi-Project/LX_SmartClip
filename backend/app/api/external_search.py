"""外部平台关键词采集：抖音 / YouTube 搜索预览 + 自动采集任务（下载→入库→预处理）。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.core.license import ensure_license_valid, is_license_enforced
from app.jobs import create_job, launch_job
from app.models.external_search import (
    DouyinLoginStatusResponse,
    ExternalSearchIngestRequest,
    ExternalSearchIngestResponse,
    ExternalSearchPreviewRequest,
    ExternalSearchPreviewResponse,
    ExternalSearchResultItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/external-search", tags=["external-search"])


async def _ensure_license() -> None:
    if is_license_enforced() and not await ensure_license_valid():
        raise HTTPException(status_code=403, detail="LICENSE_REQUIRED")


@router.get("/douyin/login-status", response_model=DouyinLoginStatusResponse)
async def douyin_login_status():
    """抖音搜索登录态：优先采集专用扫码登录，回退发布模块 cookie。"""
    from app.core.external_search.douyin import SEARCH_ACCOUNT, preferred_cookie_file
    from app.core.publisher._cookie import list_accounts

    accounts = [a["account"] for a in list_accounts("douyin")]
    cookie_file = preferred_cookie_file()
    if cookie_file is not None:
        source = "专用登录态" if cookie_file.stem == SEARCH_ACCOUNT else "复用一键发布的登录态"
        message = f"抖音登录态已就绪（{source}；主站搜索建议使用专用扫码登录）"
    else:
        message = "未找到抖音登录态：请点击「登录抖音」扫码，或仅使用 YouTube 平台"
    return DouyinLoginStatusResponse(
        cookie_ready=cookie_file is not None,
        message=message,
        accounts=accounts,
    )


@router.post("/douyin/login", response_model=ExternalSearchIngestResponse)
async def douyin_login():
    """打开可见浏览器供用户在抖音主站扫码登录（后台任务，SSE 跟踪进度）。"""
    await _ensure_license()
    from app.core.external_search.douyin import login_douyin_search

    job = await create_job(
        kind="douyin_login",
        ref_type="douyin",
        ref_id=None,
        ref_name="抖音扫码登录（关键词采集）",
        initial_step="login_open",
    )
    job_id = job["id"]

    async def _run():
        from app.jobs import JobReporter, update_job_status

        reporter = JobReporter(job_id)

        async def _on_stage(stage: str, message: str) -> None:
            status = "done" if stage == "login_done" else ("error" if stage == "login_error" else "running")
            await reporter.send(stage, status, message, {})

        try:
            ok = await login_douyin_search(on_stage=_on_stage)
            if ok:
                await update_job_status(job_id, "done", result={"logged_in": True})
            else:
                await update_job_status(job_id, "error", error_message="抖音登录未完成")
        except Exception as exc:
            logger.exception("抖音登录任务异常")
            await update_job_status(job_id, "error", error_message=str(exc))

    launch_job(job_id, _run())
    return ExternalSearchIngestResponse(
        job_id=job_id,
        status=job.get("status") or "running",
        stream_url=f"/api/jobs/{job_id}/stream",
    )


@router.post("/search-preview", response_model=ExternalSearchPreviewResponse)
async def search_preview(req: ExternalSearchPreviewRequest):
    """只搜索不下载：返回各平台结果卡片（供前端勾选后走 ingest selected 模式）。"""
    await _ensure_license()
    from app.core.external_search.ingest import read_ingest_config, search_platforms

    keywords = list(req.keywords)
    extraction = None
    if not keywords and req.copy_text.strip():
        if not req.extract_keywords:
            keywords = [req.copy_text.strip()[:40]]
            extraction = {"method": "fallback", "reason": "未启用 AI 提取"}
        else:
            from app.core.external_search.ingest import extract_keywords_from_copy

            keywords, method, reason = await extract_keywords_from_copy(req.copy_text)
            extraction = {"method": method, "reason": reason}
    if not keywords:
        raise HTTPException(status_code=400, detail="keywords 与 copy_text 至少提供一项")

    cfg = await read_ingest_config()
    results, notes = await search_platforms(
        keywords,
        list(req.platforms) or ["douyin"],
        req.limit_per_keyword,
        cfg,
    )
    return ExternalSearchPreviewResponse(
        keywords=keywords,
        results=[ExternalSearchResultItem(**r.to_payload()) for r in results],
        notes=notes,
        extraction=extraction,
    )


@router.post("/ingest", response_model=ExternalSearchIngestResponse)
async def start_ingest(req: ExternalSearchIngestRequest):
    """创建自动采集后台任务（搜索→下载→入库→自动进预处理队列）。"""
    await _ensure_license()
    from app.core.external_search.ingest import IngestParams, run_ingest_job

    if req.selected_items:
        keywords_hint = f"预览勾选 {len(req.selected_items)} 个目标"
    elif req.keywords:
        keywords_hint = "、".join(req.keywords[:3]) + ("…" if len(req.keywords) > 3 else "")
    elif req.copy_text.strip():
        keywords_hint = "文案：" + req.copy_text.strip()[:24] + "…"
    else:
        raise HTTPException(status_code=400, detail="keywords / copy_text / selected_items 至少提供一项")

    params = IngestParams(
        keywords=list(req.keywords),
        copy_text=req.copy_text,
        platforms=list(req.platforms) or ["douyin"],
        limit_per_keyword=req.limit_per_keyword or 0,
        resolution=req.resolution or "",
        auto_process=req.auto_process,
        selected_items=[it.model_dump() for it in (req.selected_items or [])],
    )

    job = await create_job(
        kind="external_ingest",
        ref_type="keyword",
        ref_id=None,
        ref_name=keywords_hint,
        initial_step="keywords",
    )
    launch_job(job["id"], run_ingest_job(job["id"], params))
    return ExternalSearchIngestResponse(
        job_id=job["id"],
        status=job.get("status") or "running",
        stream_url=f"/api/jobs/{job['id']}/stream",
    )
