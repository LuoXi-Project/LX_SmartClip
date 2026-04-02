"""copy_gen.py — 文案智能生成 API

根据选中视频的 ASR + VLM 内容，调用 LLM 自动生成文案段落。
支持流式 (SSE) 输出。
"""
from __future__ import annotations

import json
import logging
import re
from typing import List, Optional, Dict, Tuple

import aiosqlite
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.models.copy_gen import CopyGenRequest

from app.db.database import DB_PATH
from app.core.llm import LLMClient, LLMConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/copy-gen", tags=["copy-gen"])



# ────────────────────────────────────────────────────────────
# Context builder
# ────────────────────────────────────────────────────────────

async def _build_video_context(db: aiosqlite.Connection, video_ids: List[str]) -> str:
    """
    从数据库查询选中视频下所有 clip 的 ASR 台词与 VLM 画面描述，
    拼成结构化文本作为 LLM system context。
    说明：
    - 默认不对 ASR/VLM 做“按字段硬截断”，而是依赖“素材筛选 + 全局字符预算”控制上下文长度。
    - 当用户一次选择很多视频时，会先做轻量相关性召回（基于 user_prompt 关键词命中），再选择 topK，最后按字符预算拼装。
    """
    # NOTE：保持签名不变时，无法拿到 user_prompt 做相关性筛选。
    # 计划生成（auto_edit）会走带 user_prompt 参数的重载版本。
    #
    # 这里提供一个“安全默认”：只取前若干条候选片段，避免上下文过长。
    placeholders = ",".join(["?"] * len(video_ids))
    sql = f"""
        SELECT c.id, v.name AS video_name,
               c.start_time, c.end_time,
               c.asr_text, c.vlm_description
        FROM clips c
        JOIN videos v ON v.id = c.video_id
        WHERE c.video_id IN ({placeholders})
          AND (
            TRIM(COALESCE(c.asr_text, '')) <> ''
            OR TRIM(COALESCE(c.vlm_description, '')) <> ''
          )
        ORDER BY v.name, c.start_time
        LIMIT 120
    """
    async with db.execute(sql, video_ids) as cur:
        rows = await cur.fetchall()

    if not rows:
        return "（未找到有效的 ASR 或 VLM 识别内容）"

    # 兜底拼装：做一个全局字符预算保护
    context_max_chars = 12000
    total_chars = 0
    lines: list[str] = []
    cur_video = None
    header_added = False
    for row in rows[:40]:
        if row["video_name"] != cur_video:
            cur_video = row["video_name"]
            header_added = False
        t0 = _fmt_time(row["start_time"])
        t1 = _fmt_time(row["end_time"])
        asr = (row["asr_text"] or "").strip()
        vlm = (row["vlm_description"] or "").strip()
        parts = []
        if asr:
            parts.append(f"台词：{asr}")
        if vlm:
            parts.append(f"画面：{vlm}")
        if not parts:
            continue
        if not header_added:
            header = f"\n【视频：{cur_video}】"
            if lines and total_chars + len(header) > context_max_chars:
                break
            lines.append(header)
            total_chars += len(header)
            header_added = True
        # 显式带上 clip_id，方便后续 Plan 严格复用真实 ID
        line = f"  [clip_id={row['id']}] [{t0}→{t1}] " + " | ".join(parts)
        if lines and total_chars + len(line) > context_max_chars:
            break
        lines.append(line)
        total_chars += len(line)

    return "\n".join(lines)


def _extract_prompt_keywords(user_prompt: str, max_keywords: int = 25) -> list[str]:
    """
    从用户提示词中抽取关键词（用于轻量相关性召回）。
    目标：简单、快、无需额外 embedding/向量库。
    """
    if not user_prompt:
        return []
    # 取长度>=2 的中英文/数字片段作为关键词
    tokens = re.findall(r"[0-9A-Za-z\u4e00-\u9fff]{2,}", user_prompt.lower())
    # 去重：保序
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        t = t.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= max_keywords:
            break
    return out


