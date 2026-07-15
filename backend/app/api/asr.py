import json
import asyncio
import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from app.db.database import get_db_conn
from app.core.asr.whisper_asr import WhisperASR
from app.core.asr.openai_asr import OpenAIASR
from app.core.asr.bailian_asr import BailianASR
from app.core.asr.corrector import correct_transcript
from app.api.process_shared import get_splitter
from app.utils.paths import resolve_stored_path
from app.utils.ffmpeg_utils import extract_audio_for_asr
import logging

from app.utils.logging_utils import stage_log
from app.core.llm import LLMClient, LLMConfig
from app.api.process_db import update_clip_asr

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["asr"])

# ASR 单例缓存（key = provider+model_size/model）
_asr_cache: dict = {}


def _cache_key(provider: str, **kwargs) -> str:
    return "|".join([provider] + [f"{k}={v}" for k, v in sorted(kwargs.items())])


def get_asr(
    provider: str = "whisper",
    model_size: str = "small",
    base_url: str = "",
    api_key: str = "",
    model: str = "whisper-1",
    language: str = "",
):
    """获取 ASR 实例（带缓存）"""
    key = _cache_key(
        provider,
        model_size=model_size,
        base_url=base_url,
        model=model,
        language=language or "",
    )
    if key not in _asr_cache:
        if provider == "openai":
            logger.info("初始化 OpenAI ASR (base_url=%s, model=%s)", base_url, model)
            _asr_cache[key] = OpenAIASR(
                base_url=base_url,
                api_key=api_key,
                model=model,
                language=language,
            )
        elif provider == "bailian":
            logger.info("初始化百炼 ASR (base_url=%s, model=%s)", base_url, model)
            _asr_cache[key] = BailianASR(
                base_url=base_url,
                api_key=api_key,
                model=model,
                language=language,
            )
        else:
            logger.info("初始化 Whisper ASR (model_size=%s)", model_size)
            _asr_cache[key] = WhisperASR(
                model_size=model_size,
                language=language or None,
            )
    return _asr_cache[key]


async def _read_config(db, key: str, default: str = "") -> str:
    cursor = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row["value"] if row else default


def _parse_positive_int(raw: str, default: int, min_v: int = 1, max_v: int = 64) -> int:
    try:
        v = int(str(raw or "").strip())
    except Exception:
        v = default
    v = max(min_v, v)
    v = min(max_v, v)
    return v


