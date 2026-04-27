"""auto_edit.py — 自动一键成片 · Plan 规划接口

Phase 1：仅生成结构化 Plan，不负责实际成片渲染。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Dict, List, Set

import aiosqlite
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.blocking_pool import run_heavy
from app.db.database import DB_PATH
from app.core.llm import LLMConfig
from app.core.llm import LLMClient
from app.core.llm.response_utils import extract_json_object
from app.core.auto_edit.plan_generation import call_llm_for_plans
from app.core.auto_edit.segments import ClipCandidate, collect_plan_clip_ids, segments_from_plan
from app.core.auto_edit_v2.plan_compile import (
    build_v0_dsl_from_request,
    build_v0_timelines_from_context,
    compile_timeline_to_plan,
)
from app.core.auto_edit_v2.template_config import (
    get_long_video_events_profile,
    list_templates,
    normalize_content_style,
    normalize_template_preset,
)
from app.core.auto_edit_v2.dsl_generation import call_llm_for_strategy_dsl
from app.core.auto_edit_v2.events_generation import call_llm_for_events_all
from app.core.auto_edit_v2.merge_rank import assign_tiers_and_rank, merge_batches
from app.core.auto_edit_v2.arrange import arrange_timeline_variants
from app.core.bgm.auto_bgm import apply_bgm_postprocess_if_needed
from app.api.copy_gen import _build_video_context_with_recall
from app.models.subtitle import (
    SubtitleStyle,
    GenerateSRTRequest,
    BurnSubtitleRequest,
    ExportOriginalRequest,
)
from app.api.subtitle import execute_burn_subtitle, execute_export_original
from app.models.auto_edit import (
    AutoEditPlanRequest,
    AutoEditPlanResponse,
    AutoEditPlanSessionResponse,
    AutoEditRealizeRequest,
    AutoEditRealizeResponse,
    VoiceoverQuickCutRequest,
)
from app.models.auto_edit_timeline import FinalTimeline, StrategyDSL, TimelineItem
from app.core.auto_edit.voiceover_quick_cut import (
    apply_voiceover_source_timeline_dedupe,
    build_plan_from_clip_groups,
    load_clip_groups_by_videos,
)
from app.core.auto_edit.voiceover_semantic import build_semantic_voiceover_plan

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/auto-edit", tags=["auto-edit"])

_PLAN_STREAM_SESSIONS: Dict[str, AutoEditPlanRequest] = {}
_PLAN_STREAM_CREATED_AT: Dict[str, float] = {}
_PLAN_STREAM_EXPIRE_SEC = 10 * 60

# TODO：后续可将这组任务参数抽成独立结构，避免散落在 request/cfg
def _load_timeline_long_video_cfg(req: AutoEditPlanRequest, cfg: dict) -> None:
    """
    为 auto_edit_v2 注入长视频参数（任务级）：
    - 先按请求里的 content_style 命中默认档位
    - 再用请求里的显式字段覆盖
    不再读取设置页中的 llm_events_*，避免把不同视频任务绑死在全局配置上。
    """
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


async def _expand_timeline_with_llm_copy_if_needed(
    *,
    cfg: dict,
    timeline: FinalTimeline,
    dsl: StrategyDSL,
    mode: str,
    target_duration_sec: int | None,
    user_prompt: str,
    context: str,
) -> FinalTimeline:
    """
    当 timeline 预计时长不足目标时，让 LLM 续写旁白文案并复用素材 clip_id 以补齐时长。
    仅在 auto/voiceover 模式启用，避免 original 模式改写文案。
    """
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
        max_tokens=min(int(cfg.get("max_tokens") or 20480), 4096),
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


@router.get("/templates")
async def list_auto_edit_templates() -> List[Dict[str, str]]:
    """
    模板列表：单一来源来自 template_config 注册表。
    用于前端渲染模板按钮，避免新增模板需要改多处硬编码枚举。
    """
    return list_templates()

def _cleanup_expired_plan_sessions() -> None:
    now = time.time()
    expired = [
        sid
        for sid, created_at in _PLAN_STREAM_CREATED_AT.items()
        if now - created_at > _PLAN_STREAM_EXPIRE_SEC
    ]
    for sid in expired:
        _PLAN_STREAM_CREATED_AT.pop(sid, None)
        _PLAN_STREAM_SESSIONS.pop(sid, None)


def _build_sse_event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _load_video_names(db: aiosqlite.Connection, video_ids: list[str]) -> list[str]:
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


def _build_video_meta_for_plan(*, video_names: list[str], user_prompt: str) -> tuple[str | None, str | None]:
    names = [n.strip() for n in (video_names or []) if n and n.strip()]
    if not names:
        return None, None
    video_title = names[0] if len(names) == 1 else f"{len(names)}个视频合集"
    up = (user_prompt or "").strip()
    prefix = f"用户诉求：{up}；" if up else ""
    materials = "、".join(names[:6]) + (" 等" if len(names) > 6 else "")
    video_description = f"{prefix}素材：{materials}"
    return video_title, video_description


def _compose_plan_title(*, plan_index: int, video_title: str | None) -> str:
    base = f"智能剪辑（Timeline Engine）#{plan_index}"
    vt = (video_title or "").strip()
    return f"{vt} · {base}" if vt else base


def _compose_plan_summary(*, engine_summary: str, video_description: str | None) -> str:
    vd = (video_description or "").strip()
    if not vd:
        return engine_summary
    return f"{vd}\n{engine_summary}"


def _http_exception_for_llm_upstream(exc: BaseException) -> HTTPException | None:
    """
    OpenAI 兼容客户端在上游返回 401/403/5xx 或网络异常时会抛出这些类型。
    此类错误不应被新引擎的「V0 时间轴回退」吞掉，否则前端会误以为方案生成成功。
    """
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


async def _call_llm_for_final_video_meta(
    *,
    cfg: dict,
    context: str,
    user_prompt: str,
    mode: str,
    target_duration_sec: int | None,
) -> tuple[str | None, str | None]:
    """
    生成“成片成品”的标题与描述（用于发布/项目命名），而不是素材文件名。
    返回 (title, description)。失败返回 (None, None)。
    """
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
        import re

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


@router.post("/plan", response_model=AutoEditPlanResponse)
async def generate_auto_edit_plan(req: AutoEditPlanRequest) -> AutoEditPlanResponse:
    """
    基于已处理完成的视频素材（clips + ASR + VLM），生成自动成片的结构化方案（Plan）。

    当前阶段：
    - 不做转场与 BGM 的真实渲染，仅在 Plan 中占位。
    - 不支持复杂的 keep_flags/prev_plan 逻辑，只做最简单的全量新方案。
    """
    if not req.video_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个视频")

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cfg = await LLMConfig.get_llm_params_with_defaults(
                db,
                base_url_key="llm_base_url",
                api_key_key="llm_api_key",
                model_key="llm_model",
                fallback_model_key="vlm_model",
                default_temperature=0.7,
                default_max_tokens=20480,
            )
            _load_timeline_long_video_cfg(req, cfg)
            logger.info("auto_edit 启用新引擎：正在读取上下文")
            video_names = await _load_video_names(db, req.video_ids)
            video_title, video_description = _build_video_meta_for_plan(
                video_names=video_names,
                user_prompt=req.user_prompt,
            )
            context = await _build_video_context_with_recall(
                db,
                req.video_ids,
                user_prompt=req.user_prompt,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("auto_edit 读取上下文失败: %s", e)
        raise HTTPException(status_code=500, detail="读取素材上下文失败")

    # 低侵入升级：启用新引擎时，先走“规则 timeline → 编译回 Plan”（V0 骨架），保持 response_model 不变
    if getattr(req, "use_timeline_engine", False):
        template_preset = normalize_template_preset(getattr(req, "template_preset", None))
        # V1：优先走 DSL(LLM) → Events(LLM 分批) → Merge/Tier → Arrange → Compile
        # 失败则回退 V0（规则 timeline），再失败回退旧逻辑（LLM 直出 Plan）
        try:
            if template_preset:
                logger.info("auto_edit 启用新引擎：模板预设存在，使用 V0 DSL(结构强制)")
                dsl = build_v0_dsl_from_request(
                    req.user_prompt,
                    req.mode,
                    req.target_duration_sec,
                    template_preset=template_preset,
                )
            else:
                logger.info("auto_edit 启用新引擎：正在生成 DSL")
                dsl = await call_llm_for_strategy_dsl(
                    cfg=cfg,
                    user_prompt=req.user_prompt,
                    mode_hint=req.mode,
                    target_duration_sec=req.target_duration_sec,
                )
        except Exception:
            dsl = build_v0_dsl_from_request(
                req.user_prompt, req.mode, req.target_duration_sec, template_preset=template_preset
            )

        try:
            logger.info("auto_edit 启用新引擎：正在生成事件池")
            batches = await call_llm_for_events_all(
                cfg=cfg,
                context=context,
                template_preset=template_preset,
            )
            logger.info("auto_edit 启用新引擎：正在合并事件池")
            merged_events = merge_batches(batches)
            logger.info("auto_edit 启用新引擎：正在分配事件池")
            pool = assign_tiers_and_rank(merged_events)
            logger.info("auto_edit 启用新引擎：正在编排事件池")
            timelines = arrange_timeline_variants(
                pool=pool,
                dsl=dsl,
                mode=req.mode,
                target_duration_sec=req.target_duration_sec,
                num_plans=req.num_plans,
                seed_hint=req.user_prompt,
            )
            timelines = [tl for tl in timelines if tl.items]
            if not timelines:
                raise RuntimeError("timeline empty")
            logger.info("auto_edit 启用新引擎：正在编译时间轴为 Plan")
            final_title, final_desc = await _call_llm_for_final_video_meta(
                cfg=cfg,
                context=context,
                user_prompt=req.user_prompt,
                mode=req.mode,
                target_duration_sec=req.target_duration_sec,
            )
            plans = []
            for i, tl in enumerate(timelines[: max(1, req.num_plans)], 1):
                tl = await _expand_timeline_with_llm_copy_if_needed(
                    cfg=cfg,
                    timeline=tl,
                    dsl=dsl,
                    mode=req.mode,
                    target_duration_sec=req.target_duration_sec,
                    user_prompt=req.user_prompt,
                    context=context,
                )
                plans.append(
                    compile_timeline_to_plan(
                        timeline=tl,
                        dsl=dsl,
                        plan_id=uuid.uuid4().hex[:8],
                        title=(final_title or _compose_plan_title(plan_index=i, video_title=video_title)),
                        summary=(final_desc or _compose_plan_summary(
                            engine_summary="由事件级时间轴编译生成（V1）",
                            video_description=video_description,
                        )),
                        video_title=(final_title or video_title),
                        video_description=(final_desc or video_description),
                        mode=req.mode,
                        allow_cross_video=req.allow_cross_video,
                    )
                )
            return AutoEditPlanResponse(plans=plans)
        except HTTPException:
            raise
        except Exception as e:
            he = _http_exception_for_llm_upstream(e)
            if he is not None:
                raise he
            logger.warning("auto_edit 新引擎 V1 失败，回退 V0 规则时间轴: %s", e)
            timelines = build_v0_timelines_from_context(
                context=context,
                dsl=dsl,
                mode=req.mode,
                num_plans=req.num_plans,
            )
            timelines = [tl for tl in timelines if tl.items]
            if timelines:
                final_title, final_desc = await _call_llm_for_final_video_meta(
                    cfg=cfg,
                    context=context,
                    user_prompt=req.user_prompt,
                    mode=req.mode,
                    target_duration_sec=req.target_duration_sec,
                )
                plans = []
                for i, tl in enumerate(timelines[: max(1, req.num_plans)], 1):
                    tl = await _expand_timeline_with_llm_copy_if_needed(
                        cfg=cfg,
                        timeline=tl,
                        dsl=dsl,
                        mode=req.mode,
                        target_duration_sec=req.target_duration_sec,
                        user_prompt=req.user_prompt,
                        context=context,
                    )
                    plans.append(
                        compile_timeline_to_plan(
                            timeline=tl,
                            dsl=dsl,
                            plan_id=uuid.uuid4().hex[:8],
                            title=(final_title or _compose_plan_title(plan_index=i, video_title=video_title)),
                            summary=(final_desc or _compose_plan_summary(
                                engine_summary="由事件级时间轴编译生成（V0 回退）",
                                video_description=video_description,
                            )),
                            video_title=(final_title or video_title),
                            video_description=(final_desc or video_description),
                            mode=req.mode,
                            allow_cross_video=req.allow_cross_video,
                        )
                    )
                return AutoEditPlanResponse(plans=plans)

            # 最终兜底：回退旧逻辑，避免新引擎缺信息直接失败
            return await call_llm_for_plans(cfg, context, req)

    return await call_llm_for_plans(cfg, context, req)


@router.post("/voiceover-quick-cut", response_model=AutoEditPlanResponse)
async def voiceover_quick_cut_plan(req: VoiceoverQuickCutRequest) -> AutoEditPlanResponse:
    """
    口播快剪（ASR 驱动）：按 clips 表片段级 asr_text 筛选素材，生成单份原声 Plan，可走 /realize 导出。
    """
    if not req.video_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个视频")
    if req.strategy == "semantic":
        up = (req.user_prompt or "").strip()
        if not up:
            raise HTTPException(status_code=400, detail="智能快剪需要填写提示词")

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            placeholders = ",".join(["?"] * len(req.video_ids))
            async with db.execute(
                f"SELECT id FROM videos WHERE id IN ({placeholders})",
                list(req.video_ids),
            ) as cur:
                found_ids = {str(r["id"]) for r in await cur.fetchall()}
            missing = [vid for vid in req.video_ids if vid not in found_ids]
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail=f"以下视频不存在或已删除：{', '.join(missing[:8])}",
                )

            video_names = await _load_video_names(db, req.video_ids)
            groups = await load_clip_groups_by_videos(
                db,
                req.video_ids,
                include_raw_video_fallback=(req.strategy == "audio_activity_fast"),
            )
            llm_cfg: dict | None = None
            if req.strategy == "semantic":
                try:
                    llm_cfg = await LLMConfig.get_llm_params_with_defaults(db)
                    # 语义快剪分块需要“上下文输入 tokens”预算
                    llm_cfg["context_tokens"] = int(
                        await LLMConfig.read_config(db, "llm_max_context_tokens", "128000")
                    )
                    # 长视频兼容参数：内容画像 + 记忆模板 + 分章/锚点
                    llm_cfg["content_style"] = normalize_content_style(
                        await LLMConfig.read_config(db, "llm_content_style", "generic")
                    )
                    llm_cfg["chapter_target_sec"] = int(
                        await LLMConfig.read_config(db, "llm_chapter_target_sec", "150")
                    )
                    llm_cfg["chapter_anchor_min"] = int(
                        await LLMConfig.read_config(db, "llm_chapter_anchor_min", "1")
                    )
                    memory_style_raw = (
                        await LLMConfig.read_config(db, "llm_memory_style", "")
                    ).strip()
                    if memory_style_raw:
                        try:
                            memory_style = json.loads(memory_style_raw)
                            if isinstance(memory_style, dict):
                                llm_cfg["memory_style"] = memory_style
                            else:
                                logger.warning(
                                    "llm_memory_style 不是对象，忽略该配置: %s",
                                    type(memory_style).__name__,
                                )
                        except Exception:
                            logger.warning("llm_memory_style JSON 解析失败，忽略该配置")
                except ValueError as ve:
                    raise HTTPException(
                        status_code=400,
                        detail=f"智能快剪需要可用的 LLM 配置：{ve}",
                    ) from ve
    except HTTPException:
        raise
    except Exception as e:
        logger.error("voiceover_quick_cut 读库失败: %s", e)
        raise HTTPException(status_code=500, detail="读取视频片段失败")

    hint = video_names[0] if len(video_names) == 1 else (f"{len(req.video_ids)} 个视频" if req.video_ids else None)
    if req.strategy == "semantic":
        if not llm_cfg:
            raise HTTPException(status_code=500, detail="内部错误：缺少 LLM 配置")
        try:
            plan = await build_semantic_voiceover_plan(
                clip_groups=groups,
                user_prompt=(req.user_prompt or "").strip(),
                cfg=llm_cfg,
                video_title_hint=hint,
                video_ids_order=list(req.video_ids),
            )
        except RuntimeError as e:
            # 把 LLM 鉴权/调用失败等关键异常透传到前端展示
            raise HTTPException(status_code=502, detail=str(e)) from e
    else:
        build_kwargs = {
            "clip_groups": groups,
            "strategy": req.strategy,
            "video_title_hint": hint,
            "audio_activity_cfg": {
                "db_threshold": float(req.activity_db_threshold),
                "min_silence_sec": float(req.activity_min_silence_sec),
                "min_keep_sec": float(req.activity_min_keep_sec),
                "merge_gap_sec": float(req.activity_merge_gap_sec),
                "head_pad_sec": float(req.activity_head_pad_sec),
                "tail_pad_sec": float(req.activity_tail_pad_sec),
                "keep_ranges": req.activity_keep_ranges,
            },
        }
        if req.strategy == "audio_activity_fast":
            plan = await run_heavy(build_plan_from_clip_groups, **build_kwargs)
        else:
            plan = build_plan_from_clip_groups(**build_kwargs)
    plan = apply_voiceover_source_timeline_dedupe(
        plan, allow_overlaps=req.allow_overlapping_source_timeline
    )
    if not plan.segments:
        if req.strategy == "audio_activity_fast":
            raise HTTPException(
                status_code=400,
                detail="音频粗剪未检测到可保留语音片段：请检查源视频是否有可用音轨，或适当下调阈值后重试",
            )
        raise HTTPException(
            status_code=400,
            detail="没有可保留的片段：请确认已对选中视频跑过 ASR，且至少一个 clip 含有识别文本",
        )
    return AutoEditPlanResponse(plans=[plan])


@router.post("/plan/session", response_model=AutoEditPlanSessionResponse)
async def create_auto_edit_plan_session(req: AutoEditPlanRequest) -> AutoEditPlanSessionResponse:
    if not req.video_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个视频")
    _cleanup_expired_plan_sessions()
    session_id = uuid.uuid4().hex
    _PLAN_STREAM_SESSIONS[session_id] = req
    _PLAN_STREAM_CREATED_AT[session_id] = time.time()
    return AutoEditPlanSessionResponse(
        session_id=session_id,
        stream_url=f"/api/auto-edit/plan/stream?session_id={session_id}",
    )


@router.get("/plan/stream")
async def stream_auto_edit_plan(session_id: str) -> StreamingResponse:
    _cleanup_expired_plan_sessions()
    # 注意：SSE(EventSource) 在网络抖动时会自动重连；如果这里立刻 pop 掉 session，
    # 重连会直接 404，前端会误以为“转发/连接不正常”。
    # 因此改为：流结束（或异常结束）后再清理 session。
    req = _PLAN_STREAM_SESSIONS.get(session_id)
    if req is None:
        raise HTTPException(status_code=404, detail="规划会话不存在或已过期")

    async def event_generator():
        try:
            # 发送一个轻量事件帮助部分代理/浏览器尽快 flush headers
            yield ": ok\n\n"
            yield _build_sse_event("progress", {"stage": "init", "message": "开始读取模型配置"})
            await asyncio.sleep(0)
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    db.row_factory = aiosqlite.Row
                    cfg = await LLMConfig.get_llm_params_with_defaults(
                        db,
                        base_url_key="llm_base_url",
                        api_key_key="llm_api_key",
                        model_key="llm_model",
                        fallback_model_key="vlm_model",
                        default_temperature=0.7,
                        default_max_tokens=20480,
                    )
                    _load_timeline_long_video_cfg(req, cfg)
                    yield _build_sse_event("progress", {"stage": "context", "message": "正在构建素材上下文"})
                    video_names = await _load_video_names(db, req.video_ids)
                    video_title, video_description = _build_video_meta_for_plan(
                        video_names=video_names,
                        user_prompt=req.user_prompt,
                    )
                    context = await _build_video_context_with_recall(
                        db,
                        req.video_ids,
                        user_prompt=req.user_prompt,
                    )
            except ValueError as e:
                yield _build_sse_event("failed", {"message": str(e)})
                return
            except Exception as e:
                logger.error("auto_edit stream 读取上下文失败: %s", e)
                yield _build_sse_event("failed", {"message": "读取素材上下文失败"})
                return

            yield _build_sse_event("progress", {"stage": "llm", "message": "LLM 正在生成候选方案"})
            if getattr(req, "use_timeline_engine", False):
                template_preset = normalize_template_preset(getattr(req, "template_preset", None))
                yield _build_sse_event(
                    "progress",
                    {"stage": "timeline", "message": "新引擎：正在生成 DSL/事件池/时间轴并编译为 Plan"},
                )
                try:
                    if template_preset:
                        dsl = build_v0_dsl_from_request(
                            req.user_prompt,
                            req.mode,
                            req.target_duration_sec,
                            template_preset=template_preset,
                        )
                    else:
                        dsl = await call_llm_for_strategy_dsl(
                            cfg=cfg,
                            user_prompt=req.user_prompt,
                            mode_hint=req.mode,
                            target_duration_sec=req.target_duration_sec,
                        )
                except Exception:
                    dsl = build_v0_dsl_from_request(
                        req.user_prompt,
                        req.mode,
                        req.target_duration_sec,
                        template_preset=template_preset,
                    )

                try:
                    batches = await call_llm_for_events_all(
                        cfg=cfg,
                        context=context,
                        template_preset=template_preset,
                    )
                    merged_events = merge_batches(batches)
                    pool = assign_tiers_and_rank(merged_events)
                    timelines = arrange_timeline_variants(
                        pool=pool,
                        dsl=dsl,
                        mode=req.mode,
                        target_duration_sec=req.target_duration_sec,
                        num_plans=req.num_plans,
                        seed_hint=req.user_prompt,
                    )
                    timelines = [tl for tl in timelines if tl.items]
                    if not timelines:
                        raise RuntimeError("timeline empty")
                    final_title, final_desc = await _call_llm_for_final_video_meta(
                        cfg=cfg,
                        context=context,
                        user_prompt=req.user_prompt,
                        mode=req.mode,
                        target_duration_sec=req.target_duration_sec,
                    )
                    plans = []
                    for i, tl in enumerate(timelines[: max(1, req.num_plans)], 1):
                        tl = await _expand_timeline_with_llm_copy_if_needed(
                            cfg=cfg,
                            timeline=tl,
                            dsl=dsl,
                            mode=req.mode,
                            target_duration_sec=req.target_duration_sec,
                            user_prompt=req.user_prompt,
                            context=context,
                        )
                        plans.append(
                            compile_timeline_to_plan(
                                timeline=tl,
                                dsl=dsl,
                                plan_id=uuid.uuid4().hex[:8],
                                title=(final_title or _compose_plan_title(plan_index=i, video_title=video_title)),
                                summary=(final_desc or _compose_plan_summary(
                                    engine_summary="由事件级时间轴编译生成（V1）",
                                    video_description=video_description,
                                )),
                                video_title=(final_title or video_title),
                                video_description=(final_desc or video_description),
                                mode=req.mode,
                                allow_cross_video=req.allow_cross_video,
                            )
                        )
                    plan_res = AutoEditPlanResponse(plans=plans)
                except HTTPException as e:
                    msg = e.detail if isinstance(e.detail, str) else "生成方案失败"
                    yield _build_sse_event("failed", {"message": msg})
                    return
                except Exception as e:
                    he = _http_exception_for_llm_upstream(e)
                    if he is not None:
                        d = he.detail
                        yield _build_sse_event(
                            "failed",
                            {"message": d if isinstance(d, str) else "LLM 调用失败"},
                        )
                        return
                    logger.warning("auto_edit SSE 新引擎 V1 失败，回退 V0 规则时间轴: %s", e)
                    timelines = build_v0_timelines_from_context(
                        context=context,
                        dsl=dsl,
                        mode=req.mode,
                        num_plans=req.num_plans,
                    )
                    timelines = [tl for tl in timelines if tl.items]
                    if timelines:
                        final_title, final_desc = await _call_llm_for_final_video_meta(
                            cfg=cfg,
                            context=context,
                            user_prompt=req.user_prompt,
                            mode=req.mode,
                            target_duration_sec=req.target_duration_sec,
                        )
                        plans = []
                        for i, tl in enumerate(timelines[: max(1, req.num_plans)], 1):
                            tl = await _expand_timeline_with_llm_copy_if_needed(
                                cfg=cfg,
                                timeline=tl,
                                dsl=dsl,
                                mode=req.mode,
                                target_duration_sec=req.target_duration_sec,
                                user_prompt=req.user_prompt,
                                context=context,
                            )
                            plans.append(
                                compile_timeline_to_plan(
                                    timeline=tl,
                                    dsl=dsl,
                                    plan_id=uuid.uuid4().hex[:8],
                                    title=(final_title or _compose_plan_title(plan_index=i, video_title=video_title)),
                                    summary=(final_desc or _compose_plan_summary(
                                        engine_summary="由事件级时间轴编译生成（V0 回退）",
                                        video_description=video_description,
                                    )),
                                    video_title=(final_title or video_title),
                                    video_description=(final_desc or video_description),
                                    mode=req.mode,
                                    allow_cross_video=req.allow_cross_video,
                                )
                            )
                        plan_res = AutoEditPlanResponse(plans=plans)
                    else:
                        plan_res = await call_llm_for_plans(cfg, context, req)
            else:
                plan_res = await call_llm_for_plans(cfg, context, req)
            yield _build_sse_event(
                "progress",
                {"stage": "done", "message": f"生成完成，共 {len(plan_res.plans)} 个方案"},
            )
            yield _build_sse_event("result", plan_res.model_dump())
        except HTTPException as e:
            msg = e.detail if isinstance(e.detail, str) else "生成方案失败"
            yield _build_sse_event("failed", {"message": msg})
        except Exception as e:
            logger.error("auto_edit stream 未知异常: %s", e)
            yield _build_sse_event("failed", {"message": "生成方案失败"})
        finally:
            _PLAN_STREAM_SESSIONS.pop(session_id, None)
            _PLAN_STREAM_CREATED_AT.pop(session_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # 让反向代理不要缓冲 SSE（即使你以后上了 Nginx/Caddy 也更稳）
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/realize", response_model=AutoEditRealizeResponse)
async def realize_auto_edit_plan(
    req: AutoEditRealizeRequest,
    request: Request,
) -> AutoEditRealizeResponse:
    """
    将一个 Plan 实际转为成片：
    - voiceover 模式：TTS + 字幕 + burn 管线
    - original 模式：保留原声，按段落平均切字幕，调用 export_original

    当前版本：
    - 忽略 Plan.keep_flags / BGM / transition，仅打通基础链路。
    """
    if await request.is_disconnected():
        raise HTTPException(status_code=400, detail="客户端已断开连接")
    plan = req.plan
    if not plan.segments:
        raise HTTPException(status_code=400, detail="Plan 中没有任何 segments")
    if not any(not s.exclude_from_output for s in plan.segments):
        raise HTTPException(status_code=400, detail="所有段落均已标记为弃用，无法成片")

    requested_clip_ids = collect_plan_clip_ids(plan)
    requested_raw_clip_ids = [cid for cid in requested_clip_ids if str(cid).startswith("raw_")]
    valid_clip_ids: Set[str] = set()
    clip_id_to_video: Dict[str, str] = {}
    candidate_videos: Set[str] = set()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # 1) clip_id 预检：友好返回无效 ID 列表
        if requested_clip_ids:
            placeholders = ",".join(["?"] * len(requested_clip_ids))
            async with db.execute(
                f"SELECT id, video_id FROM clips WHERE id IN ({placeholders})",
                requested_clip_ids,
            ) as cur:
                rows = await cur.fetchall()
            for row in rows:
                cid = str(row["id"])
                valid_clip_ids.add(cid)
                clip_id_to_video[cid] = str(row["video_id"])

        invalid_clip_ids = [cid for cid in requested_clip_ids if cid not in valid_clip_ids]
        # raw_<video_id> 为“未预处理视频”虚拟片段：不在 clips 表内，但允许进入后续裁剪链路。
        for rid in requested_raw_clip_ids:
            valid_clip_ids.add(rid)
        invalid_clip_ids = [cid for cid in invalid_clip_ids if cid not in requested_raw_clip_ids]

        # 2) 构造回退候选池（优先 segment.clip_group 的 video_id，其次已命中 clip 的 video_id）
        for seg in plan.segments:
            for ref in seg.clip_group:
                if ref.video_id:
                    candidate_videos.add(ref.video_id)
        for cid in valid_clip_ids:
            vid = clip_id_to_video.get(cid)
            if vid:
                candidate_videos.add(vid)

        candidates: List[ClipCandidate] = []
        candidates_by_video: Dict[str, List[ClipCandidate]] = {}
        if candidate_videos:
            placeholders = ",".join(["?"] * len(candidate_videos))
            async with db.execute(
                f"SELECT id, video_id, start_time, end_time, duration FROM clips "
                f"WHERE video_id IN ({placeholders})",
                list(candidate_videos),
            ) as cur:
                rows = await cur.fetchall()
            for row in rows:
                cand = ClipCandidate(
                    id=str(row["id"]),
                    video_id=str(row["video_id"]),
                    start_time=float(row["start_time"] or 0.0),
                    end_time=float(row["end_time"] or 0.0),
                    duration=float(row["duration"] or 0.0),
                )
                candidates.append(cand)
                candidates_by_video.setdefault(cand.video_id, []).append(cand)

    seg_inputs = await segments_from_plan(
        plan=plan,
        valid_clip_ids=valid_clip_ids,
        candidates_by_video=candidates_by_video,
        all_candidates=candidates,
    )
    if not seg_inputs:
        detail = {
            "message": "Plan 转换后没有有效片段，请检查计划中的 clip_id 是否有效。",
            "invalid_clip_ids": invalid_clip_ids,
        }
        raise HTTPException(status_code=400, detail=detail)

    if invalid_clip_ids:
        logger.warning("realize 检测到无效 clip_id，已尝试自动回退: %s", invalid_clip_ids)

    project_name = req.project_name or f"auto_edit_{plan.plan_id}"

    # 字幕样式：优先使用前端传入，否则回退默认值
    style = req.style or SubtitleStyle()

    # voiceover / auto -> 统一走配音管线（若某段未生成 TTS，会回落到 clip 时长）
    if plan.mode in ("auto", "voiceover"):
        from app.api.subtitle import generate_srt as generate_srt_route

        if req.include_subtitle:
            if await request.is_disconnected():
                raise HTTPException(status_code=400, detail="客户端已断开连接")
            srt_req = GenerateSRTRequest(segments=seg_inputs, style=style, use_tts_timing=True)
            srt_res = await generate_srt_route(srt_req)
            burn_req = BurnSubtitleRequest(
                segments=seg_inputs,
                srt_content=srt_res.srt_content,
                style=style,
                project_name=project_name,
            )
            burn_res = await execute_burn_subtitle(burn_req)
        else:
            if await request.is_disconnected():
                raise HTTPException(status_code=400, detail="客户端已断开连接")
            export_req = ExportOriginalRequest(
                segments=seg_inputs,
                style=style,
                project_name=project_name,
                include_subtitle=False,
                normalize_audio=True,
            )
            export_res = await execute_export_original(export_req)
            burn_res = {
                "filename": export_res.get("filename"),
                "url": export_res.get("url"),
            }
        if await request.is_disconnected():
            raise HTTPException(status_code=400, detail="客户端已断开连接")
        final_filename, final_url = await run_heavy(
            apply_bgm_postprocess_if_needed,
            plan,
            burn_res["filename"],
            burn_res["url"],
        )
        return AutoEditRealizeResponse(mode="voiceover", filename=final_filename, url=final_url)

    export_req = ExportOriginalRequest(
        segments=seg_inputs,
        style=style,
        project_name=project_name,
        include_subtitle=req.include_subtitle,
        normalize_audio=True,
    )
    if await request.is_disconnected():
        raise HTTPException(status_code=400, detail="客户端已断开连接")
    res = await execute_export_original(export_req)
    if await request.is_disconnected():
        raise HTTPException(status_code=400, detail="客户端已断开连接")
    final_filename, final_url = await run_heavy(
        apply_bgm_postprocess_if_needed,
        plan,
        res.get("filename") or "",
        res.get("url") or "",
    )
    return AutoEditRealizeResponse(mode="original", filename=final_filename, url=final_url)

