import asyncio
import logging
import os
import sqlite3
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from app.models.match import (
    MatchBatchItem,
    MatchBatchRequest,
    MatchBatchResponse,
    MatchRequest,
    MatchResponse,
    ClipResult,
    VALID_SUBSPACES,
)

from app.core.blocking_pool import run_heavy
from app.core.matcher import Matcher, resolve_match_mode, _attach_media_urls
from app.core.auto_edit.visual_intent import (
    expand_visual_intent_sync,
    expand_visual_intents_sync,
)
from app.core.vlm.relevance import apply_vlm_rerank, score_candidates_sync
from app.db.database import DB_PATH
from app.utils.logging_utils import stage_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["match"])

# 整篇批量匹配：跨段去重的滑动窗口（只惩罚最近 N 个已用片段，长文案不永久拉黑）
_BATCH_PENALIZE_WINDOW = 12
# 批量匹配的 VLM 校验调用预算（每次调用覆盖多个候选），防止长文案成本失控
_BATCH_VLM_BUDGET = 24


def _read_cfg(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def _cfg_bool(conn: sqlite3.Connection, key: str, default: bool) -> bool:
    raw = _read_cfg(conn, key, "1" if default else "0").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


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


def _load_match_runtime(
    conn: sqlite3.Connection,
    match_mode_override: Optional[str],
    *,
    top_k_override: Optional[int],
    top_n_override: Optional[int],
) -> dict:
    """集中读取匹配运行时配置与组件（单次/批量共用），并解析出有效匹配模式。"""
    match_mode_cfg = (match_mode_override or "").strip().lower() or _read_cfg(conn, "match_mode", "auto")

    embed_base_url = _read_cfg(conn, "embedding_base_url", "https://api.openai.com/v1")
    embed_api_key = _read_cfg(conn, "embedding_api_key", "")
    embed_model = _read_cfg(conn, "embedding_model", "text-embedding-3-small")

    llm_base_url = _read_cfg(conn, "llm_base_url", "https://api.openai.com/v1")
    llm_api_key = _read_cfg(conn, "llm_api_key", "")
    llm_model = _read_cfg(conn, "llm_model", "gpt-4o-mini")

    vlm_base_url = _read_cfg(conn, "vlm_base_url", "https://api.openai.com/v1")
    vlm_api_key = _read_cfg(conn, "vlm_api_key", "")
    vlm_model = _read_cfg(conn, "vlm_model", "gpt-4o")

    vector_dim = int(_read_cfg(conn, "vector_dimension", "1024"))
    top_k = top_k_override if top_k_override is not None else int(_read_cfg(conn, "match_top_k", "12"))
    top_n = top_n_override if top_n_override is not None else int(_read_cfg(conn, "match_top_n", "5"))

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

    return {
        "matcher": Matcher(embedder=embedder, vector_db=vector_db, llm=llm),
        "effective_mode": effective_mode,
        "top_k": top_k,
        "top_n": top_n,
        "min_llm_score": min_llm_score,
        "min_similarity": min_similarity,
        "llm_api_key": llm_api_key,
        "llm_cfg": {
            "base_url": llm_base_url,
            "api_key": llm_api_key,
            "model": llm_model,
        },
        "vlm_api_key": vlm_api_key,
        "vlm_cfg": {
            "base_url": vlm_base_url,
            "api_key": vlm_api_key,
            "model": vlm_model,
        },
        # 生成式兜底（文生视频）：SiliconFlow 风格 提交-轮询-下载 协议
        "generate_cfg": {
            "base_url": _read_cfg(conn, "video_gen_base_url", "https://api.siliconflow.cn"),
            "api_key": _read_cfg(conn, "video_gen_api_key", ""),
            "model": _read_cfg(conn, "video_gen_model", "Wan-AI/Wan2.2-T2V-A14B"),
        },
        "gen_min_score": float(_read_cfg(conn, "match_generate_min_score", "5.5") or 5.5),
        "gen_duration_sec": float(_read_cfg(conn, "video_gen_duration_sec", "5") or 5),
        "gen_timeout_sec": float(_read_cfg(conn, "video_gen_timeout_sec", "600") or 600),
        "gen_max_per_batch": int(_read_cfg(conn, "match_generate_max_per_batch", "3") or 3),
    }


def _validate_subspaces(subspaces: Optional[List[str]]) -> None:
    if subspaces:
        invalid = [s for s in subspaces if s not in VALID_SUBSPACES]
        if invalid:
            raise MatchPipelineError(
                400, f"subspaces 含非法值 {invalid}，允许: {sorted(VALID_SUBSPACES)}"
            )


def _resolve_visual_flags(
    conn: sqlite3.Connection,
    rt: dict,
    req_visual_intent: Optional[bool],
    req_visual_verify: Optional[bool],
) -> tuple[bool, bool]:
    """画面意图改写 / VLM 画面校验 的生效开关：请求覆盖 > 全局配置 > 默认值。"""
    use_intent = (
        req_visual_intent
        if req_visual_intent is not None
        else _cfg_bool(conn, "match_visual_intent", True)
    )
    use_intent = bool(use_intent and rt["llm_api_key"])

    use_verify = (
        req_visual_verify
        if req_visual_verify is not None
        else _cfg_bool(conn, "match_visual_verify", False)
    )
    use_verify = bool(use_verify and rt["vlm_api_key"])
    return use_intent, use_verify


def _maybe_visual_intent(rt: dict, query: str) -> Optional[str]:
    """把文案改写为画面意图；过短/失败返回 None（调用方回退原文检索）。"""
    q = (query or "").strip()
    if len(q) < 4:
        return None
    stage_log("检索", "画面意图改写中…", status="running")
    intent = expand_visual_intent_sync(rt["llm_cfg"], q)
    if intent:
        logger.info("[Match] 画面意图：%s", intent[:60])
    return intent


def _maybe_vlm_verify(rt: dict, narration: str, result: dict, verify_top_n: Optional[int]) -> bool:
    """对推荐头部候选抽帧做 VLM 相关度校验并重排；返回是否实际生效。"""
    recommended = result.get("recommended") or []
    if not recommended:
        return False
    n = max(1, min(5, int(verify_top_n or 3)))
    pool = recommended[:n]
    stage_log("检索", f"VLM 画面校验 {len(pool)} 个候选…", status="running")
    scores = score_candidates_sync(rt["vlm_cfg"], narration, pool)
    if not scores:
        return False
    reranked = apply_vlm_rerank(pool, scores)
    result["recommended"] = reranked + recommended[n:]
    return True


def _maybe_generate_fallback(
    rt: dict,
    conn: sqlite3.Connection,
    req_flag: Optional[bool],
    result: dict,
    prompt: str,
    budget: Optional[list],
) -> bool:
    """素材库无强匹配时用文生视频生成空镜补位，置顶推荐并入库。

    - 触发条件：开关开启（请求覆盖 > 全局配置）+ 已配 video_gen_api_key
      + 预算未耗尽 + 推荐为空或最佳分低于 match_generate_min_score；
    - 生成失败静默回退普通推荐；budget 为 [剩余次数] 单元素列表（单次匹配传 None）。
    """
    use_gen = (
        req_flag if req_flag is not None else _cfg_bool(conn, "match_generate_fallback", False)
    )
    if not use_gen or not rt["generate_cfg"].get("api_key"):
        return False
    if budget is not None and budget[0] <= 0:
        return False

    recommended = result.get("recommended") or []
    best = 0.0
    if recommended:
        try:
            best = float(recommended[0].get("score", 0) or 0)
        except (TypeError, ValueError):
            best = 0.0
    if recommended and best >= rt["gen_min_score"]:
        return False

    stage_log("检索", "素材库无强匹配，AI 生成空镜兜底…", status="running")
    from app.core.material.video_gen import generate_broll_sync

    try:
        clip = generate_broll_sync(
            conn,
            rt["generate_cfg"],
            (prompt or "").strip(),
            duration_sec=rt["gen_duration_sec"],
            timeout_sec=rt["gen_timeout_sec"],
        )
    except Exception as e:
        logger.warning("[Match] 空镜生成异常，回退普通推荐: %s", e)
        clip = None
    if not clip:
        return False

    gen = dict(clip)
    gen["score"] = round(max(float(rt["gen_min_score"]), 0.01), 3)  # 置顶推荐
    gen["reason"] = f"AI 生成空镜（素材库最佳匹配 {best:.1f} 分，低于阈值 {rt['gen_min_score']}）"
    gen["is_generated"] = True
    _attach_media_urls([gen], "")
    result["recommended"] = [gen] + list(recommended)
    result["candidates"] = list(result.get("candidates") or []) + [dict(gen)]
    if budget is not None:
        budget[0] -= 1
    return True


def _run_matcher(
    rt: dict,
    conn: sqlite3.Connection,
    req,
    query: str,
    penalize_clip_ids: Optional[List[str]],
    api_base_url: str = "",
) -> dict:
    return rt["matcher"].match(
        query=query,
        db_conn=conn,
        top_k=rt["top_k"],
        top_n=rt["top_n"],
        video_ids=req.video_ids,
        api_base_url=api_base_url,
        mode=rt["effective_mode"],  # type: ignore[arg-type]
        min_llm_score=rt["min_llm_score"],
        min_similarity=rt["min_similarity"],
        refine=req.refine,
        subspaces=req.subspaces,
        penalize_clip_ids=penalize_clip_ids,
    )


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
        _validate_subspaces(req.subspaces)
        rt = _load_match_runtime(
            conn,
            req.match_mode,
            top_k_override=req.top_k,
            top_n_override=req.top_n,
        )
        use_intent, use_verify = _resolve_visual_flags(
            conn, rt, req.visual_intent, req.visual_verify
        )

        q_intent = _maybe_visual_intent(rt, req.query) if use_intent else None
        q_retrieval = q_intent or req.query
        if q_intent:
            stage_log("检索", f"按画面意图检索：「{q_intent[:40]}」", status="running")

        result = _run_matcher(rt, conn, req, q_retrieval, req.penalize_clip_ids, api_base_url)
        verify_applied = (
            _maybe_vlm_verify(rt, req.query, result, req.vlm_verify_top_n)
            if use_verify
            else False
        )
        # 生成兜底：素材库无强匹配时用文生视频补空镜（单次匹配无预算上限）
        _maybe_generate_fallback(
            rt, conn, req.generate_fallback, result, (q_intent or req.query), None
        )

        return MatchResponse(
            query=req.query,
            top_n=result["top_n"],
            recommended=[ClipResult(**c) for c in result["recommended"]],
            candidates=[ClipResult(**c) for c in result["candidates"]],
            visual_intent_query=q_intent,
            visual_verify_applied=verify_applied,
        )

    except MatchPipelineError:
        raise
    except Exception as e:
        logger.error("match_clips 异常: %s", e, exc_info=True)
        raise MatchPipelineError(500, f"匹配失败: {str(e)}") from e
    finally:
        conn.close()


def _match_batch_sync(req: MatchBatchRequest, api_base_url: str) -> MatchBatchResponse:
    """整篇多段文案一次性匹配（线程池中执行）。

    与逐段调用 /api/match 的差异：
    - 画面意图一次 LLM 调用批量改写；
    - 跨段去重：前面段落已选用的片段在后续段落中被降权（滑动窗口），
      避免整片反复出现同一段素材；
    - 可选 VLM 画面校验（带调用预算，长文案自动降频）。
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
    except Exception as e:
        raise MatchPipelineError(500, f"数据库连接失败: {e}") from e

    try:
        _validate_subspaces(req.subspaces)
        rt = _load_match_runtime(
            conn,
            req.match_mode,
            top_k_override=req.top_k,
            top_n_override=req.top_n,
        )
        use_intent, use_verify = _resolve_visual_flags(
            conn, rt, req.visual_intent, req.visual_verify
        )

        segments = [str(s or "").strip() for s in req.segments]
        if use_intent and segments:
            stage_log("检索", f"批量画面意图改写（{len(segments)} 段）…", status="running")
            intents = expand_visual_intents_sync(rt["llm_cfg"], segments)
        else:
            intents = [None] * len(segments)

        used_clip_ids: List[str] = []
        verify_budget = _BATCH_VLM_BUDGET
        gen_budget = [max(0, int(rt["gen_max_per_batch"]))]
        items: List[MatchBatchItem] = []

        for i, seg in enumerate(segments):
            if not seg:
                items.append(MatchBatchItem(query="", recommended=[], candidates=[]))
                continue

            q_intent = intents[i] if i < len(intents) else None
            q_retrieval = q_intent or seg
            penalize = used_clip_ids[-_BATCH_PENALIZE_WINDOW:] or None

            result = _run_matcher(rt, conn, req, q_retrieval, penalize, api_base_url)

            if use_verify and verify_budget > 0:
                if _maybe_vlm_verify(rt, seg, result, req.vlm_verify_top_n):
                    verify_budget -= 1

            # 生成兜底：带预算上限，长文案不会失控烧钱
            _maybe_generate_fallback(
                rt, conn, req.generate_fallback, result, (q_intent or seg), gen_budget
            )

            recommended = result.get("recommended") or []
            if recommended:
                top_cid = str(recommended[0].get("clip_id") or "")
                if top_cid:
                    used_clip_ids.append(top_cid)

            items.append(
                MatchBatchItem(
                    query=seg,
                    visual_intent_query=q_intent,
                    recommended=[ClipResult(**c) for c in result["recommended"]],
                    candidates=[ClipResult(**c) for c in result["candidates"]],
                )
            )

        return MatchBatchResponse(items=items)

    except MatchPipelineError:
        raise
    except Exception as e:
        logger.error("match_clips_batch 异常: %s", e, exc_info=True)
        raise MatchPipelineError(500, f"整篇匹配失败: {str(e)}") from e
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


@router.post("/match/batch", response_model=MatchBatchResponse)
async def match_clips_batch(req: MatchBatchRequest, request: Request):
    """
    整篇多段文案批量匹配：跨段画面意图改写 + 已用片段降权去重 + 可选 VLM 画面校验。
    返回 items 与请求 segments 逐条对应（空段返回空推荐，保持索引对齐）。
    """
    if await request.is_disconnected():
        raise HTTPException(status_code=400, detail="客户端已断开连接")
    api_base_url = str(request.base_url).rstrip("/")
    scope = f"{len(req.video_ids)} 个视频" if req.video_ids else "全部视频"
    stage_log(
        "检索",
        f"整篇匹配开始：{len(req.segments)} 段文案，范围={scope}",
        status="running",
    )

    timeout_raw = (os.environ.get("SMARTCLIP_MATCH_TIMEOUT_SEC") or "").strip()
    timeout_sec = float(timeout_raw) if timeout_raw else 0.0
    # 批量是 N 段串行匹配，超时按段数放宽（至少与单次一致）
    if timeout_sec > 0:
        timeout_sec = max(timeout_sec, timeout_sec * min(len(req.segments), 20))

    async def _run() -> MatchBatchResponse:
        return await run_heavy(_match_batch_sync, req, api_base_url)

    try:
        if timeout_sec > 0:
            result = await asyncio.wait_for(_run(), timeout=timeout_sec)
        else:
            result = await _run()
        stage_log(
            "检索",
            f"整篇匹配完成：{len(result.items)} 段",
            status="done",
        )
        return result
    except asyncio.TimeoutError:
        stage_log("检索", "整篇匹配超时", status="error")
        raise HTTPException(
            status_code=504,
            detail="整篇匹配超时，请减少段数或缩小匹配范围",
        ) from None
    except asyncio.CancelledError:
        logger.warning("match_clips_batch 已取消（客户端断开或进程关停）")
        raise
    except MatchPipelineError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
