"""智能视频大纲：构建上下文、调用 LLM、读写 SQLite。"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

import aiosqlite
from fastapi import HTTPException

from app.core.llm import LLMClient
from app.core.llm.config import LLMConfig
from app.core.llm.response_utils import extract_json_object
from app.db.database import DB_PATH
from app.models.smart_outline import (
    SmartOutlineClipScore,
    SmartOutlineMeta,
    SmartOutlineResponse,
    SmartOutlineTopic,
)

logger = logging.getLogger(__name__)

_SMART_OUTLINE_SYSTEM = """你是资深剪辑策划。用户会给你一条视频的「分片素材表」，每片包含：
- clip_id：必须原样引用；
- 全局时间范围 [start→end]（秒，全片时间轴）；
- 【台词 ASR】：来自语音识别，**这是你判断结构、话题与精彩度的主要依据**；
- 【画面 VLM】：若有，仅作补充（镜头/场景），**权重低于台词**；若某片没有 VLM，不要编造画面。

请完成三件事：
1) 用中文 Markdown 写「视频大纲」（带时间锚点，结构清晰）；
2) 识别「话题段」：给出若干段，每段有标题、在全片上的 start_sec/end_sec（秒）、一句话摘要；按时间顺序，避免严重重叠；
3) 对**每一个输入的 clip_id** 给出精彩度 excitement（0~1，可小数）与简短 reason（中文）。

