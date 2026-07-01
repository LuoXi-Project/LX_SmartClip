import logging
import asyncio
import json
from typing import List, Optional, Tuple

from fastapi import APIRouter, Body, HTTPException

from app.core.embedder import Embedder
from app.core.vector_db.faiss_db import FaissVectorDB
from app.api.process_db import update_clip_field
from app.db.database import DB_PATH, get_db_conn
from app.utils.logging_utils import stage_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["embed"])


def _parse_json_list(raw: Optional[str]) -> List[str]:
    """把 clips.keywords / emotion_tags 的 JSON 字符串解析为 list[str]，失败返回 []。"""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if isinstance(data, list):
        return [str(x).strip() for x in data if str(x).strip()]
    return []

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
            "SELECT id, asr_text, vlm_description, abstract_summary, keywords, emotion_tags "
            "FROM clips WHERE video_id = ? ORDER BY start_time",
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
    stage_log(
        "预处理",
        f"向量入库开始：{len(clips)} 个片段 并发={concurrency}",
        status="running",
    )
    logger.info("开始处理 %d 个片段的 Embedding (concurrency=%d)", len(clips), concurrency)

    sem = asyncio.Semaphore(concurrency)
    add_lock = asyncio.Lock()

    async def _process_one(idx: int, clip_row):
        clip_id = clip_row["id"]
        asr_text = clip_row["asr_text"] or ""
        vlm_desc = clip_row["vlm_description"] or ""
        abstract_summary = clip_row["abstract_summary"] or ""
        keywords = _parse_json_list(clip_row["keywords"])
        emotion_tags = _parse_json_list(clip_row["emotion_tags"])
        # 五路文本拼接（与 process_pipeline 一致）：台词 + 画面 + 旁白适配摘要 + 关键词 + 情绪
        # 后三者来自 enrich，用于抹平旁白-画面表征鸿沟；老数据无 enrich 时自动退化为两路。
        parts = [
            asr_text,
            vlm_desc,
            abstract_summary,
            " ".join(keywords),
            " ".join(emotion_tags),
        ]
        text = " ".join(p for p in parts if p and p.strip()).strip()

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

    ok = sum(1 for r in results if r["status"] == "success")
    fail = sum(1 for r in results if r["status"] == "error")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    stage_log(
        "预处理",
        f"向量入库完成：成功 {ok}/{len(clips)}，跳过 {skipped}，失败 {fail}",
        status="done",
    )
    return {
        "video_id": video_id,
        "total_clips": len(clips),
        "processed": ok,
        "skipped": skipped,
        "failed": fail,
        "results": results,
    }


# ────────────────────────────── 智能标注（enrich）重算 ──────────────────────────────

# LLM 实例缓存（与 embedder 缓存同理，按 base_url/key/model 复用，避免每次重建客户端）
_llm_client = None
_llm_sig: Tuple[str, str, str] = ("", "", "")


async def _get_enrich_llm():
    """从 config 读取 LLM 配置并返回 LLMClient；未配置 key 抛 400。"""
    global _llm_client, _llm_sig
    from app.core.llm import LLMClient
    from app.core.llm.config import LLMConfig

    db = await get_db_conn()
    try:
        params = await LLMConfig.get_llm_params_with_defaults(db, default_temperature=0.3)
    finally:
        await db.close()

    base_url = params["base_url"]
    api_key = params["api_key"]
    model = params["model"]
    if not api_key:
        raise HTTPException(status_code=400, detail="LLM API Key 未配置，请在设置页配置 llm_api_key 后再重跑智能标注")

    sig: Tuple[str, str, str] = (base_url or "", api_key or "", model or "")
    if _llm_client is None or _llm_sig != sig:
        _llm_client = LLMClient(
            base_url=base_url,
            api_key=api_key,
            model=model,
            temperature=params["temperature"],
            max_tokens=params["max_tokens"],
        )
        _llm_sig = sig
    return _llm_client


