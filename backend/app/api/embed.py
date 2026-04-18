import logging
import asyncio
from typing import Optional, Tuple

from fastapi import APIRouter, HTTPException

from app.core.embedder import Embedder
from app.core.vector_db.faiss_db import FaissVectorDB
from app.db.database import DB_PATH, get_db_conn

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["embed"])

# 单例（base_url / key / model / vector_dimension 变化时重建）
_embedder = None
_embedder_sig: Optional[Tuple[str, str, str, int]] = None
_vector_db = None
_vector_db_dim: Optional[int] = None


async def _get_embedder_and_db():
    """从配置读取参数，返回 Embedder 和 VectorDB 实例"""
    global _embedder, _embedder_sig, _vector_db, _vector_db_dim

    db = await get_db_conn()
    try:
        async def get_cfg(key, default=""):
            cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
            row = await cursor.fetchone()
            return row["value"] if row else default

        api_key = await get_cfg("embedding_api_key")
        base_url = await get_cfg("embedding_base_url", "https://api.openai.com/v1")
        model = await get_cfg("embedding_model", "text-embedding-3-small")
        dimension = int(await get_cfg("vector_dimension", "1024"))
        concurrency_raw = await get_cfg("embedding_concurrency", "3")
    finally:
        await db.close()

    def _parse_positive_int(raw: str, default: int, min_v: int = 1, max_v: int = 64) -> int:
        try:
            v = int(str(raw or "").strip())
        except Exception:
            v = default
        v = max(min_v, v)
        v = min(max_v, v)
        return v

    concurrency = _parse_positive_int(concurrency_raw, default=3, min_v=1, max_v=16)

    if not api_key:
        raise HTTPException(status_code=400, detail="Embedding API Key 未配置，请在设置页面配置 embedding_api_key")

    sig: Tuple[str, str, str, int] = (base_url or "", api_key or "", model or "", dimension)
    if _embedder is None or _embedder_sig != sig:
        _embedder = Embedder(
            base_url=base_url,
            api_key=api_key,
            model=model,
            volc_output_dimensions=dimension,
        )
        _embedder_sig = sig

    if _vector_db is None or _vector_db_dim != dimension:
        _vector_db = FaissVectorDB(db_path=DB_PATH, vector_dimension=dimension)
        _vector_db_dim = dimension

    return _embedder, _vector_db, concurrency


@router.post("/{video_id}/process-embed")
async def process_embed(video_id: str):
    """
    为视频所有片段生成 Embedding 并入库。
    拼接 asr_text + vlm_description 作为文本输入。
    """
    db = await get_db_conn()
    try:
        cursor = await db.execute("SELECT id FROM videos WHERE id = ?", (video_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")

        cursor = await db.execute(
            "SELECT id, asr_text, vlm_description FROM clips WHERE video_id = ? ORDER BY start_time",
            (video_id,),
        )
        clips = await cursor.fetchall()

        if not clips:
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 没有片段")
    except HTTPException:
        raise
    finally:
        await db.close()

    embedder, vector_db, concurrency = await _get_embedder_and_db()

    results = []
    logger.info("开始处理 %d 个片段的 Embedding (concurrency=%d)", len(clips), concurrency)

    sem = asyncio.Semaphore(concurrency)
    add_lock = asyncio.Lock()

    async def _process_one(idx: int, clip_row):
        clip_id = clip_row["id"]
        asr_text = clip_row["asr_text"] or ""
        vlm_desc = clip_row["vlm_description"] or ""
        text = (asr_text + " " + vlm_desc).strip()

        if not text:
            logger.warning("片段 %s 没有文本内容，跳过", clip_id)
            return {"clip_id": clip_id, "status": "skipped", "reason": "无文本内容"}

        try:
            logger.info("处理片段 %d/%d: %s", idx + 1, len(clips), clip_id)
            async with sem:
                embedding = await asyncio.to_thread(embedder.embed, text)
            # Faiss 写入通常非线程安全，串行化写入
            async with add_lock:
                await asyncio.to_thread(vector_db.add_embedding, clip_id, embedding)
            return {"clip_id": clip_id, "status": "success", "text_length": len(text)}
        except Exception as e:
            logger.error("片段 %s Embedding 失败: %s", clip_id, e)
            return {"clip_id": clip_id, "status": "error", "error": str(e)}

    results = await asyncio.gather(*[_process_one(i, clip) for i, clip in enumerate(clips)])

    return {
        "video_id": video_id,
        "total_clips": len(clips),
        "processed": sum(1 for r in results if r["status"] == "success"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "failed": sum(1 for r in results if r["status"] == "error"),
        "results": results,
    }