硬性要求：
- 输出**仅有**一个 JSON 对象，不要 Markdown 代码围栏，不要前后解释文字。
- JSON 键名与类型必须严格如下：
{
  "outline_markdown": "string",
  "topics": [{"title":"string","start_sec":0,"end_sec":0,"summary":"string"}],
  "clip_scores": [{"clip_id":"string","excitement":0.0,"reason":"string"}]
}
- clip_scores 必须覆盖输入中的**全部** clip_id，顺序不限但不可遗漏、不可新增不存在的 clip_id。
- topics 若无把握可少给，但不要编造与台词明显矛盾的内容。
"""


def _fmt_outline_time(sec: float) -> str:
    sec = max(0.0, float(sec))
    m, s = divmod(int(round(sec)), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def _parse_asr_segments_blob(raw: Any) -> List[dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    return []


def _build_smart_outline_user_message(
    rows: List[Any], *, max_chars: int = 28000
) -> tuple[str, SmartOutlineMeta, List[Any]]:
    lines: List[str] = []
    total = 0
    clips_asr = 0
    clips_vlm = 0
    clip_blocks = 0
    included_rows: List[Any] = []

    lines.append("以下为分片素材（按时间顺序）。请严格基于事实生成 JSON。")
    lines.append("")

    for row in rows:
        cid = row["id"]
        t0 = float(row["start_time"] or 0.0)
        t1 = float(row["end_time"] or 0.0)
        asr = (row["asr_text"] or "").strip()
        vlm = (row["vlm_description"] or "").strip()

        head = f"[clip_id={cid}] [{_fmt_outline_time(t0)} → {_fmt_outline_time(t1)}] （全局 {t0:.2f}s–{t1:.2f}s）"
        block_parts: List[str] = []
        if asr:
            block_parts.append("【台词 ASR（主）】\n" + asr)
        else:
            block_parts.append("【台词 ASR（主）】\n（本片段无台词识别结果）")

        if vlm:
            block_parts.append("【画面 VLM（辅）】\n" + vlm)

        segs = _parse_asr_segments_blob(row["asr_segments"])
        if segs:
            sublines: List[str] = []
            for s in segs[:80]:
                try:
                    rs = float(s.get("start", 0.0))
                    re = float(s.get("end", 0.0))
                    txt = (s.get("text") or "").strip()
                except (TypeError, ValueError):
                    continue
                if not txt:
                    continue
                g0, g1 = t0 + rs, t0 + re
                sublines.append(f"  · [{_fmt_outline_time(g0)}–{_fmt_outline_time(g1)}] {txt}")
            if sublines:
                block_parts.append("【句级对齐（已由系统映射到全片时间）】\n" + "\n".join(sublines))

        block = head + "\n" + "\n\n".join(block_parts)

        if total + len(block) + 1 > max_chars:
            lines.append("…（后续片段因长度限制省略，请仅基于已给片段输出 clip_scores 时只使用已列出 clip_id）")
            break
        lines.append(block)
        total += len(block) + 1
        clip_blocks += 1
        included_rows.append(row)
        if asr:
            clips_asr += 1
        if vlm:
            clips_vlm += 1

    meta = SmartOutlineMeta(
        context_clip_count=clip_blocks,
        clips_with_asr=clips_asr,
        clips_with_vlm=clips_vlm,
    )
    return "\n\n".join(lines), meta, included_rows


def _parse_smart_outline_topics(raw: Any) -> List[SmartOutlineTopic]:
    out: List[SmartOutlineTopic] = []
    if not isinstance(raw, list):
        return out
    for t in raw:
        if not isinstance(t, dict):
            continue
        title = (str(t.get("title") or "")).strip() or "未命名话题"
        try:
            a = float(t.get("start_sec", 0.0))
            b = float(t.get("end_sec", 0.0))
        except (TypeError, ValueError):
            continue
        if b < a:
            a, b = b, a
        summary = (str(t.get("summary") or "")).strip() or None
        out.append(SmartOutlineTopic(title=title, start_sec=a, end_sec=b, summary=summary))
    out.sort(key=lambda x: x.start_sec)
    return out


def _merge_smart_outline_scores(rows: List[Any], raw_scores: Any) -> List[SmartOutlineClipScore]:
    by_id: dict[str, tuple[float, Optional[str]]] = {}
    if isinstance(raw_scores, list):
        for item in raw_scores:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("clip_id") or "").strip()
            if not cid:
                continue
            try:
                exc = float(item.get("excitement", 0.5))
            except (TypeError, ValueError):
                exc = 0.5
            exc = max(0.0, min(1.0, exc))
            reason_raw = (str(item.get("reason") or "")).strip()
            by_id[cid] = (exc, reason_raw or None)

    merged: List[SmartOutlineClipScore] = []
    for row in rows:
        cid = str(row["id"])
        t0 = float(row["start_time"] or 0.0)
        t1 = float(row["end_time"] or 0.0)
        exc, reason = by_id.get(cid, (0.5, "（模型未返回该片段评分，已给中性默认分）"))
        merged.append(
            SmartOutlineClipScore(
                clip_id=cid,
                start_time=t0,
                end_time=t1,
                excitement=exc,
                reason=reason,
            )
        )
    return merged


async def fetch_saved_outline(db: aiosqlite.Connection, video_id: str) -> Optional[tuple[SmartOutlineResponse, str]]:
    """返回 (response, updated_at) 或 None。"""
    async with db.execute(
        """
        SELECT o.outline_markdown, o.topics_json, o.clip_scores_json, o.meta_json, o.updated_at, v.name
        FROM video_smart_outlines o
        JOIN videos v ON v.id = o.video_id
        WHERE o.video_id = ?
        """,
        (video_id,),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return None
    try:
        topics_raw = json.loads(row["topics_json"] or "[]")
        scores_raw = json.loads(row["clip_scores_json"] or "[]")
        meta_raw = json.loads(row["meta_json"] or "{}")
    except json.JSONDecodeError:
        return None
    topics = _parse_smart_outline_topics(topics_raw)
    clip_scores: List[SmartOutlineClipScore] = []
    if isinstance(scores_raw, list):
        for item in scores_raw:
            if not isinstance(item, dict):
                continue
            try:
                clip_scores.append(
                    SmartOutlineClipScore(
                        clip_id=str(item.get("clip_id") or ""),
                        start_time=float(item.get("start_time", 0.0)),
                        end_time=float(item.get("end_time", 0.0)),
                        excitement=float(item.get("excitement", 0.0)),
                        reason=(str(item.get("reason") or "").strip() or None),
                    )
                )
            except (TypeError, ValueError):
                continue
    meta = SmartOutlineMeta(
        context_clip_count=int(meta_raw.get("context_clip_count", 0)),
        clips_with_asr=int(meta_raw.get("clips_with_asr", 0)),
        clips_with_vlm=int(meta_raw.get("clips_with_vlm", 0)),
        note=str(
            meta_raw.get("note")
            or "分析以 ASR 台词为主；若存在 VLM 画面描述则作辅助，不得喧宾夺主。"
        ),
    )
    resp = SmartOutlineResponse(
        video_id=video_id,
        video_title=str(row["name"] or video_id),
        outline_markdown=str(row["outline_markdown"] or ""),
        topics=topics,
        clip_scores=clip_scores,
        meta=meta,
    )
    return resp, str(row["updated_at"] or "")


async def upsert_saved_outline(
    db: aiosqlite.Connection,
    *,
    video_id: str,
    response: SmartOutlineResponse,
    max_clips: int,
    now: str,
) -> None:
    meta_dict = response.meta.model_dump()
    topics_json = json.dumps([t.model_dump() for t in response.topics], ensure_ascii=False)
    scores_json = json.dumps([c.model_dump() for c in response.clip_scores], ensure_ascii=False)
    meta_json = json.dumps(meta_dict, ensure_ascii=False)

    await db.execute(
        """
        INSERT INTO video_smart_outlines
          (video_id, outline_markdown, topics_json, clip_scores_json, meta_json, max_clips, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(video_id) DO UPDATE SET
          outline_markdown = excluded.outline_markdown,
          topics_json = excluded.topics_json,
          clip_scores_json = excluded.clip_scores_json,
          meta_json = excluded.meta_json,
          max_clips = excluded.max_clips,
          updated_at = excluded.updated_at
        """,
        (
            video_id,
            response.outline_markdown,
            topics_json,
            scores_json,
            meta_json,
            max_clips,
            now,
            now,
        ),
    )


async def generate_smart_outline_and_persist(
    video_id: str,
    max_clips: int,
) -> tuple[SmartOutlineResponse, str]:
    """生成并写入 DB，返回 (response, updated_at)。"""
    from .utils import now_iso

    vid = (video_id or "").strip()
    if not vid:
        raise HTTPException(status_code=400, detail="video_id 不能为空")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, name FROM videos WHERE id = ?",
            (vid,),
        ) as cur:
            vrow = await cur.fetchone()
        if not vrow:
            raise HTTPException(status_code=404, detail="视频不存在")

        video_title = str(vrow["name"] or vid)

        async with db.execute(
            """
            SELECT id, start_time, end_time, duration, asr_text, asr_segments, vlm_description
            FROM clips
            WHERE video_id = ?
            ORDER BY start_time ASC, id ASC
            LIMIT ?
            """,
            (vid, int(max_clips)),
        ) as cur:
            clip_rows = await cur.fetchall()

        if not clip_rows:
            raise HTTPException(status_code=400, detail="该视频暂无分片数据，请先完成预处理")

        has_signal = False
        for r in clip_rows:
            if (r["asr_text"] or "").strip():
                has_signal = True
                break
            if _parse_asr_segments_blob(r["asr_segments"]):
                has_signal = True
                break
            if (r["vlm_description"] or "").strip():
                has_signal = True
                break
        if not has_signal:
            raise HTTPException(
                status_code=400,
                detail="未找到可用的 ASR 或 VLM 文本，请先运行 ASR / 画面分析后再试",
            )

        try:
            cfg = await LLMConfig.get_llm_params_with_defaults(db)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    user_msg, meta, included_rows = _build_smart_outline_user_message(list(clip_rows))
    if not included_rows:
        raise HTTPException(
            status_code=400,
            detail="分片内容过长，无法在单次请求内装入上下文。请尝试缩短单个片段或调整预处理分片策略。",
        )

    llm = LLMClient(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        temperature=min(0.4, float(cfg["temperature"])),
        max_tokens=min(8192, int(cfg["max_tokens"])),
        timeout=600.0,
    )
    try:
        raw = await llm.chat(
            [
                {"role": "system", "content": _SMART_OUTLINE_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.35,
            max_tokens=min(8192, int(cfg["max_tokens"])),
        )
    except Exception as e:
        logger.error("smart_outline LLM 失败: %s", e)
        raise HTTPException(status_code=502, detail=f"调用 LLM 失败: {e}") from e

    try:
        data = json.loads(extract_json_object(raw if isinstance(raw, str) else ""))
    except json.JSONDecodeError as e:
        logger.error("smart_outline JSON 解析失败: %s", e)
        raise HTTPException(status_code=502, detail="LLM 返回内容不是合法 JSON") from e

    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="LLM 返回 JSON 格式错误")

    outline_md = (str(data.get("outline_markdown") or "")).strip() or "（模型未返回大纲正文）"
    topics = _parse_smart_outline_topics(data.get("topics"))
    clip_scores = _merge_smart_outline_scores(included_rows, data.get("clip_scores"))

    response = SmartOutlineResponse(
        video_id=vid,
        video_title=video_title,
        outline_markdown=outline_md,
        topics=topics,
        clip_scores=clip_scores,
        meta=meta,
    )

    now = now_iso()
    async with aiosqlite.connect(DB_PATH) as db:
        await upsert_saved_outline(db, video_id=vid, response=response, max_clips=int(max_clips), now=now)
        await db.commit()

    return response, now
