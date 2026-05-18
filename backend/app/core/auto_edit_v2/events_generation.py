from __future__ import annotations

import json
import logging
from typing import Any, List

from fastapi import HTTPException
from pydantic import ValidationError

from app.core.llm import LLMClient
from app.core.llm.prompts.auto_edit_v2_events import (
    _EVENTS_SYS_PROMPT,
    _EVENTS_SCHEMA_HINT,
    _build_template_sys_append,
)
from app.core.llm.response_utils import extract_json_object
from app.models.auto_edit_timeline import ClipEventsBatch

logger = logging.getLogger(__name__)


def split_context_into_batches(
    context: str,
    *,
    max_clips_per_batch: int = 25,
    max_chars_per_batch: int = 18000,
    overlap_clips: int = 2,
) -> List[str]:
    """
    把 _build_video_context_with_recall() 生成的长文本按 clip 聚合并分批。
    约定：上下文里每个 clip 信息行包含形如 [clip_id=XXX]。
    """
    import re

    lines = (context or "").splitlines()
    blocks: list[list[str]] = []
    cur: list[str] = []
    for ln in lines:
        if re.search(r"\[clip_id=[^\]]+\]", ln):
            if cur:
                blocks.append(cur)
            cur = [ln]
        else:
            if cur:
                cur.append(ln)
    if cur:
        blocks.append(cur)

    # blocks 按 clip 计数切 batch
    batches: List[str] = []
    buf_blocks: list[list[str]] = []
    buf_chars = 0
    for b in blocks:
        b_chars = len("\n".join(b))
        reach_clip_limit = len(buf_blocks) >= max_clips_per_batch
        reach_char_limit = (buf_chars + b_chars) > max_chars_per_batch if buf_blocks else False
        if (reach_clip_limit or reach_char_limit) and buf_blocks:
            batches.append("\n".join(ln for blk in buf_blocks for ln in blk).strip())
            # 为长视频保留小重叠窗口，减少跨批断裂
            carry = buf_blocks[-max(0, overlap_clips) :] if overlap_clips > 0 else []
            buf_blocks = list(carry)
            buf_chars = sum(len("\n".join(x)) for x in buf_blocks)
        buf_blocks.append(b)
        buf_chars += b_chars
    if buf_blocks:
        batches.append("\n".join(ln for blk in buf_blocks for ln in blk).strip())
    return [b for b in batches if b]


async def call_llm_for_events_batch(
    *,
    cfg: dict[str, Any],
    batch_id: str,
    batch_context: str,
    template_preset: str | None = None,
) -> ClipEventsBatch:
    logger.info("auto_edit 启用新引擎：正在生成事件池（批次）")
    sys_prompt = _EVENTS_SYS_PROMPT + _build_template_sys_append(template_preset)
    llm = LLMClient(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        temperature=0.2,
        max_tokens=int(cfg.get("max_tokens") or 20480),
        timeout=3600,
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {
            "role": "user",
            "content": f"batch_id={batch_id}\n\n【素材】\n{batch_context}\n\n{_EVENTS_SCHEMA_HINT}",
        },
    ]
    raw = await llm.chat(messages)
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=502, detail="LLM 返回 events 为空")

    cleaned = extract_json_object(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        try:
            from json_repair import repair_json

            data = json.loads(repair_json(cleaned))
            logger.warning("events batch JSON 修复成功: %s", batch_id)
        except Exception as e:
            logger.error("events batch JSON 解析失败(%s): %s", batch_id, e)
            raise HTTPException(status_code=502, detail="LLM 返回的 events JSON 无法解析")

    # 强制 batch_id（避免 LLM 瞎写）
    if isinstance(data, dict):
        data["batch_id"] = batch_id

    try:
        return ClipEventsBatch(**data)
    except ValidationError as e:
        logger.error("events batch 验证失败(%s): %s", batch_id, e)
        raise HTTPException(status_code=502, detail="LLM 返回的 events 结构不符合预期")


async def call_llm_for_events_all(
    *,
    cfg: dict[str, Any],
    context: str,
    max_clips_per_batch: int = 25,
    max_batches: int = 12,
    template_preset: str | None = None,
) -> List[ClipEventsBatch]:
    logger.info("auto_edit 启用新引擎：正在分割上下文为批次")
    # 长视频参数：优先读配置，未配置回退函数默认
    cfg_max_clips = int(cfg.get("events_max_clips_per_batch") or max_clips_per_batch)
    cfg_max_batches = int(cfg.get("events_max_batches") or max_batches)
    cfg_max_chars = int(cfg.get("events_max_chars_per_batch") or 18000)
    cfg_overlap = int(cfg.get("events_batch_overlap_clips") or 2)
    batches = split_context_into_batches(
        context,
        max_clips_per_batch=max(5, cfg_max_clips),
        max_chars_per_batch=max(4000, cfg_max_chars),
        overlap_clips=max(0, cfg_overlap),
    )
    logger.info("auto_edit 启用新引擎：分割上下文为批次完成，批次数量：%d", len(batches))
    if not batches:
        ctx = (context or "").strip()
        if ctx and "未找到有效" not in ctx:
            logger.warning(
                "auto_edit 上下文未解析到 [clip_id=...] 行，整段作为单批次处理（长度=%d）",
                len(ctx),
            )
            batches = [ctx]
        elif ctx:
            logger.warning("auto_edit 素材上下文为空或无可用 clip，跳过事件池分批")
    if cfg_max_batches and len(batches) > cfg_max_batches:
        batches = batches[:cfg_max_batches]

    out: List[ClipEventsBatch] = []
    for i, bctx in enumerate(batches, 1):
        bid = f"b_{i:03d}"
        batch = await call_llm_for_events_batch(
            cfg=cfg,
            batch_id=bid,
            batch_context=bctx,
            template_preset=template_preset,
        )
        for ev in batch.events:
            tags = list(getattr(ev, "tags", []) or [])
            marker = f"batch:{bid}"
            if marker not in tags:
                tags.append(marker)
            ev.tags = tags
        out.append(batch)
    return out

