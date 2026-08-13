"""音频库 API 路由（音乐爬取 + 账号管理）。

仿 publish.py 范式。prefix=/api/audio-library。
职责：
- /status：功能就绪状态（浏览器引擎 + 各音乐源登录态摘要）
- /accounts：账号管理（列出/登录/校验/删除/改名）
- /search-preview：搜索歌曲预览（不下载）
- /download-batch：批量下载勾选歌曲到 BGM 库（异步任务）
- /tasks：任务（列出/详情/取消）
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException

from app.core.audio_library import _cookie as audio_cookie
from app.core.audio_library import login as audio_login
from app.core.audio_library.runner import (
    cancel as runner_cancel,
    is_running as runner_is_running,
    start_login_worker,
    start_worker,
)
from app.core.audio_library.types import (
    SOURCES,
    SOURCE_META,
    AudioTaskPayload,
    needs_login,
    source_label,
)
from app.core.publisher import _browser
from app.models.audio_library import (
    CheckLoginRequest,
    DownloadBatchRequest,
    LoginRequest,
    SearchPreviewRequest,
    UpdateAccountRequest,
)
from app.utils.paths import get_writable_backend_root

from . import audio_library_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/audio-library", tags=["audio-library"])


# ── 状态 ──────────────────────────────────────────────────────────────────
@router.get("/status")
async def get_status():
    """功能就绪状态：浏览器引擎 + 各音乐源元信息。"""
    browser_status = _browser.status_dict()
    sources_info = []
    for s in SOURCES:
        meta = SOURCE_META[s]
        has_logged = audio_cookie.has_account(s) if meta["needs_login"] else True
        sources_info.append({
            "source": s,
            "label": meta["label"],
            "needs_login": meta["needs_login"],
            "has_account": has_logged,
        })
    return {
        "ready": True,  # 爬取不强制需要浏览器（仅登录需要）；搜索/下载用 httpx
        "browser": browser_status,
        "sources": sources_info,
    }


# ── 账号 ──────────────────────────────────────────────────────────────────
@router.get("/accounts")
async def get_accounts(source: str | None = None):
    """列出账号（可按音乐源过滤）。

    合并 DB 记录与 cookie 文件实际存在性：cookie 文件为准（真实登录态），
    DB 补充 last_login_at 等元信息。酷我（免登录）返回 guest 占位。
    """
    target_sources = [source] if source else SOURCES
    db_accounts = {f"{a['source']}:{a['account']}": a for a in await audio_library_db.list_accounts()}

    result = []
    for s in target_sources:
        meta = SOURCE_META.get(s)
        if meta is None:
            continue
        if not meta["needs_login"]:
            # 酷我免登录：若无 DB 记录则返回 guest 占位
            db_accs = [a for a in db_accounts.values() if a["source"] == s]
            if not db_accs:
                result.append({
                    "source": s,
                    "account": "main",
                    "display_name": None,
                    "login_status": "guest",
                    "last_login_at": None,
                    "last_used_at": None,
                    "last_error": None,
                })
            else:
                for a in db_accs:
                    result.append({
                        "source": s, "account": a["account"],
                        "display_name": a.get("display_name"),
                        "login_status": "guest",
                        "last_login_at": a.get("last_login_at"),
                        "last_used_at": a.get("last_used_at"),
                        "last_error": a.get("last_error"),
                    })
            continue

        # 需登录源（netease）：以 cookie 文件为准
        for acc in audio_cookie.list_accounts(s):
            key = f"{s}:{acc['account']}"
            db_info = db_accounts.get(key, {})
            result.append({
                "source": s,
                "account": acc["account"],
                "login_status": db_info.get("login_status", "logged_in"),
                "display_name": db_info.get("display_name"),
                "last_login_at": db_info.get("last_login_at"),
                "last_used_at": db_info.get("last_used_at"),
                "last_error": db_info.get("last_error"),
            })
    return {"accounts": result}


@router.post("/accounts/{source}/login")
async def login_account(source: str, body: LoginRequest):
    """触发扫码登录（拉起可见浏览器子进程）。仅 netease。"""
    if not needs_login(source):
        raise HTTPException(status_code=400, detail=f"音乐源 {source}（{source_label(source)}）免登录，无需登录")
    if not _browser.is_ready():
        raise HTTPException(
            status_code=400,
            detail="浏览器引擎未就绪：未检测到本地 Chrome/Edge，且包内 Chromium 不可用",
        )

    account = body.account or "main"

    async def _on_complete(src, acc, success, log_tail):
        if success:
            existing = await audio_library_db.get_account(src, acc)
            existing_name = (existing or {}).get("display_name") if existing else None
            display_name = existing_name or f"{source_label(src)}-{acc}"
            await audio_library_db.upsert_account(
                source=src, account=acc, login_status="logged_in",
                display_name=display_name, last_error=None,
            )
        else:
            await audio_library_db.upsert_account(
                source=src, account=acc, login_status="expired",
                last_error=log_tail or "登录失败",
            )

    asyncio.create_task(start_login_worker(source, account, on_complete=_on_complete))
    return {"message": f"已启动 {source_label(source)} 登录流程，请在弹出的浏览器中登录", "account": account}


@router.post("/accounts/{source}/check")
async def check_account(source: str, body: CheckLoginRequest):
    """校验某账号登录态是否仍有效。"""
    if not needs_login(source):
        return {"source": source, "account": body.account or "main", "valid": True, "message": "免登录源"}
    account = body.account or "main"
    if not audio_cookie.has_account(source, account):
        return {"source": source, "account": account, "valid": False, "message": "未找到该账号 cookie"}
    try:
        valid = await audio_login.check_login(source, account)
    except Exception as exc:
        logger.exception("校验登录态异常")
        return {"source": source, "account": account, "valid": False, "message": f"校验异常: {exc}"}
    await audio_library_db.upsert_account(
        source=source, account=account,
        login_status="logged_in" if valid else "expired",
    )
    return {"source": source, "account": account, "valid": valid}


@router.delete("/accounts/{source}/{account}")
async def delete_account(source: str, account: str):
    """删除账号（清 cookie + DB 记录）。"""
    removed = audio_cookie.remove_account(source, account)
    await audio_library_db.delete_account(source, account)
    return {"removed": removed, "source": source, "account": account}


@router.patch("/accounts/{source}/{account}")
async def update_account(source: str, account: str, body: UpdateAccountRequest):
    """更新账号自定义显示名称。空串清除。"""
    name = body.display_name.strip()
    if not name:
        name = None
    updated = await audio_library_db.update_display_name(source, account, name)
    if not updated:
        raise HTTPException(status_code=404, detail=f"未找到账号 {source}/{account}")
    return {"source": source, "account": account, "display_name": name, "updated": True}


# ── 搜索 ──────────────────────────────────────────────────────────────────
@router.post("/search-preview")
async def search_preview(body: SearchPreviewRequest):
    """搜索预览：触发异步搜索任务，返回 task_id。

    前端用 task_id 轮询 /tasks/{task_id}，完成后从 result_json 读 songs。
    （搜索本身较快，但走子进程保持隔离一致。）
    """
    payload = AudioTaskPayload(
        task_id="",  # 由 DB 生成
        job_type="search",
        source=body.source,
        account=body.account,
        keyword=body.keyword,
        limit=body.limit,
        home_dir=str(get_writable_backend_root()),
    )
    task_id = await audio_library_db.create_task(
        job_type="search", source=body.source, account=body.account,
        payload_json=json.dumps(payload.to_dict(), ensure_ascii=False),
    )
    payload.task_id = task_id
    # 回写带 task_id 的 payload
    await audio_library_db.update_task(task_id, payload_json=json.dumps(payload.to_dict(), ensure_ascii=False))

    async def _on_progress(tid, prog):
        await audio_library_db.update_task(
            tid,
            progress_json=json.dumps(prog, ensure_ascii=False),
            log_append=(prog.get("message", "") + "\n") if prog.get("message") else None,
        )

    async def _on_complete(tid, status, result):
        await audio_library_db.update_task(
            tid, status=status,
            result_json=json.dumps(result, ensure_ascii=False) if result else None,
        )

    asyncio.create_task(start_worker(payload, on_progress=_on_progress, on_complete=_on_complete))
    return {"task_id": task_id, "message": "搜索任务已提交"}


# ── 下载 ──────────────────────────────────────────────────────────────────
@router.post("/download-batch")
async def download_batch(body: DownloadBatchRequest):
    """批量下载勾选歌曲到 BGM 库（异步任务）。"""
    payload = AudioTaskPayload(
        task_id="",
        job_type="download",
        source=body.source,
        account=body.account,
        songs=body.songs,
        home_dir=str(get_writable_backend_root()),
    )
    task_id = await audio_library_db.create_task(
        job_type="download", source=body.source, account=body.account,
        payload_json=json.dumps(payload.to_dict(), ensure_ascii=False),
    )
    payload.task_id = task_id
    await audio_library_db.update_task(task_id, payload_json=json.dumps(payload.to_dict(), ensure_ascii=False))
    # 标记账号已使用
    await audio_library_db.touch_account_used(body.source, body.account)

    async def _on_progress(tid, prog):
        await audio_library_db.update_task(
            tid,
            progress_json=json.dumps(prog, ensure_ascii=False),
            log_append=(prog.get("message", "") + "\n") if prog.get("message") else None,
        )

    async def _on_complete(tid, status, result):
        await audio_library_db.update_task(
            tid, status=status,
            result_json=json.dumps(result, ensure_ascii=False) if result else None,
        )

    asyncio.create_task(start_worker(payload, on_progress=_on_progress, on_complete=_on_complete))
    return {"task_id": task_id, "message": f"下载任务已提交，共 {len(body.songs)} 首"}


# ── 任务 ──────────────────────────────────────────────────────────────────
@router.get("/tasks")
async def list_tasks(limit: int = 50, offset: int = 0):
    rows = await audio_library_db.list_tasks(limit=limit, offset=offset)
    return {"tasks": rows}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    row = await audio_library_db.get_task(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    return row


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    if not runner_is_running(task_id):
        # 任务可能已结束，把状态标 cancelled 兜底
        row = await audio_library_db.get_task(task_id)
        if row and row["status"] in ("pending", "running"):
            await audio_library_db.update_task(task_id, status="cancelled")
        return {"cancelled": False, "message": "任务不在运行中"}
    ok = runner_cancel(task_id)
    if ok:
        await audio_library_db.update_task(task_id, status="cancelled")
    return {"cancelled": ok}
