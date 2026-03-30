import sqlite3
import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db.database import DB_PATH

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["match"])


class MatchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="用户文案")
    top_k: Optional[int] = Field(None, ge=1, le=50, description="向量初筛数量（可选）")
    top_n: Optional[int] = Field(None, ge=1, le=20, description="最终推荐数量（可选）")
    video_ids: Optional[List[str]] = Field(None, description="限定视频 ID 列表")


class ClipResult(BaseModel):
    clip_id: str
    video_id: str
    clip_path: str
    start_time: float
    end_time: float
    duration: float
    asr_text: Optional[str] = None
    vlm_description: Optional[str] = None
    score: float
    reason: str


class MatchResponse(BaseModel):
    query: str
    top_n: int
    recommended: List[ClipResult]
    candidates: List[ClipResult]


def _read_cfg(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


@router.post("/match", response_model=MatchResponse)
async def match_clips(req: MatchRequest):
    """
    三级匹配引擎：向量初筛 -> LLM 精排 -> 返回推荐
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据库连接失败: {e}")

    try:
        embed_base_url = _read_cfg(conn, "embedding_base_url", "https://api.openai.com/v1")
        embed_api_key  = _read_cfg(conn, "embedding_api_key", "")
        embed_model    = _read_cfg(conn, "embedding_model", "text-embedding-3-small")

        llm_base_url   = _read_cfg(conn, "llm_base_url", "https://api.openai.com/v1")
        llm_api_key    = _read_cfg(conn, "llm_api_key", "")
        llm_model      = _read_cfg(conn, "llm_model", "gpt-4o-mini")
        llm_temperature = float(_read_cfg(conn, "llm_temperature", "0.7"))
        llm_max_tokens  = int(_read_cfg(conn, "llm_max_tokens", "20480"))
        llm_max_context_tokens = int(_read_cfg(conn, "llm_max_context_tokens", "128000"))
        llm_concurrency = int(_read_cfg(conn, "llm_concurrency", "3"))

        vector_dim     = int(_read_cfg(conn, "vector_dimension", "1536"))
        top_k_cfg      = int(_read_cfg(conn, "match_top_k", "12"))
        top_n_cfg      = int(_read_cfg(conn, "match_top_n", "5"))

        top_k = req.top_k if req.top_k is not None else top_k_cfg
        top_n = req.top_n if req.top_n is not None else top_n_cfg

        if not embed_api_key:
            raise HTTPException(
                status_code=400,
                detail="Embedding API Key 未配置，请在设置页面填写 embedding_api_key"
            )
        if not llm_api_key:
            raise HTTPException(
                status_code=400,
                detail="LLM API Key 未配置，请在设置页面填写 llm_api_key"
            )

        # 初始化 Embedder
        from app.core.embedder import Embedder
        embedder = Embedder(base_url=embed_base_url, api_key=embed_api_key, model=embed_model)

        # 初始化向量数据库
        from app.core.vector_db.faiss_db import FaissVectorDB
        vector_db = FaissVectorDB(db_path=DB_PATH, vector_dimension=vector_dim)

        # 初始化 LLM（精排）
        from app.core.llm.openai_llm import OpenAILLM
        llm = OpenAILLM(base_url=llm_base_url, model=llm_model, api_key=llm_api_key)

        # 执行匹配
        from app.core.matcher import Matcher
        matcher = Matcher(embedder=embedder, vector_db=vector_db, llm=llm)

        result = matcher.match(
            query=req.query,
            db_conn=conn,
            top_k=top_k,
            top_n=top_n,
            video_ids=req.video_ids,
        )

        return MatchResponse(
            query=result["query"],
            top_n=result["top_n"],
            recommended=[ClipResult(**c) for c in result["recommended"]],
            candidates=[ClipResult(**c) for c in result["candidates"]],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("match_clips 异常: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"匹配失败: {str(e)}")
    finally:
        conn.close()
