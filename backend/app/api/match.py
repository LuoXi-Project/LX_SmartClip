import asyncio
import logging
import os
import sqlite3
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from app.models.match import MatchRequest, MatchResponse, ClipResult, VALID_SUBSPACES

from app.core.blocking_pool import run_heavy
from app.core.matcher import Matcher, resolve_match_mode
from app.db.database import DB_PATH
from app.utils.logging_utils import stage_log

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


def _validate_mode_requirements(
    mode: str,
    *,
    embed_api_key: str,
    llm_api_key: str,
) -> None:
    if mode == "vector" and not embed_api_key:
        raise MatchPipelineError(
            400,
            "当前为「向量匹配」模式，请在设置页配置 embedding_api_key，或切换为文本/纯 LLM 模式",
        )
    if mode == "llm_only" and not llm_api_key:
        raise MatchPipelineError(
            400,
            "当前为「纯 LLM 匹配」模式，请在设置页配置 llm_api_key",
        )
    if mode == "text" and not llm_api_key:
        logger.info("[Match] 文本匹配模式未配置 LLM，将仅使用 ASR/VLM 文本相似度排序")
    if mode == "vector" and not llm_api_key:
        logger.info("[Match] 向量匹配模式未配置 LLM，将仅使用向量相似度排序")


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
        # 子空间合法性校验（仅 vector 模式生效，但提前校验避免无效值穿透）
        if req.subspaces:
            invalid = [s for s in req.subspaces if s not in VALID_SUBSPACES]
            if invalid:
                raise MatchPipelineError(400, f"subspaces 含非法值 {invalid}，允许: {sorted(VALID_SUBSPACES)}")
        # 优先用请求级覆盖，其次全局配置
        match_mode_cfg = (req.match_mode or "").strip().lower() or _read_cfg(conn, "match_mode", "auto")

        embed_base_url = _read_cfg(conn, "embedding_base_url", "https://api.openai.com/v1")
        embed_api_key = _read_cfg(conn, "embedding_api_key", "")
        embed_model = _read_cfg(conn, "embedding_model", "text-embedding-3-small")

        llm_base_url = _read_cfg(conn, "llm_base_url", "https://api.openai.com/v1")
        llm_api_key = _read_cfg(conn, "llm_api_key", "")
        llm_model = _read_cfg(conn, "llm_model", "gpt-4o-mini")

        vector_dim = int(_read_cfg(conn, "vector_dimension", "1024"))
        top_k_cfg = int(_read_cfg(conn, "match_top_k", "12"))
        top_n_cfg = int(_read_cfg(conn, "match_top_n", "5"))

        top_k = req.top_k if req.top_k is not None else top_k_cfg
        top_n = req.top_n if req.top_n is not None else top_n_cfg

        # P2 阈值过滤：低于阈值的候选不进「推荐」（candidates 仍全量返回）。0 = 不过滤。
        try:
            min_llm_score = float(_read_cfg(conn, "match_min_llm_score", "0"))
        except (TypeError, ValueError):
            min_llm_score = 0.0
        try:
            min_similarity = float(_read_cfg(conn, "match_min_similarity", "0"))
        except (TypeError, ValueError):
            min_similarity = 0.0

        embedder = None
        vector_db = None
        has_vectors = False

        if embed_api_key:
            from app.core.embedder import Embedder
            from app.core.vector_db.faiss_db import FaissVectorDB

            embedder = Embedder(
                base_url=embed_base_url,
                api_key=embed_api_key,
                model=embed_model,
                volc_output_dimensions=vector_dim,
            )
            vector_db = FaissVectorDB(db_path=DB_PATH, vector_dimension=vector_dim)
            has_vectors = vector_db.embedding_count() > 0

        llm = None
        if llm_api_key:
            from app.core.llm.openai_llm import OpenAILLM

            llm = OpenAILLM(base_url=llm_base_url, model=llm_model, api_key=llm_api_key)

        effective_mode = resolve_match_mode(
            match_mode_cfg,
            has_embed_key=bool(embed_api_key),
            has_vectors=has_vectors,
            has_llm_key=bool(llm_api_key),
        )
        _validate_mode_requirements(
            effective_mode,
            embed_api_key=embed_api_key,
            llm_api_key=llm_api_key,
        )

        if effective_mode == "vector" and not has_vectors:
            logger.warning("[Match] 向量模式但索引为空，降级为文本匹配")
            effective_mode = "text"

        logger.info(
            "[Match] 配置=%s 生效=%s embed=%s vectors=%s llm=%s",
            match_mode_cfg,
            effective_mode,
            bool(embed_api_key),
            has_vectors,
            bool(llm_api_key),
        )

        matcher = Matcher(embedder=embedder, vector_db=vector_db, llm=llm)

        result = matcher.match(
            query=req.query,
            db_conn=conn,
            top_k=top_k,
            top_n=top_n,
            video_ids=req.video_ids,
            api_base_url=api_base_url,
            mode=effective_mode,
            min_llm_score=min_llm_score,
            min_similarity=min_similarity,
            refine=req.refine,
            subspaces=req.subspaces,
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
    素材匹配：向量 / 文本 / 纯 LLM（由设置页 match_mode 控制）
    """
    if await request.is_disconnected():
        raise HTTPException(status_code=400, detail="客户端已断开连接")
    api_base_url = str(request.base_url).rstrip("/")
    scope = f"{len(req.video_ids)} 个视频" if req.video_ids else "全部视频"
    stage_log(
        "检索",
        f"素材匹配开始：「{(req.query or '')[:60]}」范围={scope} top_k={req.top_k} top_n={req.top_n}",
        status="running",
    )

    timeout_raw = (os.environ.get("SMARTCLIP_MATCH_TIMEOUT_SEC") or "").strip()
    timeout_sec = float(timeout_raw) if timeout_raw else 0.0

    async def _run() -> MatchResponse:
        return await run_heavy(_match_clips_sync, req, api_base_url)

    try:
        if timeout_sec > 0:
            result = await asyncio.wait_for(_run(), timeout=timeout_sec)
        else:
            result = await _run()
        stage_log(
            "检索",
            f"素材匹配完成：推荐 {len(result.recommended)} 条，候选 {len(result.candidates)} 条",
            status="done",
        )
        return result
    except asyncio.TimeoutError:
        stage_log("检索", "素材匹配超时", status="error")
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
