import os
import logging
from fastapi import APIRouter, HTTPException
from app.db.database import get_db_conn, DB_PATH
from app.core.embedder import Embedder
from app.core.vector_db.sqlite_vss import SQLiteVSSDB

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["embed"])

# 单例
_embedder = None
_vector_db = None


async def _get_embedder_and_db():
    """从配置读取参数，返回 Embedder 和 VectorDB 实例"""
    global _embedder, _vector_db

    db = await get_db_conn()
    try:
        # 读取配置
        async def get_cfg(key, default=""):
            cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
            row = await cursor.fetchone()
            return row["value"] if row else default

        api_key   = await get_cfg("vlm_api_key")
        base_url  = await get_cfg("vlm_base_url", "https://api.openai.com/v1")
        dimension = int(await get_cfg("vector_dimension", "1536"))
    finally:
        await db.close()

    if not api_key:
        raise HTTPException(status_code=400, detail="API Key 未配置，请在设置页面配置 vlm_api_key")

    if _embedder is None:
        _embedder = Embedder(base_url=base_url, api_key=api_key)

    if _vector_db is None:
        _vector_db = SQLiteVSSDB(db_path=DB_PATH, vector_dimension=dimension)

    return _embedder, _vector_db


@router.post("/{video_id}/process-embed")
async def process_embed(video_id: str):
    """
    为视频所有片段生成 Embedding 并入库。
    拼接 asr_text + vlm_description 作为文本输入。
    """
    db = await get_db_conn()
    try:
        # 确认视频存在
        cursor = await db.execute("SELECT id FROM videos WHERE id = ?", (video_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")

        # 获取片段
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

    # 初始化 embedder 和 vector_db
    embedder, vector_db = await _get_embedder_and_db()

    results = []
    for i, clip in enumerate(clips):
        clip_id = clip["id"]
        asr_text = clip["asr_text"] or ""
        vlm_desc = clip["vlm_description"] or ""
        text = (asr_text + " " + vlm_desc).strip()

        if not text:
            logger.warning(f"片段 {clip_id} 没有文本内容，跳过")
            results.append({"clip_id": clip_id, "status": "skipped", "reason": "无文本内容"})
            continue

        try:
            logger.info(f"处理片段 {i+1}/{len(clips)}: {clip_id}")
            embedding = embedder.embed(text)
            vector_db.add_embedding(clip_id, embedding)
            results.append({"clip_id": clip_id, "status": "success", "text_length": len(text)})
        except Exception as e:
            logger.error(f"片段 {clip_id} Embedding 失败: {e}")
            results.append({"clip_id": clip_id, "status": "error", "error": str(e)})

    return {
        "video_id": video_id,
        "total_clips": len(clips),
        "processed": sum(1 for r in results if r["status"] == "success"),
        "skipped":   sum(1 for r in results if r["status"] == "skipped"),
        "failed":    sum(1 for r in results if r["status"] == "error"),
        "results": results,
    }