async def _build_video_context_with_recall(
    db: aiosqlite.Connection,
    video_ids: List[str],
    *,
    user_prompt: str,
    candidate_limit_per_video: int = 80,
    max_total_candidates: int = 500,
    top_k: int = 25,
    context_max_chars: int = 12000,
    bin_size_sec: float = 12.0,
) -> str:
    """
    更适合“Plan/自动成片规划”的上下文构建：
    1) 不对字段做硬截断（ASR/VLM 全量可用于评分与挑选）
    2) 基于关键词命中做召回排序
    3) 用 topK + 时间 bin 多样性 + 全局字符预算 控制上下文长度
    """
    if not video_ids:
        return "（未找到有效的 ASR 或 VLM 识别内容）"

    keywords = _extract_prompt_keywords(user_prompt)

    candidates: list[dict] = []
    sql = """
        SELECT c.id, v.name AS video_name,
               c.start_time, c.end_time,
               c.asr_text, c.vlm_description
        FROM clips c
        JOIN videos v ON v.id = c.video_id
        WHERE c.video_id = ?
          AND (
            TRIM(COALESCE(c.asr_text, '')) <> ''
            OR TRIM(COALESCE(c.vlm_description, '')) <> ''
          )
        ORDER BY c.start_time
        LIMIT ?
    """
    for vid in video_ids:
        if len(candidates) >= max_total_candidates:
            break
        per_limit = min(candidate_limit_per_video, max_total_candidates - len(candidates))
        async with db.execute(sql, (vid, per_limit)) as cur:
            rows = await cur.fetchall()
            candidates.extend([dict(r) for r in rows])

    if not candidates:
        return "（未找到有效的 ASR 或 VLM 识别内容）"

    # 无关键词：直接用时间顺序挑选，避免全零评分导致空白
    if not keywords:
        candidates.sort(key=lambda r: (r.get("video_name") or "", float(r.get("start_time") or 0.0)))
        picked = candidates[:top_k]
    else:
        scored: list[Tuple[int, dict]] = []
        for c in candidates:
            asr = (c.get("asr_text") or "").strip()
            vlm = (c.get("vlm_description") or "").strip()
            asr_l = asr.lower()
            vlm_l = vlm.lower()
            score = 0
            # 简单加权：台词 > 画面（更贴近字幕/口播规划）
            for kw in keywords:
                if kw and kw in asr_l:
                    score += 2
                if kw and kw in vlm_l:
                    score += 1
            scored.append((score, c))

        # 先按 score 再按 start_time 排序，稳定一些
        scored.sort(key=lambda x: (x[0], float(x[1].get("start_time") or 0.0)), reverse=True)

        video_names = list({(c.get("video_name") or "") for _, c in scored})
        per_video_max = max(1, top_k // max(1, len(video_names)))

        picked = []
        used_bins: Dict[str, set[int]] = {}
        picked_count_by_video: Dict[str, int] = {}

        def _vn(c: dict) -> str:
            return str(c.get("video_name") or "")

        for score, c in scored:
            if len(picked) >= top_k:
                break
            vn = _vn(c)
            picked_count_by_video[vn] = picked_count_by_video.get(vn, 0)
            if picked_count_by_video[vn] >= per_video_max:
                continue
            st = float(c.get("start_time") or 0.0)
            b = int(st // max(1e-6, bin_size_sec))
            if vn not in used_bins:
                used_bins[vn] = set()
            if b in used_bins[vn]:
                continue
            picked.append(c)
            used_bins[vn].add(b)
            picked_count_by_video[vn] += 1

        # 若时间分箱导致数量不够，则放宽 bin 限制
        if len(picked) < top_k:
            picked_ids = {str(c.get("id") or "") for c in picked}
            for score, c in scored:
                if len(picked) >= top_k:
                    break
                cid = str(c.get("id") or "")
                if cid in picked_ids:
                    continue
                vn = _vn(c)
                picked_count_by_video[vn] = picked_count_by_video.get(vn, 0)
                if picked_count_by_video[vn] >= per_video_max:
                    continue
                picked.append(c)
                picked_count_by_video[vn] += 1
                picked_ids.add(cid)

    # 将候选按视频名 + 时间排序，减少同一视频 header 重复，并提升可读性
    picked.sort(key=lambda c: (str(c.get("video_name") or ""), float(c.get("start_time") or 0.0)))

    # 拼装 context：字段不截断，但按“全局字符预算”停止追加新 clip
    lines: list[str] = []
    total_chars = 0
    cur_video: Optional[str] = None
    header_added = False
    for c in picked:
        vn = str(c.get("video_name") or "")
        if vn != cur_video:
            cur_video = vn
            header_added = False

        t0 = _fmt_time(float(c.get("start_time") or 0.0))
        t1 = _fmt_time(float(c.get("end_time") or 0.0))
        asr = (c.get("asr_text") or "").strip()
        vlm = (c.get("vlm_description") or "").strip()

        parts = []
        if asr:
            parts.append(f"台词：{asr}")
        if vlm:
            parts.append(f"画面：{vlm}")
        if not parts:
            continue

        if not header_added:
            header = f"\n【视频：{vn}】"
            if lines and total_chars + len(header) > context_max_chars:
                break
            lines.append(header)
            total_chars += len(header)
            header_added = True

        line = f"  [clip_id={c.get('id')}] [{t0}→{t1}] " + " | ".join(parts)
        if lines and total_chars + len(line) > context_max_chars:
            break
        lines.append(line)
        total_chars += len(line)

    return "\n".join(lines)


def _fmt_time(s: float) -> str:
    m, sec = divmod(int(s), 60)
    return f"{m}:{sec:02d}"


# ────────────────────────────────────────────────────────────
# Prompt builder
# ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """你是一位专业的视频文案创作师。
用户会给你提供一段或多段视频的 ASR 语音识别台词和 VLM 画面描述内容，
以及用户的创作诉求（如主题、风格、目的）。

你的任务：
1. 深度理解视频内容（台词 + 画面）。
2. 根据用户诉求，撰写吸引人的视频文案。
3. 将文案按段落拆分，每段对应一个视频片段或一个叙事节拍。
4. 每段之间用空行分隔，不要有编号或序号前缀。
5. 文案要自然流畅、有感染力，符合短视频风格。
6. 只输出文案内容，不要输出任何解释或元信息。"""


def _build_user_message(context: str, req: CopyGenRequest) -> str:
    style_hint = f"\n风格要求：{req.style}" if req.style else ""
    return (
        f"以下是视频的识别内容：\n{context}\n\n"
        f"---\n"
        f"用户诉求：{req.user_prompt}{style_hint}\n"
        f"请将文案拆分为约 {req.max_segments} 段（每段空行分隔），每段对应一个叙事节拍。"
    )


# ────────────────────────────────────────────────────────────
# Route
# 
@router.post("/generate")
async def generate_copy(req: CopyGenRequest):
    """
    根据选中视频内容 + 用户诉求，通过 LLM 生成文案段落。
    支持 stream=true 返回 SSE，stream=false 返回 JSON。
    """
    if not req.video_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个视频")

    # ── 读取配置 & 构建视频上下文 ──
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cfg = await LLMConfig.get_llm_params_with_defaults(
                db,
                base_url_key="llm_base_url",
                api_key_key="llm_api_key",
                model_key="llm_model",
                fallback_model_key="vlm_model",
                default_temperature=0.85,
                default_max_tokens=20480,
            )
            context = await _build_video_context_with_recall(
                db,
                req.video_ids,
                user_prompt=req.user_prompt,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    base_url    = cfg["base_url"]
    api_key     = cfg["api_key"]
    model       = cfg["model"]
    temperature = cfg["temperature"]
    max_tokens  = cfg["max_tokens"]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": _build_user_message(context, req)},
    ]

    # ── 流式输出 ──
    if req.stream:
        async def _sse():
            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=90)
                stream = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield ("data: " + json.dumps({"content": delta}, ensure_ascii=False) + "\n\n").encode()
                yield b"data: [DONE]\n\n"
            except Exception as e:
                logger.error("copy_gen stream error: %s", e)
                yield ("data: " + json.dumps({
                    "error": "stream_error",
                    "detail": f"LLM 流式请求失败: {e}"
                }) + "\n\n").encode()

        return StreamingResponse(
            _sse(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── 非流式输出 ──
    else:
        try:
            llm = LLMClient(
                base_url=base_url,
                api_key=api_key,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=90,
            )
            content = await llm.chat(messages)
            return {"copy": content}
        except Exception as e:
            logger.error("copy_gen error: %s", e)
            raise HTTPException(status_code=502, detail=f"请求 LLM 失败: {e}")
