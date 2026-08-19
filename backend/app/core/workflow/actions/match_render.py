"""动作：文案分段匹配 + 按原文案配音成片（match 页「全自动成片」的服务端复刻）。

语义约束：成片口播与用户文案逐字一致——文案只做切分，不重写、不丢段。
- match_copy_segments：复刻 match 页切分规则（空行→句读→换行），逐段语义匹配素材
- render_copy_segments：逐段 TTS（可指定音色）→ SRT 对齐 → 烧录成片
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from app.jobs import JobCancelled, check_cancel

from . import WorkflowActionError, action

if TYPE_CHECKING:
    from ..context import WorkflowContext

# 与 match 页 splitCopyText 完全一致的切分规则
def split_copy_text(text: str) -> list[str]:
    """空行分段 → 句读断句 → 换行拆分（与经典模式前端逻辑一致）。"""
    text = text or ""
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) <= 1:
        parts = [p.strip() for p in re.split(r"(?<=[。！？!?])\s*", text) if p.strip()]
    if len(parts) <= 1:
        parts = [p.strip() for p in text.split("\n") if p.strip()]
    return parts


def normalize_video_ids(value) -> list[str]:
    """归一化 video_ids 输入：列表直取；字符串按逗号/空白切分（LLM 生成的定义常见）。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in re.split(r"[,，\s]+", value) if v.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value)]


# ── 动作 1：文案分段匹配 ──────────────────────────────────────────────────

