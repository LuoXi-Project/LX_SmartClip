from __future__ import annotations

import json
import logging
from typing import Any, List

from fastapi import HTTPException
from pydantic import ValidationError

from app.core.llm import LLMClient
from app.core.llm.response_utils import extract_json_object
from app.models.auto_edit_timeline import ClipEventsBatch

logger = logging.getLogger(__name__)


_EVENTS_SYS_PROMPT = """你是一位视频素材事件提名器（event nominator）。
你将收到若干条素材片段的文本信息（包含 clip_id、ASR/VLM 摘要等）。
你的任务是：为每个 clip 提名若干“可用于剪辑编排”的事件 ClipEvent，并给出 role/beat 和局部分数。

硬性要求（必须遵守）：
- 只输出 JSON，不要解释文字，不要 Markdown。
- 输出必须是 ClipEventsBatch 结构：{"batch_id":"...","events":[...]}
- events[*].clip_id 必须从输入中出现的 clip_id 原样拷贝，禁止编造。
- 分数范围 0~1。
- 每个 clip 事件数不要过多（建议 0~6）。
"""


_EVENTS_SCHEMA_HINT = """
输出 JSON 结构示例：
{
  "batch_id": "b_001",
  "events": [
    {
      "event_id": "e1",
      "clip_id": "CLIP_123",
      "time_range": {"start_sec": 3.2, "end_sec": 6.8},
      "text": "一句话概括该事件（可用于字幕/旁白）",
      "source": "asr|vlm|asr+vlm|llm|user",
      "role": "hook|context|highlight|cta|broll|transition",
      "beat": "setup|turn|payoff|montage|explain|demo",
      "scores": {"local_score": 0.86, "relevance": 0.9, "clarity": 0.8, "emotion": 0.3},
      "tags": ["关键词1","关键词2"],
      "evidence": "可选：引用输入中的原句"
    }
  ]
}
"""


def split_context_into_batches(context: str, *, max_clips_per_batch: int = 25) -> List[str]:
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
    buf: list[str] = []
    cnt = 0
    for b in blocks:
        if cnt >= max_clips_per_batch and buf:
            batches.append("\n".join(buf).strip())
            buf = []
            cnt = 0
        buf.extend(b)
        cnt += 1
    if buf:
        batches.append("\n".join(buf).strip())
    return [b for b in batches if b]


async def call_llm_for_events_batch(
    *,
    cfg: dict[str, Any],
    batch_id: str,
    batch_context: str,
) -> ClipEventsBatch:
    logger.info("auto_edit 启用新引擎：正在生成事件池（批次）")
    llm = LLMClient(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        temperature=0.2,
        max_tokens=min(int(cfg.get("max_tokens") or 20480), 8192),
        timeout=3600,
    )
    messages = [
        {"role": "system", "content": _EVENTS_SYS_PROMPT},
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
) -> List[ClipEventsBatch]:
    logger.info("auto_edit 启用新引擎：正在分割上下文为批次")
    batches = split_context_into_batches(context, max_clips_per_batch=max_clips_per_batch)
    logger.info("auto_edit 启用新引擎：正在分割上下文为批次完成")
    if max_batches and len(batches) > max_batches:
        batches = batches[:max_batches]

    out: List[ClipEventsBatch] = []
    for i, bctx in enumerate(batches, 1):
        bid = f"b_{i:03d}"
        out.append(await call_llm_for_events_batch(cfg=cfg, batch_id=bid, batch_context=bctx))
    return out

