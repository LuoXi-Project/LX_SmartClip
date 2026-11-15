"""auto_edit.py — 自动一键成片 · Plan 规划接口

Phase 1：仅生成结构化 Plan，不负责实际成片渲染。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Dict, List, Optional, Set

import aiosqlite
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.core.blocking_pool import run_heavy
from app.jobs import create_job, JobReporter, launch_job, update_job_status
from app.db.database import DB_PATH
from app.core.llm import LLMConfig
from app.core.llm import LLMClient
from app.core.llm.response_utils import extract_json_object
from app.core.auto_edit.plan_audio import finalize_plan_audio
from app.core.auto_edit.plan_generation import call_llm_for_plans
from app.core.auto_edit.segments import ClipCandidate, collect_plan_clip_ids, segments_from_plan
from app.core.auto_edit_v2.plan_compile import (
    build_v0_dsl_from_request,
    build_v0_timelines_from_context,
    compile_timeline_to_plan,
)
from app.core.auto_edit_v2.plan_quality import sort_plans_by_quality
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
from app.core.auto_edit.mix_anti_detect import apply_mix_anti_detect_if_needed
from app.core.auto_edit.mix_postprocess import apply_mix_overlay_if_needed
from app.core.postprod.pipeline import apply_postprod_master_if_needed
from app.core.postprod.profile import resolve_production_profile, style_with_production
from app.api.copy_gen import _build_video_context_with_recall
from app.models.subtitle import (
    BurnSubtitleRequest,
    ExportOriginalRequest,
    GenerateSRTRequest,
    JianYingDraftExportResponse,
    SubtitleStyle,
    TtsVideoAlignConfig,
)
from app.api.subtitle import TTS_AUDIO_DIR, execute_burn_subtitle, execute_export_original
from app.core.jianying.export_pipeline import export_jianying_draft_zip_async
from app.core.subtitle.tts_align import apply_timeline_duration_overrides
from app.models.auto_edit import (
    AutoEditExportJianyingDraftRequest,
    AutoEditPlanRequest,
    AutoEditPlanResponse,
    AutoEditPlanSessionResponse,
    AutoEditRealizeRequest,
    AutoEditRealizeResponse,
    Constraints,
    MixEditPlanRequest,
    Plan,
    VideoDubPlanRequest,
    VoiceoverQuickCutRequest,
)

from app.models.auto_edit_timeline import FinalTimeline, StrategyDSL, TimelineItem
from app.core.auto_edit.voiceover_quick_cut import (
    apply_voiceover_source_timeline_dedupe,
    build_plan_from_clip_groups,
    load_clip_groups_by_videos,
)
from app.core.auto_edit.voiceover_semantic import build_semantic_voiceover_plan
from app.core.auto_edit.mix_edit import (
    _segment_playback_duration_sec,
    apply_shot_boundary_refine_to_plan,
    build_mix_edit_plan,
    resolve_mix_clip_rows,
    trim_mix_segments_to_target,
)
from app.core.auto_edit.mix_edit_tts_balance import rebalance_mix_tts_voiceover_plan
from app.core.auto_edit.mix_edit_llm_copy import apply_llm_scripts_to_mute_plan
from app.core.auto_edit.video_dub import (
    apply_video_dub_llm_rewrite,
    apply_video_dub_vlm_narration,
    build_video_dub_plan,
    load_video_dub_clips,
)

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/auto-edit", tags=["auto-edit"])

_PLAN_STREAM_SESSIONS: Dict[str, AutoEditPlanRequest] = {}
_PLAN_STREAM_CREATED_AT: Dict[str, float] = {}
_PLAN_STREAM_EXPIRE_SEC = 10 * 60



def _resolve_fine_grain_split(
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




def _finalize_plans_response(resp: AutoEditPlanResponse) -> AutoEditPlanResponse:
    resp.plans = [finalize_plan_audio(pl) for pl in resp.plans]
    return resp

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

        pool = None
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
                        pool=pool,
                    )
                )
            return _finalize_plans_response(AutoEditPlanResponse(plans=sort_plans_by_quality(plans)))
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
                            pool=None,
                        )
                    )
                return _finalize_plans_response(AutoEditPlanResponse(plans=sort_plans_by_quality(plans)))

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
                    # 口播快剪句头/句尾补偿（保留说话间隙）
                    llm_cfg["head_pad_sec"] = float(req.asr_head_pad_sec)
                    llm_cfg["tail_pad_sec"] = float(req.asr_tail_pad_sec)
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
            from app.core.auto_edit.duration_hint import resolve_voiceover_target_duration_sec

            resolved_target_sec = resolve_voiceover_target_duration_sec(
                explicit_sec=req.target_duration_sec,
                user_prompt=(req.user_prompt or "").strip(),
            )
            plan = await build_semantic_voiceover_plan(
                clip_groups=groups,
                user_prompt=(req.user_prompt or "").strip(),
                cfg=llm_cfg,
                video_title_hint=hint,
                video_ids_order=list(req.video_ids),
                target_duration_sec=resolved_target_sec,
            )
        except RuntimeError as e:
            # 把 LLM 鉴权/调用失败等关键异常透传到前端展示
            raise HTTPException(status_code=502, detail=str(e)) from e
    else:
        resolved_target_sec = None
        if req.strategy == "standard":
            from app.core.auto_edit.duration_hint import resolve_voiceover_target_duration_sec

            resolved_target_sec = resolve_voiceover_target_duration_sec(
                explicit_sec=req.target_duration_sec,
                user_prompt=(req.user_prompt or "").strip(),
            )
        build_kwargs = {
            "clip_groups": groups,
            "strategy": req.strategy,
            "video_title_hint": hint,
            "target_duration_sec": resolved_target_sec,
            "audio_activity_cfg": {
                "db_threshold": float(req.activity_db_threshold),
                "min_silence_sec": float(req.activity_min_silence_sec),
                "min_keep_sec": float(req.activity_min_keep_sec),
                "merge_gap_sec": float(req.activity_merge_gap_sec),
                "head_pad_sec": float(req.activity_head_pad_sec),
                "tail_pad_sec": float(req.activity_tail_pad_sec),
                "keep_ranges": req.activity_keep_ranges,
            },
            "head_pad_sec": float(req.asr_head_pad_sec),
            "tail_pad_sec": float(req.asr_tail_pad_sec),
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
    return _finalize_plans_response(AutoEditPlanResponse(plans=[plan]))


async def _load_mix_edit_clips(
    db: aiosqlite.Connection,
    video_ids: List[str],
) -> list[aiosqlite.Row | dict[str, object]]:
    """加载混剪所需 clip（含 vlm_description），按视频顺序 + 片内时间排序。

    未预处理（无 clips 表记录）时，回退为原视频单段虚拟 clip（raw_<video_id>），
    供音量活动检测切分；成片侧已兼容 raw_ 片段 ID。
    """
    all_rows: list[aiosqlite.Row | dict[str, object]] = []
    for vid in video_ids:
        async with db.execute(
            "SELECT id, video_id, clip_path, start_time, duration, asr_text, asr_segments, vlm_description "
            "FROM clips WHERE video_id = ? ORDER BY start_time ASC, id ASC",
            (vid,),
        ) as cur:
            rows = await cur.fetchall()
        if rows:
            all_rows.extend(rows)
            continue

        async with db.execute(
            "SELECT id, file_path, duration FROM videos WHERE id = ?",
            (vid,),
        ) as cur:
            vrow = await cur.fetchone()
        if not vrow:
            continue
        all_rows.append(
            {
                "id": f"raw_{vid}",
                "video_id": str(vrow["id"]),
                "clip_path": str(vrow["file_path"] or ""),
                "start_time": 0.0,
                "duration": float(vrow["duration"] or 0.0),
                "asr_text": None,
                "asr_segments": None,
                "vlm_description": None,
            }
        )
    return all_rows


@router.post("/mix-edit-plan", response_model=AutoEditPlanResponse)
async def mix_edit_plan(req: MixEditPlanRequest) -> AutoEditPlanResponse:
    """
    混剪方案：两大顶层模式（保留原声 / 关闭全部原声）。
    素材按 ASR/VLM 四级分级编排；未预处理视频无 clip 时回退整段原片并按音量活动切分。
    """
    if not req.video_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个视频")
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
            clip_rows = await _load_mix_edit_clips(db, list(req.video_ids))
            video_names = await _load_video_names(db, list(req.video_ids))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("mix_edit_plan 读库失败: %s", e)
        raise HTTPException(status_code=500, detail="读取视频片段失败")

    if not clip_rows:
        raise HTTPException(
            status_code=400,
            detail="所选视频下没有 clip：请先在素材处理中完成切分/识别",
        )

    hint = video_names[0] if len(video_names) == 1 else (
        f"{len(req.video_ids)} 个视频" if req.video_ids else None
    )
    try:
        clip_rows, filter_note = resolve_mix_clip_rows(clip_rows, req.clip_filter)
        plan = build_mix_edit_plan(
            clip_rows=clip_rows,
            mix_audio_mode=req.mix_audio_mode,
            mute_audio_track=req.mute_audio_track,
            video_title_hint=hint,
            target_duration_sec=req.target_duration_sec,
            postprocess=req.postprocess,
            filter_note=filter_note,
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve

    if req.mix_audio_mode == "mute_all_original" and req.mute_audio_track == "ai_tts_llm":
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                llm_cfg = await LLMConfig.get_llm_params_with_defaults(db)
                plan = await apply_llm_scripts_to_mute_plan(
                    plan=plan,
                    db=db,
                    video_ids=list(req.video_ids),
                    user_prompt=(req.user_prompt or "").strip(),
                    llm_cfg=llm_cfg,
                    target_duration_sec=req.target_duration_sec,
                )
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve)) from ve
        except RuntimeError as re:
            raise HTTPException(status_code=502, detail=str(re)) from re
        except Exception as e:
            logger.error("mix_edit LLM 文案生成失败: %s", e)
            raise HTTPException(status_code=502, detail=f"AI 生成旁白文案失败: {e}") from e

    if req.mix_audio_mode == "mute_all_original" and req.mute_audio_track in (
        "ai_tts_llm",
        "ai_tts_asr",
        "ai_tts",
    ):
        split_narration = False
        if req.tts_align is not None:
            split_narration = bool(req.tts_align.split_narration_by_sentence)
        plan = rebalance_mix_tts_voiceover_plan(
            plan,
            clip_rows,
            mute_audio_track=req.mute_audio_track,
            split_narration=split_narration,
        )
        if req.mute_audio_track == "ai_tts_llm":
            plan = apply_shot_boundary_refine_to_plan(plan, clip_rows)

    split_flag = False
    if req.tts_align is not None:
        split_flag = bool(req.tts_align.split_narration_by_sentence)
    base_c = plan.constraints or Constraints()
    plan = plan.model_copy(
        update={
            "constraints": base_c.model_copy(
                update={"split_narration_by_sentence": split_flag}
            )
        }
    )

    if req.target_duration_sec and float(req.target_duration_sec) > 0:
        trimmed, trim_note = trim_mix_segments_to_target(
            plan.segments, float(req.target_duration_sec)
        )
        if trim_note:
            total_after = sum(
                _segment_playback_duration_sec(s)
                for s in trimmed
                if not s.exclude_from_output
            )
            summary = plan.summary or ""
            if "已按目标时长" not in summary:
                summary = f"{summary} {trim_note}".strip()
            plan = plan.model_copy(
                update={
                    "segments": trimmed,
                    "estimated_duration_sec": round(total_after, 2)
                    if total_after > 0
                    else None,
                    "summary": summary,
                }
            )

    if not plan.segments:
        raise HTTPException(
            status_code=400,
            detail="混剪方案为空：请确认素材已处理，且至少有一段可用画面",
        )
    return _finalize_plans_response(AutoEditPlanResponse(plans=[plan]))


_MIX_ASSET_VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".avi")
_MIX_ASSET_AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")


@router.post("/mix-upload-asset")
async def mix_upload_asset(
    file: UploadFile = File(...),
    kind: str = "auto",
) -> dict:
    """
    混剪覆盖视频 / 用户 BGM 上传，保存至 storage/mix_assets，返回可用于 plan 的路径。
    kind: overlay | bgm | auto（按扩展名推断）
    """
    from app.utils.paths import ensure_storage_subpath

    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    name = file.filename
    lower = name.lower()
    k = (kind or "auto").strip().lower()
    if k == "auto":
        if lower.endswith(_MIX_ASSET_VIDEO_EXT):
            k = "overlay"
        elif lower.endswith(_MIX_ASSET_AUDIO_EXT):
            k = "bgm"
        else:
            raise HTTPException(status_code=400, detail="无法识别文件类型，请传 mp4/mov 或 mp3/wav 等")
    if k == "overlay" and not lower.endswith(_MIX_ASSET_VIDEO_EXT):
        raise HTTPException(status_code=400, detail="覆盖视频请上传 mp4/mov 等视频文件")
    if k == "bgm" and not lower.endswith(_MIX_ASSET_AUDIO_EXT):
        raise HTTPException(status_code=400, detail="BGM 请上传 mp3/wav/m4a 等音频文件")

    dest_dir = ensure_storage_subpath("mix_assets")
    safe_name = f"{uuid.uuid4().hex[:8]}_{name}"
    dest_path = os.path.join(dest_dir, safe_name)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="文件为空")
    with open(dest_path, "wb") as f:
        f.write(content)
    rel = os.path.join("storage", "mix_assets", safe_name).replace("\\", "/")
    return {"path": dest_path, "stored_path": rel, "filename": safe_name, "kind": k}


@router.post("/video-dub-plan", response_model=AutoEditPlanResponse)
async def video_dub_plan(req: VideoDubPlanRequest) -> AutoEditPlanResponse:
    """
    视频配音：按原片 clip/ASR 时间轴生成 TTS 方案，不重新混剪编排。
    需素材具备 ASR 和/或 VLM；洗稿/画面解说可走 LLM。
    """
    if not req.video_ids:
        raise HTTPException(status_code=400, detail="请至少选择一个视频")

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
            clip_rows = await load_video_dub_clips(db, list(req.video_ids))
            video_names = await _load_video_names(db, list(req.video_ids))
    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except Exception as e:
        logger.error("video_dub_plan 读库失败: %s", e)
        raise HTTPException(status_code=500, detail="读取视频片段失败")

    if not clip_rows:
        raise HTTPException(
            status_code=400,
            detail="所选视频下没有 clip：请先在素材处理中完成切分/识别",
        )

    hint = video_names[0] if len(video_names) == 1 else (
        f"{len(req.video_ids)} 个视频" if req.video_ids else None
    )
    try:
        plan = build_video_dub_plan(
            clip_rows=clip_rows,
            content_source=req.content_source,
            video_title_hint=hint,
            preserve_gaps=req.preserve_gaps,
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve

    has_vlm_tts = any(
        s.audio_mode == "tts" and s.subtitle.source == "vlm"
        for s in plan.segments
        if not s.exclude_from_output
    )
    needs_llm = req.content_source in ("asr_rewrite", "vlm_narrate") or (
        req.content_source == "auto" and has_vlm_tts
    )
    if needs_llm or (req.user_prompt or "").strip():
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                llm_cfg = await LLMConfig.get_llm_params_with_defaults(db)
            up = (req.user_prompt or "").strip()
            if req.content_source == "asr_rewrite":
                plan = await apply_video_dub_llm_rewrite(
                    plan=plan,
                    user_prompt=up,
                    llm_cfg=llm_cfg,
                )
            elif req.content_source == "vlm_narrate":
                plan = await apply_video_dub_vlm_narration(
                    plan=plan,
                    user_prompt=up,
                    llm_cfg=llm_cfg,
                )
            elif req.content_source == "auto":
                if up:
                    plan = await apply_video_dub_llm_rewrite(
                        plan=plan,
                        user_prompt=up,
                        llm_cfg=llm_cfg,
                    )
                if has_vlm_tts or up:
                    plan = await apply_video_dub_vlm_narration(
                        plan=plan,
                        user_prompt=up,
                        llm_cfg=llm_cfg,
                    )
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve)) from ve
        except RuntimeError as re:
            raise HTTPException(status_code=502, detail=str(re)) from re
        except Exception as e:
            logger.error("video_dub LLM 文案失败: %s", e)
            raise HTTPException(status_code=502, detail=f"生成配音文案失败: {e}") from e

    split_flag = False
    if req.tts_align is not None:
        split_flag = bool(req.tts_align.split_narration_by_sentence)
    base_c = plan.constraints or Constraints()
    plan = plan.model_copy(
        update={
            "constraints": base_c.model_copy(
                update={"split_narration_by_sentence": split_flag}
            )
        }
    )

    if not plan.segments:
        raise HTTPException(status_code=400, detail="配音方案为空")

    # 未传对齐策略时，视频配音默认「保留画面时长」
    if req.tts_align is None:
        plan = plan.model_copy(
            update={
                "summary": (plan.summary or "")
                + " 成片对齐：保留画面时长（可在导出前于面板修改）。",
            }
        )
    return _finalize_plans_response(AutoEditPlanResponse(plans=[plan]))


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

                pool = None
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
                                pool=pool,
                            )
                        )
                    plan_res = AutoEditPlanResponse(plans=sort_plans_by_quality(plans))
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
                                    pool=pool,
                                )
                            )
                        plan_res = AutoEditPlanResponse(plans=sort_plans_by_quality(plans))
                    else:
                        # 带心跳：LLM 调用可能耗时 30-60s
                        _hb_timeline = asyncio.ensure_future(call_llm_for_plans(cfg, context, req))
                        while True:
                            _done_hbt, _ = await asyncio.wait([_hb_timeline], timeout=10.0)
                            if _hb_timeline.done():
                                plan_res = _hb_timeline.result()
                                break
                            yield f": heartbeat: LLM 方案生成中...\n\n"

            else:
                # 带心跳：LLM 调用可能耗时 30-60s
                _hb_fallback = asyncio.ensure_future(call_llm_for_plans(cfg, context, req))
                while True:
                    _done_hbf, _ = await asyncio.wait([_hb_fallback], timeout=10.0)
                    if _hb_fallback.done():
                        plan_res = _hb_fallback.result()
                        break
                    yield f": heartbeat: LLM 方案生成中...\n\n"

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


async def _prepare_auto_edit_segments_from_plan(
    *,
    plan: Plan,
    project_name: Optional[str],
    style: Optional[SubtitleStyle],
    force_tts_pipeline: bool,
    tts_align: Optional[TtsVideoAlignConfig],
) -> tuple[list, SubtitleStyle, str, bool]:
    """Plan → segments_from_plan + TTS 对齐覆盖；供 realize 与剪映草稿导出复用。"""
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
        for rid in requested_raw_clip_ids:
            valid_clip_ids.add(rid)
        invalid_clip_ids = [cid for cid in invalid_clip_ids if cid not in requested_raw_clip_ids]

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

    active_plan_segments = [s for s in plan.segments if not s.exclude_from_output]
    plan_has_tts_segments = any(s.audio_mode == "tts" for s in active_plan_segments)
    use_tts_branch = (
        bool(force_tts_pipeline)
        or plan.mode == "voiceover"
        or plan_has_tts_segments
    )

    seg_inputs = await segments_from_plan(
        plan=plan,
        valid_clip_ids=valid_clip_ids,
        candidates_by_video=candidates_by_video,
        all_candidates=candidates,
        force_tts=bool(force_tts_pipeline),
        fail_fast_on_tts_error=use_tts_branch and (plan_has_tts_segments or bool(force_tts_pipeline)),
    )
    if not seg_inputs:
        detail = {
            "message": "Plan 转换后没有有效片段，请检查计划中的 clip_id 是否有效。",
            "invalid_clip_ids": invalid_clip_ids,
        }
        raise HTTPException(status_code=400, detail=detail)

    if invalid_clip_ids:
        logger.warning("auto_edit Plan→segments 检测到无效 clip_id，已尝试自动回退: %s", invalid_clip_ids)

    apply_timeline_duration_overrides(seg_inputs, tts_align, TTS_AUDIO_DIR)

    if (
        tts_align is not None
        and str(tts_align.policy) == "loop_playlist_to_cover"
        and plan.constraints
        and plan.constraints.mix_playlist_clip_ids
    ):
        pl = [c for c in plan.constraints.mix_playlist_clip_ids if c in valid_clip_ids]
        if pl:
            tts_align = tts_align.model_copy(update={"playlist_clip_ids": pl})
            logger.info("混剪轮播：注入全量播放列表 %d 条 clip", len(pl))

    resolved_name = project_name or f"auto_edit_{plan.plan_id}"
    resolved_style = style or SubtitleStyle()

    return seg_inputs, resolved_style, resolved_name, use_tts_branch


async def _run_realize_postprocess(
    plan: Plan,
    filename: str,
    url: str,
    profile,
    srt_content: str = "",
) -> tuple[str, str]:
    final_filename, final_url = await run_heavy(
        apply_mix_overlay_if_needed,
        plan,
        filename,
        url,
    )
    final_filename, final_url = await run_heavy(
        apply_postprod_master_if_needed,
        plan=plan,
        filename=final_filename,
        url=final_url,
        production_profile=profile,
    )
    duck = profile.audio.ducking if profile else "off"
    final_filename, final_url = await run_heavy(
        apply_bgm_postprocess_if_needed,
        plan,
        final_filename,
        final_url,
        ducking=duck,
    )
    final_filename, final_url = await run_heavy(
        apply_mix_anti_detect_if_needed,
        plan,
        final_filename,
        final_url,
    )
    # 动效字幕（HyperFrames）：字幕层透明 WebM 渲染后 ffmpeg 叠加（ASS 已在渲染时跳过）
    caps = getattr(profile, "captions", None)
    if caps is not None and getattr(caps, "engine", "ass") == "hyperframes" and (srt_content or "").strip():
        from app.core.motion.caption_render import apply_hyperframes_captions

        final_filename, final_url = await apply_hyperframes_captions(
            final_filename,
            final_url,
            srt_content=srt_content,
            style_slug=getattr(caps, "style", "karaoke-hormozi") or "karaoke-hormozi",
            params=dict(getattr(caps, "params", {}) or {}),
        )
    return final_filename, final_url


async def _launch_realize_job(req: AutoEditRealizeRequest) -> str:
    """把 Plan 落地成片：创建 realize 后台 job 并启动，返回 job_id。

    供 /realize 端点与工作流 realize_plan 动作共用。
    """
    job = await create_job(kind="realize", initial_step="prepare")
    job_id = job["id"]

    plan = req.plan
    profile = resolve_production_profile(explicit=req.production_profile, plan=plan)
    align_cfg = req.tts_align

    seg_inputs, style, project_name, use_tts_branch = await _prepare_auto_edit_segments_from_plan(
        plan=plan, project_name=req.project_name, style=req.style,
        force_tts_pipeline=req.force_tts_pipeline, tts_align=align_cfg,
    )
    style = style_with_production(style, profile)

    async def _run():
        reporter = JobReporter(job_id)
        try:
            # 动效字幕引擎：ASS 跳过，SRT 交给后处理链的 HyperFrames 叠加
            hf_captions = (
                getattr(profile, "captions", None) is not None
                and getattr(profile.captions, "engine", "ass") == "hyperframes"
                and bool(req.include_subtitle)
            )
            hf_srt = ""
            if use_tts_branch:
                from app.api.subtitle import generate_srt as generate_srt_route
                fine_grain = _resolve_fine_grain_split(tts_align=align_cfg, plan=plan)
                await reporter.send("render", "running", "正在合成 TTS 成片...")
                if req.include_subtitle:
                    srt_req = GenerateSRTRequest(segments=seg_inputs, style=style, use_tts_timing=True, split_narration_by_sentence=fine_grain)
                    srt_res = await generate_srt_route(srt_req)
                    burn_srt = "" if hf_captions else srt_res.srt_content
                    hf_srt = srt_res.srt_content if hf_captions else ""
                    burn_req = BurnSubtitleRequest(segments=seg_inputs, srt_content=burn_srt, style=style, project_name=project_name, tts_align=align_cfg, require_tts_audio=True, production_profile=profile)
                    burn_res = await execute_burn_subtitle(burn_req)
                else:
                    burn_req = BurnSubtitleRequest(segments=seg_inputs, srt_content="", style=style, project_name=project_name, tts_align=align_cfg, require_tts_audio=True, production_profile=profile)
                    burn_res = await execute_burn_subtitle(burn_req)
                final_filename, final_url = burn_res["filename"], burn_res["url"]
                await reporter.send("postprocess", "running", "正在后期处理...")
                final_filename, final_url = await _run_realize_postprocess(plan, final_filename, final_url, profile, srt_content=hf_srt)
            else:
                await reporter.send("render", "running", "正在导出原声成片...")
                if hf_captions:
                    # 原声分支的动效字幕：按原声时间生成 SRT，导出时跳过 ASS
                    from app.api.subtitle import generate_srt as generate_srt_route
                    srt_res = await generate_srt_route(GenerateSRTRequest(segments=seg_inputs, style=style, use_tts_timing=False))
                    hf_srt = srt_res.srt_content
                export_req = ExportOriginalRequest(segments=seg_inputs, style=style, project_name=project_name, include_subtitle=req.include_subtitle and not hf_captions, normalize_audio=True, production_profile=profile)
                res = await execute_export_original(export_req)
                final_filename = res.get("filename") or ""
                final_url = res.get("url") or ""
                await reporter.send("postprocess", "running", "正在后期处理...")
                final_filename, final_url = await _run_realize_postprocess(plan, final_filename, final_url, profile, srt_content=hf_srt)
            result = {"mode": "voiceover" if use_tts_branch else "original", "filename": final_filename, "url": final_url}
            # 记录成片到 renders 表（异步，不阻塞返回）
            _vid = getattr(getattr(plan, "video_id", None), "__str__", lambda: None)()
            asyncio.create_task(_record_realize(final_url, _vid, plan))

            await update_job_status(job_id, "done", result=result)
            await reporter.send("done", "done", "成片已就绪", {"result": result})
        except Exception as e:
            logger.exception("realize job %s failed", job_id)
            await reporter.send("error", "error", "成片落地失败: " + str(e))
            await update_job_status(job_id, "error", error_message=str(e))
    launch_job(job_id, _run())
    return job_id


@router.post("/realize")
async def realize_auto_edit_plan(
    req: AutoEditRealizeRequest,
    request: Request,
):
    """将一个 Plan 实际转为成片 -> 后台任务，返回 job_id。"""
    job_id = await _launch_realize_job(req)
    return {"job_id": job_id, "status": "running", "stream_url": f"/api/jobs/{job_id}/stream", "ws_url": f"/api/jobs/{job_id}/ws"}


async def _record_realize(public_url: str, material_id: str | None, plan=None) -> None:
    """把 realize 成片记录到 renders 表。从 public_url 反解绝对路径。

    同时携带原素材标题（material_id → videos.name）与方案/方案内容快照（plan），
    供「一键发布」AI 文案生成时无需回查原任务即可拿到上下文。
    """
    try:
        from app.api.renders_db import record_render_from_path, extract_plan_snapshot
        from app.utils.paths import resolve_stored_path
        abs_path = resolve_stored_path(public_url)
        # 取原素材标题
        material_title = None
        if material_id:
            try:
                from app.db.database import get_db_conn
                db = await get_db_conn()
                try:
                    cur = await db.execute("SELECT name FROM videos WHERE id = ?", (material_id,))
                    row = await cur.fetchone()
                    if row:
                        material_title = row["name"]
                finally:
                    await db.close()
            except Exception:
                logger.debug("查询原素材标题失败（忽略）", exc_info=True)
        plan_json = None
        snap = extract_plan_snapshot(plan)
        if snap:
            import json as _json
            plan_json = _json.dumps(snap, ensure_ascii=False)
        await record_render_from_path(
            abs_path=abs_path, source="realize", material_id=material_id,
            material_title=material_title, plan_json=plan_json,
        )
    except Exception:
        logger.debug("记录 realize 成片失败（忽略）", exc_info=True)


@router.post("/export-jianying-draft", response_model=JianYingDraftExportResponse)
async def export_jianying_draft_from_plan(
    req: AutoEditExportJianyingDraftRequest,
    request: Request,
) -> JianYingDraftExportResponse:
    """仅导出剪映草稿 ZIP，不调用 burn / export_original。"""
    if await request.is_disconnected():
        raise HTTPException(status_code=400, detail="客户端已断开连接")
    try:
        plan = req.plan
        seg_inputs, style, project_name, use_tts_branch = await _prepare_auto_edit_segments_from_plan(
            plan=plan,
            project_name=req.project_name,
            style=req.style,
            force_tts_pipeline=req.force_tts_pipeline,
            tts_align=req.tts_align,
        )
        if use_tts_branch:
            from app.api.subtitle import generate_srt as generate_srt_route

            align_cfg = req.tts_align
            fine_grain = _resolve_fine_grain_split(tts_align=align_cfg, plan=plan)

            if req.include_subtitle:
                if await request.is_disconnected():
                    raise HTTPException(status_code=400, detail="客户端已断开连接")
                srt_req = GenerateSRTRequest(
                    segments=seg_inputs,
                    style=style,
                    use_tts_timing=True,
                    split_narration_by_sentence=fine_grain,
                )
                srt_res = await generate_srt_route(srt_req)
                srt_content = srt_res.srt_content
            else:
                srt_content = ""
            return await export_jianying_draft_zip_async(
                segments=seg_inputs,
                mode="tts",
                project_name_base=project_name,
                tts_audio_dir=TTS_AUDIO_DIR,
                style=style,
                client_srt_content=srt_content,
                strict_use_client_srt=False,
                include_subtitle=True,
            )
        return await export_jianying_draft_zip_async(
            segments=seg_inputs,
            mode="original",
            project_name_base=project_name,
            tts_audio_dir=TTS_AUDIO_DIR,
            style=style,
            client_srt_content="",
            strict_use_client_srt=False,
            include_subtitle=req.include_subtitle,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("export_jianying_draft_from_plan failed")
        raise HTTPException(status_code=500, detail=f"剪映草稿导出失败: {e}") from e