@action(
    "match_copy_segments",
    title="文案分段匹配",
    description=(
        "把文案按「空行→句读→换行」切分成段，逐段在指定素材范围内语义匹配片段，"
        "每段取推荐第一位 clip。文案逐字保留（不重写、不丢段），输出直接交给 "
        "render_copy_segments 按原文案配音成片。"
    ),
    input_schema={
        "copy_text": {"type": "string", "required": True, "description": "成片文案（切分后逐段匹配）"},
        "video_ids": {"type": "string[]", "required": True, "description": "素材范围（可引用采集/预处理步骤输出）"},
        "top_k": {"type": "number", "required": False, "description": "向量初筛数量（默认用全局配置）"},
        "top_n": {"type": "number", "required": False, "description": "每段推荐数量（默认用全局配置）"},
        "match_mode": {"type": "string", "required": False, "description": "匹配模式覆盖：auto/vector/text/llm_only（默认全局配置）"},
        "on_no_match": {"type": "string", "required": False, "description": "某段无匹配素材时的策略：fail=步骤失败（默认，文案不丢段）；any_clip=范围内任取一 clip 兜底", "enum": ["fail", "any_clip"]},
    },
    output_schema={
        "segments": "匹配结果列表 [{copy_text, clip_id, video_id, score}]（顺序与文案一致）",
        "segment_count": "段数",
        "fallback_count": "无匹配而用兜底 clip 的段数",
    },
    example={
        "copy_text": "${inputs.copy_text}",
        "video_ids": "${steps.wait_process.video_ids}",
    },
)
async def run_match_copy_segments(ctx: "WorkflowContext", params: dict) -> dict:
    from app.api.match import _match_clips_sync
    from app.core.blocking_pool import run_heavy
    from app.models.match import MatchRequest

    copy_text = str(params.get("copy_text") or "").strip()
    video_ids = normalize_video_ids(params.get("video_ids"))
    if not copy_text:
        raise WorkflowActionError("match_copy_segments 需要 copy_text")
    if not video_ids:
        raise WorkflowActionError("match_copy_segments 需要 video_ids（素材范围）")
    on_no_match = str(params.get("on_no_match") or "fail")

    parts = split_copy_text(copy_text)
    if not parts:
        raise WorkflowActionError("文案切分后为空")

    # 段级并发（matcher 每段走专用线程池，这里限流避免同时打爆 LLM/FAISS）
    sem = asyncio.Semaphore(3)
    results: list[dict | None] = [None] * len(parts)

    async def _match_one(idx: int, text: str) -> None:
        async with sem:
            await check_cancel(ctx.job_id)
            req = MatchRequest(
                query=text,
                top_k=params.get("top_k") or None,
                top_n=params.get("top_n") or None,
                video_ids=video_ids,
                match_mode=str(params["match_mode"]) if params.get("match_mode") else None,
            )
            # api_base_url 仅用于拼预览 URL，工作流侧不需要
            resp = await run_heavy(_match_clips_sync, req, "")
            hits = list(resp.recommended or []) or list(resp.candidates or [])
            if hits:
                best = hits[0]
                results[idx] = {
                    "copy_text": text,
                    "clip_id": str(best.clip_id),
                    "video_id": str(best.video_id),
                    "score": float(best.score or 0.0),
                    "matched": True,
                }
            else:
                results[idx] = {"copy_text": text, "clip_id": "", "matched": False}

    await asyncio.gather(*[_match_one(i, t) for i, t in enumerate(parts)])

    # 无匹配段兜底：any_clip 模式从范围内取一个 clip（按入库顺序第一个可用）
    fallback_clip: dict | None = None
    if on_no_match == "any_clip":
        for r in results:
            if r and r.get("matched"):
                fallback_clip = {"clip_id": r["clip_id"], "video_id": r["video_id"]}
                break
        if fallback_clip is None:
            # 全部未命中时从库内任取一个 clip
            from app.db.database import get_db_conn

            db = await get_db_conn()
            try:
                placeholders = ",".join("?" for _ in video_ids)
                cur = await db.execute(
                    f"SELECT id, video_id FROM clips WHERE video_id IN ({placeholders}) "
                    f"ORDER BY created_at DESC LIMIT 1",
                    video_ids,
                )
                row = await cur.fetchone()
                if row:
                    fallback_clip = {"clip_id": str(row["id"]), "video_id": str(row["video_id"])}
            finally:
                await db.close()

    segments: list[dict] = []
    fallback_count = 0
    unmatched: list[int] = []
    for idx, r in enumerate(results):
        if not r:
            continue   # gather 全部完成，理论不达
        if r.get("matched"):
            segments.append(r)
            continue
        if on_no_match == "any_clip" and fallback_clip:
            segments.append({
                "copy_text": r["copy_text"],
                "clip_id": fallback_clip["clip_id"],
                "video_id": fallback_clip["video_id"],
                "score": 0.0,
                "matched": False,
            })
            fallback_count += 1
        else:
            unmatched.append(idx + 1)

    if unmatched:
        preview = "、".join(parts[i - 1][:20] for i in unmatched[:3])
        raise WorkflowActionError(
            f"第 {unmatched} 段无匹配素材（如：{preview}）。"
            f"文案不丢段：可补充素材后重跑，或将 on_no_match 设为 any_clip"
        )

    await ctx.reporter.send(
        ctx.current_step, "running",
        f"文案切分 {len(parts)} 段，全部匹配完成"
        + (f"（其中 {fallback_count} 段使用兜底画面）" if fallback_count else ""),
        {"segments": len(segments)},
    )
    return {
        "segments": segments,
        "segment_count": len(segments),
        "fallback_count": fallback_count,
    }


# ── 动作 2：按原文案配音成片 ──────────────────────────────────────────────

