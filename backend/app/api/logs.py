from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from app.utils.logging_utils import get_memory_log_handler, merge_log_items, query_file_logs


router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
async def list_logs(
    q: str | None = Query(default=None, description="关键字检索（匹配时间/级别/logger/message）"),
    limit: int = Query(default=800, ge=1, le=5000, description="返回最新日志条数（最多 5000）"),
    level: str | None = Query(default=None, description="级别过滤：DEBUG/INFO/WARNING/ERROR/CRITICAL"),
    source: Literal["memory", "file", "both"] = Query(
        default="both",
        description="memory=仅进程内缓冲；file=仅 app.log 落盘（含轮转）；both=合并去重（推荐）",
    ),
):
    if source == "memory":
        items = get_memory_log_handler().query(q=q, limit=limit, level=level)
    elif source == "file":
        items = query_file_logs(q=q, limit=limit, level=level)
    else:
        cap = min(5000, max(limit, limit * 4))
        mem = get_memory_log_handler().query(q=q, limit=cap, level=level)
        disk = query_file_logs(q=q, limit=cap, level=level)
        items = merge_log_items(mem, disk, limit)
    return {"items": items, "limit": limit, "q": q, "level": level, "source": source}