@router.post("/{video_id}/process-asr")
async def process_asr(video_id: str):
    """
    处理视频的所有片段的 ASR

    从 config 读取 asr_provider、asr_model（whisper 模型大小）、
    asr_base_url、asr_api_key、asr_openai_model 参数
    """
    db = await get_db_conn()
    try:
        # 查询视频
        cursor = await db.execute(
            "SELECT id FROM videos WHERE id = ?", (video_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 不存在")

        # 读取 ASR 配置
        asr_provider   = await _read_config(db, "asr_provider", "whisper")
        model_size     = await _read_config(db, "asr_model", "small")
        asr_base_url   = await _read_config(db, "asr_base_url", "https://api.openai.com/v1")
        asr_api_key    = await _read_config(db, "asr_api_key", "")
        asr_openai_model = await _read_config(db, "asr_openai_model", "whisper-1")
        asr_language = (await _read_config(db, "asr_language", "zh") or "").strip()
        asr_concurrency_raw = await _read_config(db, "asr_concurrency", "1")
        asr_concurrency = _parse_positive_int(asr_concurrency_raw, default=1, min_v=1, max_v=16)

        # 获取 ASR 实例
        asr_instance = get_asr(
            provider=asr_provider,
            model_size=model_size,
            base_url=asr_base_url,
            api_key=asr_api_key,
            model=asr_openai_model,
            language=asr_language,
        )

        # 查询视频的所有片段
        cursor = await db.execute(
            "SELECT id, clip_path FROM clips WHERE video_id = ? ORDER BY start_time",
            (video_id,),
        )
        clips = await cursor.fetchall()

        if not clips:
            raise HTTPException(status_code=404, detail=f"视频 '{video_id}' 没有片段")

        stage_log(
            "预处理",
            f"ASR 开始：{len(clips)} 个片段 provider={asr_provider} 并发={asr_concurrency}",
            status="running",
        )
        logger.info(
            "开始处理 %d 个片段的 ASR (provider=%s, concurrency=%d)",
            len(clips),
            asr_provider,
            asr_concurrency,
        )

        sem = asyncio.Semaphore(asr_concurrency)

        async def _process_one(idx: int, clip_row):
            clip_id = clip_row["id"]
            clip_path = resolve_stored_path(clip_row["clip_path"])
            try:
                logger.info("处理片段 %d/%d: %s", idx + 1, len(clips), clip_id)
                async with sem:
                    splitter = get_splitter(video_id)
                    if asr_provider == "bailian":
                        clip_name = os.path.splitext(os.path.basename(clip_path))[0]
                        audio_out = os.path.join(splitter.audio_dir, f"{clip_name}.asr.wav")
                        audio_path = await asyncio.to_thread(
                            lambda: extract_audio_for_asr(
                                clip_path,
                                audio_out,
                                overwrite=True,
                                sample_rate=16000,
                                channels=1,
                            ),
                        )
                    else:
                        audio_path = await asyncio.to_thread(
                            splitter.extract_audio, clip_path
                        )
                    tr = await asyncio.to_thread(asr_instance.transcribe_detailed, audio_path)
                    asr_text = tr.text
                    seg_list = tr.segments_as_dicts()
                return {
                    "clip_id": clip_id,
                    "status": "success",
                    "asr_text": asr_text,
                    "asr_segments": seg_list,
                    "segment_count": len(seg_list),
                    "text_length": len(asr_text),
                    "text": asr_text[:100] + "..." if len(asr_text) > 100 else asr_text,
                }
            except Exception as e:
                logger.error("片段 %s ASR 失败: %s", clip_id, e)
                return {"clip_id": clip_id, "status": "error", "error": str(e)}

        results = await asyncio.gather(*[_process_one(i, clip) for i, clip in enumerate(clips)])

        # 写库：串行更新，避免并发写同一连接
        for r in results:
            if r.get("status") == "success":
                segs = r.get("asr_segments") or []
                seg_json = (
                    json.dumps(segs, ensure_ascii=False) if segs else None
                )
                await db.execute(
                    "UPDATE clips SET asr_text = ?, asr_segments = ? WHERE id = ?",
                    (r.get("asr_text", ""), seg_json, r["clip_id"]),
                )
        await db.commit()

        ok = sum(1 for r in results if r["status"] == "success")
        fail = sum(1 for r in results if r["status"] == "error")
        stage_log("预处理", f"ASR 完成：成功 {ok}/{len(clips)}，失败 {fail}", status="done")
        return {
            "video_id": video_id,
            "total_clips": len(clips),
            "processed": ok,
            "failed": fail,
            "results": results,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("ASR 处理失败: %s", e)
        raise HTTPException(status_code=500, detail=f"ASR 处理失败: {str(e)}")
    finally:
        await db.close()


@router.get("/asr/info")
async def get_asr_info():
    """获取当前 ASR 配置信息"""
    from app.db.database import get_db_conn as _get
    db = await _get()
    try:
        asr_provider     = await _read_config(db, "asr_provider", "whisper")
        model_size       = await _read_config(db, "asr_model", "small")
        asr_base_url     = await _read_config(db, "asr_base_url", "https://api.openai.com/v1")
        asr_openai_model = await _read_config(db, "asr_openai_model", "whisper-1")
        asr_language = (await _read_config(db, "asr_language", "zh") or "").strip()
    finally:
        await db.close()

    return {
        "provider": asr_provider,
        "model_size": model_size,
        "asr_base_url": asr_base_url,
        "asr_openai_model": asr_openai_model,
        "asr_language": asr_language or None,
    }


# ===========================================================================
# ASR 结果 LLM 校准
# ===========================================================================
# 用 LLM 修正 ASR 识别错误（同音/形近错字、标点、断句），保留原句级时间轴的
# start/end，只更新每句 text；校准后 asr_text 由各句拼接，保证全文↔句级一致。
#
# - apply=false：仅返回 diff，不写库（用于「预览对比确认」）
# - apply=true ：写库覆盖 asr_text/asr_segments，并提示需重算向量
# 流水线自动校准见 process_pipeline._asr_worker（由 asr_auto_correct 开关控制）。


class AsrCorrectRequest(BaseModel):
    apply: bool = Field(
        False, description="true=校准后直接写库覆盖；false=仅返回 diff 预览"
    )


class AsrCorrectBatchRequest(BaseModel):
    clip_ids: list[str] | None = Field(
        None, description="待校准片段 id 列表；不传则校准该视频下全部片段"
    )
    apply: bool = Field(False, description="true=校准后直接写库；false=仅返回 diff")


async def _build_llm_for_correct(db) -> LLMClient:
    """读取 LLM 配置并构造客户端（复用 llm_* 配置，温度偏低）。"""
    cfg = await LLMConfig.get_llm_params_with_defaults(
        db,
        base_url_key="llm_base_url",
        api_key_key="llm_api_key",
        model_key="llm_model",
        fallback_model_key="vlm_model",
        default_temperature=0.2,
        default_max_tokens=8192,
    )
    return LLMClient(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        temperature=cfg["temperature"],
        max_tokens=cfg["max_tokens"],
        timeout=120.0,
    )


def _parse_segments(raw) -> list[dict]:
    """解析 clips.asr_segments（JSON 字符串）为 list[{start,end,text}]。"""
    if not raw:
        return []
    if isinstance(raw, list):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                {
                    "start": float(item.get("start", 0.0) or 0.0),
                    "end": float(item.get("end", 0.0) or 0.0),
                    "text": str(item.get("text", "") or ""),
                }
            )
        except (TypeError, ValueError):
            continue
    return out


async def _build_correction_context(
    db, video_id: str, exclude_clip_id: str | None = None
) -> tuple[str, str]:
    """
    为 ASR 校准拼装上下文，帮助 LLM 理解视频主题、修正领域专有名词。

    Returns:
        (topic, context)
        - topic: 视频标题（通常是用户起的有意义名字）
        - context: 同视频其他片段的 ASR 文本（按时间顺序，排除当前片段自身），
          长度受限以免过长。
    """
    topic = ""
    try:
        cur = await db.execute("SELECT name FROM videos WHERE id = ?", (video_id,))
        vrow = await cur.fetchone()
        if vrow:
            topic = (vrow["name"] or "").strip()
    except Exception:
        pass

    context_parts: list[str] = []
    try:
        cur = await db.execute(
            "SELECT id, start_time, asr_text FROM clips "
            "WHERE video_id = ? AND asr_text IS NOT NULL AND TRIM(asr_text) <> '' "
            "ORDER BY start_time",
            (video_id,),
        )
        rows = await cur.fetchall()
        total_chars = 0
        # 全局字符预算，避免上下文过长
        for r in rows:
            if exclude_clip_id and r["id"] == exclude_clip_id:
                continue
            txt = (r["asr_text"] or "").strip()
            if not txt:
                continue
            if total_chars + len(txt) > 2000:
                # 截断到预算
                remain = 2000 - total_chars
                if remain > 20:
                    context_parts.append(txt[:remain] + "…")
                break
            context_parts.append(txt)
            total_chars += len(txt)
    except Exception:
        pass

    return topic, "\n".join(context_parts)


@router.post("/clips/{clip_id}/asr-correct")
async def correct_clip_asr(clip_id: str, req: AsrCorrectRequest):
    """对单个片段的 ASR 结果做 LLM 校准（预览或直接应用）。"""
    db = await get_db_conn()
    try:
        cursor = await db.execute(
            "SELECT id, video_id, asr_text, asr_segments FROM clips WHERE id = ?",
            (clip_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"片段 '{clip_id}' 不存在")

        asr_text = row["asr_text"] or ""
        segments = _parse_segments(row["asr_segments"])

        if not asr_text.strip() and not segments:
            raise HTTPException(status_code=400, detail="该片段暂无 ASR 文本，无法校准")

        try:
            llm = await _build_llm_for_correct(db)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # 拼装视频主题 + 同视频其他片段上下文，帮助修正领域专有名词
        topic, context = await _build_correction_context(db, row["video_id"], exclude_clip_id=clip_id)

        try:
            result = await correct_transcript(
                llm, asr_text, segments, topic=topic, context=context
            )
        except Exception as e:
            logger.error("片段 %s ASR 校准失败: %s", clip_id, e)
            raise HTTPException(status_code=500, detail=f"LLM 校准失败: {e}")

        applied = False
        vector_stale = False
        if req.apply and result["changed"]:
            seg_json = (
                json.dumps(result["corrected_segments"], ensure_ascii=False)
                if result["corrected_segments"]
                else None
            )
            await update_clip_asr(clip_id, result["corrected_text"], seg_json)
            applied = True
            # asr_text 已变更，原向量过期；前端可触发 embed_only 重算
            vector_stale = True

        return {
            "clip_id": clip_id,
            "original_text": result["original_text"],
            "corrected_text": result["corrected_text"],
            "original_segments": result["original_segments"],
            "corrected_segments": result["corrected_segments"],
            "changed": result["changed"],
            "applied": applied,
            "vector_stale": vector_stale,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("ASR 校准接口失败: %s", e)
        raise HTTPException(status_code=500, detail=f"ASR 校准失败: {str(e)}")
    finally:
        await db.close()


@router.post("/{video_id}/asr-correct-batch")
async def correct_video_asr_batch(video_id: str, req: AsrCorrectBatchRequest):
    """批量校准视频下多个片段的 ASR（串行，避免 LLM 速率限制）。"""
    db = await get_db_conn()
    try:
        if req.clip_ids:
            placeholders = ",".join(["?"] * len(req.clip_ids))
            cursor = await db.execute(
                f"SELECT id, asr_text, asr_segments FROM clips "
                f"WHERE video_id = ? AND id IN ({placeholders}) ORDER BY start_time",
                (video_id, *req.clip_ids),
            )
        else:
            cursor = await db.execute(
                "SELECT id, asr_text, asr_segments FROM clips "
                "WHERE video_id = ? ORDER BY start_time",
                (video_id,),
            )
        rows = await cursor.fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="未找到可校准的片段")

        # 过滤掉无文本的片段
        targets = [
            r for r in rows if (r["asr_text"] or "").strip() or _parse_segments(r["asr_segments"])
        ]
        if not targets:
            raise HTTPException(status_code=400, detail="所选片段均无 ASR 文本")

        try:
            llm = await _build_llm_for_correct(db)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # 视频主题 + 片段文本映射（用于为每条拼装上下文，排除自身）
        topic, _ = await _build_correction_context(db, video_id, exclude_clip_id=None)
        clip_text_map = {
            r["id"]: (r["asr_text"] or "").strip()
            for r in targets
            if (r["asr_text"] or "").strip()
        }

        results = []
        ok = 0
        changed = 0
        for r in targets:
            cid = r["id"]
            asr_text = r["asr_text"] or ""
            segments = _parse_segments(r["asr_segments"])
            # 上下文：同视频其他片段文本（排除自身），按字符预算截断
            ctx_parts: list[str] = []
            ctx_chars = 0
            for other_cid, other_txt in clip_text_map.items():
                if other_cid == cid or not other_txt:
                    continue
                if ctx_chars + len(other_txt) > 2000:
                    remain = 2000 - ctx_chars
                    if remain > 20:
                        ctx_parts.append(other_txt[:remain] + "…")
                    break
                ctx_parts.append(other_txt)
                ctx_chars += len(other_txt)
            context = "\n".join(ctx_parts)
            try:
                res = await correct_transcript(
                    llm, asr_text, segments, topic=topic, context=context
                )
                applied = False
                if req.apply and res["changed"]:
                    seg_json = (
                        json.dumps(res["corrected_segments"], ensure_ascii=False)
                        if res["corrected_segments"]
                        else None
                    )
                    await update_clip_asr(cid, res["corrected_text"], seg_json)
                    applied = True
                if res["changed"]:
                    changed += 1
                ok += 1
                results.append(
                    {
                        "clip_id": cid,
                        "status": "success",
                        "changed": res["changed"],
                        "applied": applied,
                        "original_text": res["original_text"],
                        "corrected_text": res["corrected_text"],
                    }
                )
            except Exception as e:
                logger.warning("批量校准：片段 %s 失败: %s", cid, e)
                results.append({"clip_id": cid, "status": "error", "error": str(e)})

        return {
            "video_id": video_id,
            "total": len(targets),
            "success": ok,
            "changed": changed,
            "applied": bool(req.apply),
            "vector_stale": bool(req.apply and changed > 0),
            "results": results,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("批量 ASR 校准失败: %s", e)
        raise HTTPException(status_code=500, detail=f"批量校准失败: {str(e)}")
    finally:
        await db.close()