@action(
    "render_copy_segments",
    title="按文案配音成片",
    description=(
        "按匹配结果逐段合成 TTS（文案逐字作为口播，可指定音色）→ 生成对齐字幕 → "
        "烧录成片（含后期）。与经典模式「全自动成片」的导出链路一致，成片口播=文案原文。"
    ),
    input_schema={
        "segments": {"type": "object[]", "required": True, "description": "来自 match_copy_segments 的输出"},
        "voice": {"type": "string", "required": False, "description": "TTS 音色（留空用配置默认）"},
        "rate": {"type": "string", "required": False, "description": "TTS 语速，如 +0%/-20%"},
        "volume": {"type": "string", "required": False, "description": "TTS 音量，如 +0%/+10%"},
        "include_subtitle": {"type": "boolean", "required": False, "description": "是否烧录字幕，默认 true"},
        "project_name": {"type": "string", "required": False, "description": "成片项目名（默认自动生成）"},
    },
    output_schema={
        "url": "成片文件 URL（/storage/...，可直接下载）",
        "filename": "成片文件名",
        "segment_count": "成片段数",
        "job_id": "烧录子任务 ID",
    },
    example={
        "segments": "${steps.match.segments}",
        "voice": "${inputs.tts_voice}",
        "include_subtitle": True,
    },
)
async def run_render_copy_segments(ctx: "WorkflowContext", params: dict) -> dict:
    from app.api.subtitle import _launch_burn_job, generate_srt as generate_srt_route
    from app.api.tts import SynthesizeRequest, synthesize as tts_synthesize
    from app.models.subtitle import BurnSubtitleRequest, GenerateSRTRequest, SubtitleSegmentInput

    raw_segments = params.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise WorkflowActionError("render_copy_segments 需要 segments（来自 match_copy_segments 输出）")
    voice = str(params.get("voice") or "").strip() or None
    rate = str(params.get("rate") or "").strip() or None
    volume = str(params.get("volume") or "").strip() or None
    include_subtitle = bool(params.get("include_subtitle", True))
    project_name = str(params.get("project_name") or "").strip() or "workflow_copy_project"

    # 1) 逐段 TTS：文案逐字合成，任一段失败即失败（无口播的文案成片没有意义）
    seg_inputs: list[SubtitleSegmentInput] = []
    tts_sem = asyncio.Semaphore(3)
    total = len(raw_segments)

    async def _tts_one(idx: int, item: dict) -> tuple[int, str]:
        text = str(item.get("copy_text") or "").strip()
        if not text:
            raise WorkflowActionError(f"第 {idx + 1} 段文案为空")
        async with tts_sem:
            await check_cancel(ctx.job_id)
            await ctx.reporter.send(
                ctx.current_step, "running",
                f"配音合成 {idx + 1}/{total}", {"current": idx + 1, "total": total},
            )
            try:
                res = await tts_synthesize(SynthesizeRequest(text=text, voice=voice, rate=rate, volume=volume))
                return idx, res.filename
            except JobCancelled:
                raise
            except Exception as exc:
                raise WorkflowActionError(f"第 {idx + 1} 段 TTS 失败：{str(exc)[:200]}") from exc

    tts_results = await asyncio.gather(*[_tts_one(i, it) for i, it in enumerate(raw_segments)])
    tts_filenames = dict(tts_results)

    for idx, item in enumerate(raw_segments):
        clip_id = str(item.get("clip_id") or "").strip()
        if not clip_id:
            raise WorkflowActionError(f"第 {idx + 1} 段缺少 clip_id（请先经 match_copy_segments 匹配）")
        seg_inputs.append(SubtitleSegmentInput(
            copy_text=str(item.get("copy_text") or "").strip(),
            clip_id=clip_id,
            tts_filename=tts_filenames.get(idx),
        ))

    # 2) 字幕时间轴（按 TTS 实测时长对齐）；不烧字幕时传空 SRT
    srt_content = ""
    if include_subtitle:
        await check_cancel(ctx.job_id)
        srt_res = await generate_srt_route(GenerateSRTRequest(
            segments=seg_inputs, use_tts_timing=True,
        ))
        srt_content = srt_res.srt_content

    # 3) 烧录成片（后台 job，等待完成）
    await check_cancel(ctx.job_id)
    burn_req = BurnSubtitleRequest(
        segments=seg_inputs,
        srt_content=srt_content,
        project_name=project_name,
        require_tts_audio=True,
    )
    job_id = await _launch_burn_job(burn_req)
    ctx.child_job_ids.append(job_id)
    result = await ctx.wait_job(job_id, title="烧录成片")

    url = str(result.get("url") or "")
    if not url:
        raise WorkflowActionError(f"烧录完成但未返回成片地址（result={str(result)[:200]}）")
    return {
        "url": url,
        "filename": result.get("filename") or "",
        "segment_count": total,
        "job_id": job_id,
    }
