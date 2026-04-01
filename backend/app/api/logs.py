from __future__ import annotations

from fastapi import APIRouter, Query

from app.utils.logging_utils import get_memory_log_handler


router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
async def list_logs(
    q: str | None = Query(default=None, description="关键字检索（匹配时间/级别/logger/message）"),
    limit: int = Query(default=200, ge=1, le=5000, description="返回最新日志条数（最多 5000）"),
    level: str | None = Query(default=None, description="级别过滤：DEBUG/INFO/WARNING/ERROR/CRITICAL"),
):
    h = get_memory_log_handler()
    items = h.query(q=q, limit=limit, level=level)
    return {"items": items, "limit": limit, "q": q, "level": level}