@router.post("/{video_id}/process-enrich")
async def process_enrich(video_id: str, clip_ids: Optional[List[str]] = Body(default=None, embed=True)):
    """
    为视频（或指定片段）重新生成智能标注（abstract_summary / keywords / emotion_tags）。
    输入 = asr_text + vlm_description；复用 pipeline 同款 enrich_clip。
    与 /process-embed 同构：同步并发、不依赖 pipeline。

    请求体可选：{"clip_ids": ["id1", "id2"]}，为空则重跑该视频全部片段。
    """
    from app.core.enricher import enrich_clip

    db = await get_db_conn()
    try:
        cursor = await db.execute("SELECT id FROM videos WHERE id = ?", (video_id,))
        if not await cursor.fetchone():
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")

        if clip_ids:
            placeholders = ",".join("?" * len(clip_ids))
            cursor = await db.execute(
                f"SELECT id, asr_text, vlm_description FROM clips "
                f"WHERE video_id = ? AND id IN ({placeholders}) ORDER BY start_time",
                (video_id, *clip_ids),
            )
        else:
            cursor = await db.execute(
                "SELECT id, asr_text, vlm_description FROM clips "
                "WHERE video_id = ? ORDER BY start_time",
                (video_id,),
            )
        clips = await cursor.fetchall()

        if not clips:
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 没有可标注的片段")
    except HTTPException:
        raise
    finally:
        await db.close()

    llm = await _get_enrich_llm()
    concurrency = 3  # 纯文本 LLM 调用，保守并发避免限流

    stage_log(
        "预处理",
        f"智能标注开始：{len(clips)} 个片段 并发={concurrency}",
        status="running",
    )
    logger.info("开始重新智能标注 %d 个片段 (concurrency=%d)", len(clips), concurrency)

    sem = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()

    async def _process_one(idx: int, clip_row):
        clip_id = clip_row["id"]
        asr_text = clip_row["asr_text"] or ""
        vlm_desc = clip_row["vlm_description"] or ""
        if not asr_text and not vlm_desc:
            logger.warning("片段 %s 无台词也无画面描述，跳过", clip_id)
            return {"clip_id": clip_id, "status": "skipped", "reason": "无文本内容"}

        try:
            logger.info("智能标注片段 %d/%d: %s", idx + 1, len(clips), clip_id)
            async with sem:
                enriched = await enrich_clip(llm, asr_text=asr_text, vlm_description=vlm_desc)
            # 写库串行化（aiosqlite 连接单线程）
            async with write_lock:
                summary = enriched.get("abstract_summary", "")
                keywords = enriched.get("keywords", [])
                emotion_tags = enriched.get("emotion_tags", [])
                await update_clip_field(clip_id, "abstract_summary", summary)
                await update_clip_field(clip_id, "keywords", json.dumps(keywords, ensure_ascii=False) if keywords else "")
                await update_clip_field(clip_id, "emotion_tags", json.dumps(emotion_tags, ensure_ascii=False) if emotion_tags else "")
            has_output = bool(summary or keywords or emotion_tags)
            if not has_output:
                return {"clip_id": clip_id, "status": "error", "error": "标注返回为空"}
            return {
                "clip_id": clip_id,
                "status": "success",
                "abstract_summary": summary,
                "keywords": keywords,
                "emotion_tags": emotion_tags,
            }
        except Exception as e:
            logger.error("片段 %s 智能标注失败: %s", clip_id, e)
            return {"clip_id": clip_id, "status": "error", "error": str(e)}

    results = await asyncio.gather(*[_process_one(i, clip) for i, clip in enumerate(clips)])

    ok = sum(1 for r in results if r["status"] == "success")
    fail = sum(1 for r in results if r["status"] == "error")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    stage_log(
        "预处理",
        f"智能标注完成：成功 {ok}/{len(clips)}，跳过 {skipped}，失败 {fail}",
        status="done",
    )
    return {
        "video_id": video_id,
        "total_clips": len(clips),
        "processed": ok,
        "skipped": skipped,
        "failed": fail,
        "results": results,
    }
