import asyncio
import logging
import os
import sqlite3
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from app.models.match import MatchRequest, MatchResponse, ClipResult

from app.core.blocking_pool import run_heavy
from app.db.database import DB_PATH

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["match"])


def _read_cfg(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


class MatchPipelineError(Exception):
    """在线程池中执行匹配 pipeline 时使用的 HTTP 语义错误（避免在 worker 内抛 HTTPException）。"""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


def _match_clips_sync(req: MatchRequest, api_base_url: str) -> MatchResponse:
    """
    同步执行匹配（Embedding / FAISS / 同步 OpenAI 客户端），须在线程池中调用，
    避免阻塞 asyncio 事件循环导致其它接口（如视频流预览）饥饿。
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
    except Exception as e:
        raise MatchPipelineError(500, f"数据库连接失败: {e}") from e

    try:
        embed_base_url = _read_cfg(conn, "embedding_base_url", "https://api.openai.com/v1")
        embed_api_key = _read_cfg(conn, "embedding_api_key", "")
        embed_model = _read_cfg(conn, "embedding_model", "text-embedding-3-small")

        llm_base_url = _read_cfg(conn, "llm_base_url", "https://api.openai.com/v1")
        llm_api_key = _read_cfg(conn, "llm_api_key", "")
        llm_model = _read_cfg(conn, "llm_model", "gpt-4o-mini")
        llm_temperature = float(_read_cfg(conn, "llm_temperature", "0.7"))
        llm_max_tokens = int(_read_cfg(conn, "llm_max_tokens", "20480"))
        llm_max_context_tokens = int(_read_cfg(conn, "llm_max_context_tokens", "128000"))
        llm_concurrency = int(_read_cfg(conn, "llm_concurrency", "3"))

        vector_dim = int(_read_cfg(conn, "vector_dimension", "1024"))
        top_k_cfg = int(_read_cfg(conn, "match_top_k", "12"))
        top_n_cfg = int(_read_cfg(conn, "match_top_n", "5"))

        top_k = req.top_k if req.top_k is not None else top_k_cfg
        top_n = req.top_n if req.top_n is not None else top_n_cfg

        if not embed_api_key:
            raise MatchPipelineError(
                400,
                "Embedding API Key 未配置，请在设置页面填写 embedding_api_key",
            )
        if not llm_api_key:
            raise MatchPipelineError(
                400,
                "LLM API Key 未配置，请在设置页面填写 llm_api_key",
            )

        from app.core.embedder import Embedder
        embedder = Embedder(base_url=embed_base_url, api_key=embed_api_key, model=embed_model)

        from app.core.vector_db.faiss_db import FaissVectorDB
        vector_db = FaissVectorDB(db_path=DB_PATH, vector_dimension=vector_dim)

        from app.core.llm.openai_llm import OpenAILLM
        llm = OpenAILLM(base_url=llm_base_url, model=llm_model, api_key=llm_api_key)

        from app.core.matcher import Matcher
        matcher = Matcher(embedder=embedder, vector_db=vector_db, llm=llm)

        result = matcher.match(
            query=req.query,
            db_conn=conn,
            top_k=top_k,
            top_n=top_n,
            video_ids=req.video_ids,
            api_base_url=api_base_url,
        )

        return MatchResponse(
            query=result["query"],
            top_n=result["top_n"],
            recommended=[ClipResult(**c) for c in result["recommended"]],
            candidates=[ClipResult(**c) for c in result["candidates"]],
        )

    except MatchPipelineError:
        raise
    except Exception as e:
        logger.error("match_clips 异常: %s", e, exc_info=True)
        raise MatchPipelineError(500, f"匹配失败: {str(e)}") from e
    finally:
        conn.close()


@router.post("/match", response_model=MatchResponse)
async def match_clips(req: MatchRequest, request: Request):
    """
    三级匹配引擎：向量初筛 -> LLM 精排 -> 返回推荐
    """
    if await request.is_disconnected():
        raise HTTPException(status_code=400, detail="客户端已断开连接")
    api_base_url = str(request.base_url).rstrip("/")

    timeout_raw = (os.environ.get("SMARTCLIP_MATCH_TIMEOUT_SEC") or "").strip()
    timeout_sec = float(timeout_raw) if timeout_raw else 0.0

    async def _run() -> MatchResponse:
        return await run_heavy(_match_clips_sync, req, api_base_url)

    try:
        if timeout_sec > 0:
            return await asyncio.wait_for(_run(), timeout=timeout_sec)
        return await _run()
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="匹配处理超时，请稍后重试或缩小匹配范围",
        ) from None
    except asyncio.CancelledError:
        logger.warning(
            "match_clips 已取消（客户端断开或进程关停）；"
            "专用线程池中的匹配仍可能跑完，无法安全中断同步 OpenAI/FAISS"
        )
        raise
    except MatchPipelineError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
