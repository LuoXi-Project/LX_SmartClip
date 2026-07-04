"""一键发布 API 路由。

仿 process.py 范式：APIRouter(prefix, tags) + pydantic schema + 直接抛 HTTPException。
职责：
- /status：功能就绪状态（浏览器引擎 + 各账号登录态摘要）
- /accounts：账号管理（列出/登录/校验/删除）
- /tasks：发布任务（创建/列出/详情/取消）
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.publisher import _browser
from app.core.publisher._cookie import has_account, list_accounts, remove_account
from app.core.publisher.runner import (
    cancel as runner_cancel,
    is_running as runner_is_running,
    start_login_worker,
    start_worker,
)
from app.core.publisher.types import (
    IMPLEMENTED_PLATFORMS,
    PLATFORM_META,
    PLATFORMS,
    PublishItem,
    PublishTaskPayload,
    is_implemented_platform,
)
from app.models.publish import (
    CheckLoginRequest,
    CreatePublishTaskRequest,
    LoginRequest,
    PublishItemRequest,
)
from app.utils.paths import get_writable_backend_root, resolve_stored_path

from . import publish_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/publish", tags=["publish"])


# ── 状态 ──────────────────────────────────────────────────────────────────
@router.get("/status")
async def get_status():
    """功能就绪状态：浏览器引擎命中情况 + 各平台元信息。"""
    browser_status = _browser.status_dict()
    platforms_info = []
    for p in PLATFORMS:
        meta = PLATFORM_META[p]
        has_logged = has_account(p)
        platforms_info.append({
            "platform": p,
            "label": meta["label"],
            "implemented": meta["implemented"],
            "risk": meta["risk"],
            "has_account": has_logged,
        })
    return {
        "ready": browser_status["ready"],
        "browser": browser_status,
        "platforms": platforms_info,
        "implemented_platforms": IMPLEMENTED_PLATFORMS,
    }


# ── 账号 ──────────────────────────────────────────────────────────────────
@router.get("/accounts")
async def get_accounts(platform: str | None = None):
    """列出账号（可按平台过滤）。

    合并 DB 记录与 cookie 文件实际存在性：以 cookie 文件为准（真实登录态），
    DB 记录补充 last_login_at 等元信息。
    """
    target_platforms = [platform] if platform else PLATFORMS
    db_accounts = {f"{a['platform']}:{a['account']}": a for a in await publish_db.list_accounts()}

    result = []
    for p in target_platforms:
        # 从 cookie 文件列真实账号
        for acc in list_accounts(p):
            key = f"{p}:{acc['account']}"
            db_info = db_accounts.get(key, {})
            result.append({
                "platform": p,
                "account": acc["account"],
                "login_status": db_info.get("login_status", "logged_in"),
                "display_name": db_info.get("display_name"),
                "last_login_at": db_info.get("last_login_at"),
                "last_used_at": db_info.get("last_used_at"),
                "last_error": db_info.get("last_error"),
            })
    return {"accounts": result}


@router.post("/accounts/{platform}/login")
async def login_account(platform: str, body: LoginRequest):
    """触发扫码登录（拉起可见浏览器子进程）。"""
    if not is_implemented_platform(platform):
        raise HTTPException(status_code=400, detail=f"平台 {platform} 暂未实现登录功能")
    if not _browser.is_ready():
        raise HTTPException(
            status_code=400,
            detail="浏览器引擎未就绪：未检测到本地 Chrome/Edge，且包内 Chromium 不可用",
        )

    account = body.account or "main"

    # 异步拉起登录子进程（不阻塞响应）
    async def _on_complete(p, acc, success, log_tail):
        if success:
            await publish_db.upsert_account(
                platform=p, account=acc, login_status="logged_in",
                display_name=f"{PLATFORM_META.get(p, {}).get('label', p)}-{acc}",
                last_error=None,  # 成功时清除历史错误
            )
        else:
            await publish_db.upsert_account(
                platform=p, account=acc, login_status="expired",
                last_error=log_tail or "登录失败",
            )

    asyncio.create_task(start_login_worker(platform, account, on_complete=_on_complete))

    return {"message": f"已启动 {platform} 登录流程，请在弹出的浏览器中扫码", "account": account}


@router.post("/accounts/{platform}/check")
async def check_account(platform: str, body: CheckLoginRequest):
    """校验某账号登录态是否仍有效（精确判定，会打开浏览器）。"""
    if not is_implemented_platform(platform):
        raise HTTPException(status_code=400, detail=f"平台 {platform} 暂未实现")
    account = body.account or "main"
    if not has_account(platform, account):
        return {"platform": platform, "account": account, "valid": False, "message": "未找到该账号 cookie"}

    # 各平台精确校验登录态
    try:
        if platform == "douyin":
            from app.core.publisher.douyin import douyin_check_login
            valid = await douyin_check_login(account)
        else:
            # 其余平台走通用校验
            from app.core.publisher import generic
            valid = await generic.check_login(platform, account)
    except Exception as exc:
        logger.exception("校验登录态异常")
        return {"platform": platform, "account": account, "valid": False, "message": f"校验异常: {exc}"}
    await publish_db.upsert_account(
        platform=platform, account=account,
        login_status="logged_in" if valid else "expired",
    )
    return {"platform": platform, "account": account, "valid": valid}


@router.delete("/accounts/{platform}/{account}")
async def delete_account(platform: str, account: str):
    """删除账号（清 cookie + DB 记录）。"""
    removed = remove_account(platform, account)
    await publish_db.delete_account(platform, account)
    return {"removed": removed, "platform": platform, "account": account}


# ── 任务 ──────────────────────────────────────────────────────────────────
@router.post("/tasks")
async def create_task(body: CreatePublishTaskRequest):
    """创建发布任务并拉起 worker 子进程。"""
    # 校验视频文件
    video_path = body.video_path
    try:
        video_path = str(resolve_stored_path(video_path))
    except Exception:
        pass  # 允许绝对路径直接用
    if not Path(video_path).is_file():
        raise HTTPException(status_code=400, detail=f"视频文件不存在: {video_path}")

    # 校验平台 + 账号登录态
    items_for_payload: list[PublishItem] = []
    for it in body.items:
        if not is_implemented_platform(it.platform):
            raise HTTPException(status_code=400, detail=f"平台 {it.platform} 暂未实现")
        if not has_account(it.platform, it.account):
            raise HTTPException(
                status_code=400,
                detail=f"平台 {it.platform} 账号 {it.account} 未登录，请先登录",
            )
        items_for_payload.append(PublishItem(
            platform=it.platform,
            account=it.account,
            title=it.title,
            description=it.description,
            tags=list(it.tags),
            cover_path=it.cover_path,
            publish_strategy=it.publish_strategy,
            publish_date=it.publish_date,
        ))

    # 落库
    items_json = json.dumps([it.to_dict() for it in items_for_payload], ensure_ascii=False)
    task_id = await publish_db.create_task(
        video_path=video_path,
        video_name=Path(video_path).name,
        items_json=items_json,
    )

    # 构造子进程载荷
    payload = PublishTaskPayload(
        task_id=task_id,
        video_path=video_path,
        items=items_for_payload,
        home_dir=str(get_writable_backend_root()),
    )

    # 进度/完成回调
    async def _on_progress(tid, prog):
        # prog 可能是进度行或普通 log
        await publish_db.update_task_status(tid, progress_json=json.dumps(prog, ensure_ascii=False))
        if "message" in prog:
            await publish_db.update_task_status(tid, log_append=prog.get("message", "") + "\n")
        elif prog.get("log"):
            await publish_db.update_task_status(tid, log_append=prog["log"] + "\n")

    async def _on_complete(tid, status, result):
        await publish_db.update_task_status(
            tid,
            status=status,
            result_json=json.dumps(result, ensure_ascii=False) if result else None,
            pid=None,
        )
        # 更新各账号 last_used_at
        for it in items_for_payload:
            await publish_db.touch_account_used(it.platform, it.account)

    # 异步拉起 worker（不阻塞响应）
    asyncio.create_task(start_worker(payload, on_progress=_on_progress, on_complete=_on_complete))

    return {"task_id": task_id, "status": "pending", "message": "任务已创建，正在执行"}


@router.get("/tasks")
async def list_tasks(limit: int = 50, offset: int = 0):
    """列任务（分页）。"""
    tasks = await publish_db.list_tasks(limit=limit, offset=offset)
    # 解析 JSON 字段为对象，方便前端用
    for t in tasks:
        for k in ("items_json", "progress_json", "result_json"):
            if t.get(k):
                try:
                    t[k] = json.loads(t[k])
                except Exception:
                    pass
    return {"tasks": tasks, "total": len(tasks)}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """任务详情（前端轮询用）。"""
    t = await publish_db.get_task(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 标记是否仍在运行
    t["running"] = runner_is_running(task_id)
    for k in ("items_json", "progress_json", "result_json"):
        if t.get(k):
            try:
                t[k] = json.loads(t[k])
            except Exception:
                pass
    return t


@router.delete("/tasks/{task_id}")
async def cancel_task(task_id: str):
    """取消任务。"""
    if not runner_is_running(task_id):
        # 进程已结束，仅更新状态
        await publish_db.update_task_status(task_id, status="cancelled")
        return {"cancelled": True, "message": "任务已结束，状态置为已取消"}
    ok = runner_cancel(task_id)
    if ok:
        await publish_db.update_task_status(task_id, status="cancelled")
    return {"cancelled": ok}
