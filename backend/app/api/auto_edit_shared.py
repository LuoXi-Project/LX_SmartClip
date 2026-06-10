"""auto_edit 路由与共用辅助函数。"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Dict, List, Optional

import aiosqlite
from fastapi import APIRouter, HTTPException

from app.core.llm import LLMClient
from app.core.llm.response_utils import extract_json_object
from app.core.auto_edit_v2.template_config import (
    get_long_video_events_profile,
    normalize_content_style,
)
from app.models.auto_edit import AutoEditPlanRequest, Plan
from app.models.auto_edit_timeline import FinalTimeline, StrategyDSL, TimelineItem
from app.models.subtitle import TtsVideoAlignConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auto-edit", tags=["auto-edit"])

_PLAN_STREAM_SESSIONS: Dict[str, AutoEditPlanRequest] = {}
_PLAN_STREAM_CREATED_AT: Dict[str, float] = {}
_PLAN_STREAM_EXPIRE_SEC = 10 * 60


def resolve_fine_grain_split(
    *,
    tts_align: Optional[TtsVideoAlignConfig],
    plan: Optional[Plan] = None,
) -> bool:
    """True=按逗号/短句拆条；False=仅句号/换行。优先请求里的 tts_align，其次方案 constraints。"""
    if tts_align is not None:
        return bool(tts_align.split_narration_by_sentence)
    if (
        plan is not None
        and plan.constraints is not None
        and plan.constraints.split_narration_by_sentence is not None
    ):
        return bool(plan.constraints.split_narration_by_sentence)
    return False


def load_timeline_long_video_cfg(req: AutoEditPlanRequest, cfg: dict) -> None:
    """为 auto_edit_v2 注入长视频参数（任务级）。"""
    content_style = normalize_content_style(getattr(req, "content_style", None) or "generic")
    cfg["content_style"] = content_style
    defaults = get_long_video_events_profile(content_style)
    cfg["events_max_clips_per_batch"] = max(
        5,
        int(getattr(req, "events_max_clips_per_batch", None) or defaults["events_max_clips_per_batch"]),
    )
    cfg["events_max_chars_per_batch"] = max(
        4000,
        int(getattr(req, "events_max_chars_per_batch", None) or defaults["events_max_chars_per_batch"]),
    )
    cfg["events_batch_overlap_clips"] = max(
        0,
        int(getattr(req, "events_batch_overlap_clips", None) or defaults["events_batch_overlap_clips"]),
    )
    cfg["events_max_batches"] = max(
        1,
        int(getattr(req, "events_max_batches", None) or defaults["events_max_batches"]),
    )


async def expand_timeline_with_llm_copy_if_needed(
    *,
    cfg: dict,
    timeline: FinalTimeline,
    dsl: StrategyDSL,
    mode: str,
    target_duration_sec: int | None,
    user_prompt: str,
    context: str,
) -> FinalTimeline:
    """当 timeline 预计时长不足目标时，让 LLM 续写旁白文案并复用素材 clip_id。"""
    if mode not in ("auto", "voiceover"):
        return timeline
    target = float(target_duration_sec or dsl.target_duration_sec or 0.0)
    if target <= 0:
        return timeline
    current = float(sum((it.duration_budget_sec or 0.0) for it in timeline.items))
    if current >= target * 0.92:
        return timeline
    if not timeline.items:
        return timeline

    remain = max(0.0, target - current)
    if remain < 6.0:
        return timeline

    clip_ids = [it.clip_id for it in timeline.items if it.clip_id]
    if not clip_ids:
        return timeline

    llm = LLMClient(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        temperature=0.45,
        max_tokens=min(int(cfg.get("max_tokens") or 20480), 65536),
        timeout=3600,
    )
    base_script = [str(it.subtitle_text or "").strip() for it in timeline.items if str(it.subtitle_text or "").strip()]
    preset = str(getattr(dsl, "template_preset", "") or "")
    domain = "通用解说"
    structure_hint = "保持叙事连贯与信息递进。"
    if "film" in preset:
        domain = "影视解说"
        structure_hint = "按铺垫-冲突-转折-高潮-余韵推进，允许留白和悬念。"
    elif "scene" in preset:
        domain = "场景剧情"
        structure_hint = "突出场景变化、人物关系推进与情绪变化。"
    elif "short" in preset:
        domain = "短视频口播"
        structure_hint = "保持节奏紧凑，重点明确，结尾有行动引导。"
    sys = (
        f"你是{domain}续写助手。目标：在不重复原句的前提下，续写新的旁白文案以补齐目标时长。"
        "你只能输出 JSON，不要解释。"
    )
    user = (
        f"【用户诉求】\n{(user_prompt or '').strip()}\n\n"
        f"【内容域】{domain}\n"
        f"【风格节奏】pace={dsl.style.pace}, tone={dsl.style.tone}\n"
        f"【结构约束】{structure_hint}\n"
        f"【目标补齐时长】{int(remain)} 秒\n\n"
        "【已有文案（禁止逐句重复）】\n"
        + "\n".join([f"- {x}" for x in base_script[:30]])
        + "\n\n【素材摘要】\n"
        + (context or "")[:3000]
        + "\n\n请输出 JSON："
        + '{"segments":[{"text":"续写旁白句","duration_sec":5.0}]}'
    )
    raw = await llm.chat([{"role": "system", "content": sys}, {"role": "user", "content": user}])
    cleaned = extract_json_object(raw if isinstance(raw, str) else "")
    try:
        data = json.loads(cleaned)
    except Exception:
        return timeline
    segs = data.get("segments") if isinstance(data, dict) else None
    if not isinstance(segs, list) or not segs:
        return timeline

    next_items = list(timeline.items)
    extra_total = 0.0
    seq = 0
    for s in segs:
        if not isinstance(s, dict):
            continue
        text = str(s.get("text") or "").strip()
        if not text:
            continue
        try:
            dur = float(s.get("duration_sec") or 0.0)
        except Exception:
            dur = 0.0
        if dur <= 0.0:
            dur = 4.5 if dsl.style.pace == "fast" else 6.0
        remain2 = max(0.0, remain - extra_total)
        if remain2 <= 0.0:
            break
        dur = max(1.0, min(dur, remain2))
        clip_id = clip_ids[seq % len(clip_ids)]
        seq += 1
        next_items.append(
            TimelineItem(
                event_id=f"llm_ext_{seq}",
                clip_id=clip_id,
                subtitle_text=text,
                audio_mode="tts" if mode in ("auto", "voiceover") else "original",
                duration_budget_sec=dur,
            )
        )
        extra_total += dur
        if extra_total >= remain * 0.98:
            break

    total = float(sum((it.duration_budget_sec or 0.0) for it in next_items))
    return FinalTimeline(items=next_items, total_duration_sec_est=total if total > 0 else None)


def cleanup_expired_plan_sessions() -> None:
    now = time.time()
    expired = [
        sid
        for sid, created_at in _PLAN_STREAM_CREATED_AT.items()
        if now - created_at > _PLAN_STREAM_EXPIRE_SEC
    ]
    for sid in expired:
        _PLAN_STREAM_CREATED_AT.pop(sid, None)
        _PLAN_STREAM_SESSIONS.pop(sid, None)


def build_sse_event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def load_video_names(db: aiosqlite.Connection, video_ids: list[str]) -> list[str]:
    if not video_ids:
        return []
    placeholders = ",".join(["?"] * len(video_ids))
    sql = f"SELECT id, name FROM videos WHERE id IN ({placeholders})"
    async with db.execute(sql, video_ids) as cur:
        rows = await cur.fetchall()
    id_to_name = {str(r["id"]): str(r["name"] or "") for r in rows}
    out: list[str] = []
    for vid in video_ids:
        name = (id_to_name.get(str(vid)) or "").strip()
        if name:
            out.append(name)
    return out


def build_video_meta_for_plan(*, video_names: list[str], user_prompt: str) -> tuple[str | None, str | None]:
    names = [n.strip() for n in (video_names or []) if n and n.strip()]
    if not names:
        return None, None
    video_title = names[0] if len(names) == 1 else f"{len(names)}个视频合集"
    up = (user_prompt or "").strip()
    prefix = f"用户诉求：{up}；" if up else ""
    materials = "、".join(names[:6]) + (" 等" if len(names) > 6 else "")
    video_description = f"{prefix}素材：{materials}"
    return video_title, video_description


def compose_plan_title(*, plan_index: int, video_title: str | None) -> str:
    base = f"智能剪辑（Timeline Engine）#{plan_index}"
    vt = (video_title or "").strip()
    return f"{vt} · {base}" if vt else base


def compose_plan_summary(*, engine_summary: str, video_description: str | None) -> str:
    vd = (video_description or "").strip()
    if not vd:
        return engine_summary
    return f"{vd}\n{engine_summary}"


def http_exception_for_llm_upstream(exc: BaseException) -> HTTPException | None:
    try:
        from openai import APIConnectionError, APIStatusError, AuthenticationError
    except ImportError:
        return None
    if isinstance(exc, AuthenticationError):
        return HTTPException(status_code=502, detail=f"LLM 鉴权失败：{exc}")
    if isinstance(exc, APIStatusError):
        return HTTPException(status_code=502, detail=f"LLM 接口错误：{exc}")
    if isinstance(exc, APIConnectionError):
        return HTTPException(status_code=502, detail=f"LLM 网络异常：{exc}")
    return None


async def call_llm_for_final_video_meta(
    *,
    cfg: dict,
    context: str,
    user_prompt: str,
    mode: str,
    target_duration_sec: int | None,
) -> tuple[str | None, str | None]:
    try:
        llm = LLMClient(
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            model=cfg["model"],
            temperature=0.4,
            max_tokens=20480,
            timeout=3600,
        )
        sys = (
            "你是短视频剪辑成片的发布文案助手。\n"
            "你将收到：素材内容摘要（台词/画面）、用户诉求、成片模式与目标时长。\n"
            "任务：为“最终成片”生成一个标题(title)与一个基本描述(description)。\n"
            "要求：\n"
            "- title：15~30字，吸引人但不要夸张，不要包含文件名/ID/时间戳。\n"
            "- description：1~3句，概括主题+亮点+结构/节奏，可提及风格；不要复述素材列表。\n"
            "- 不要输出 Markdown，不要解释；只输出 JSON：{\"title\":\"...\",\"description\":\"...\"}\n"
        )
        user = (
            f"【用户诉求】\n{(user_prompt or '').strip()}\n\n"
            f"【成片模式】{mode}\n"
            f"【目标时长】{target_duration_sec or ''}\n\n"
            f"【素材内容摘要】\n{(context or '').strip()}\n"
        )
        raw = await llm.chat(
            [
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ]
        )
        if not isinstance(raw, str) or not raw.strip():
            return None, None
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", raw, flags=re.IGNORECASE).strip()
        s = cleaned.find("{")
        e = cleaned.rfind("}")
        if s != -1 and e != -1 and e > s:
            cleaned = cleaned[s : e + 1]
        data = json.loads(cleaned)
        if not isinstance(data, dict):
            return None, None
        title = str(data.get("title") or "").strip() or None
        desc = str(data.get("description") or "").strip() or None
        return title, desc
    except Exception:
        return None, None
