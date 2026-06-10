"""口播快剪、混剪、视频配音等变体 Plan 路由。"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import List

import aiosqlite
from fastapi import File, HTTPException, UploadFile

from app.core.auto_edit.mix_edit import (
    apply_shot_boundary_refine_to_plan,
    build_mix_edit_plan,
    resolve_mix_clip_rows,
)
from app.core.auto_edit.mix_edit_llm_copy import apply_llm_scripts_to_mute_plan
from app.core.auto_edit.mix_edit_tts_balance import rebalance_mix_tts_voiceover_plan
from app.core.auto_edit.voiceover_quick_cut import (
    apply_voiceover_source_timeline_dedupe,
    build_plan_from_clip_groups,
    load_clip_groups_by_videos,
)
from app.core.auto_edit.voiceover_semantic import build_semantic_voiceover_plan
from app.core.auto_edit.video_dub import (
    apply_video_dub_llm_rewrite,
    apply_video_dub_vlm_narration,
    build_video_dub_plan,
    load_video_dub_clips,
)
from app.core.blocking_pool import run_heavy
from app.core.auto_edit_v2.template_config import normalize_content_style
from app.core.llm import LLMConfig
from app.db.database import DB_PATH
from app.models.auto_edit import (
    AutoEditPlanResponse,
    Constraints,
    MixEditPlanRequest,
    VideoDubPlanRequest,
    VoiceoverQuickCutRequest,
)

from app.api.auto_edit_shared import load_video_names, router

logger = logging.getLogger(__name__)

_MIX_ASSET_VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".avi")
_MIX_ASSET_AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")


@router.post("/voiceover-quick-cut", response_model=AutoEditPlanResponse)
async def voiceover_quick_cut_plan(req: VoiceoverQuickCutRequest) -> AutoEditPlanResponse:
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

            video_names = await load_video_names(db, req.video_ids)
            groups = await load_clip_groups_by_videos(
                db,
                req.video_ids,
                include_raw_video_fallback=(req.strategy == "audio_activity_fast"),
            )
            llm_cfg: dict | None = None
            if req.strategy == "semantic":
                try:
                    llm_cfg = await LLMConfig.get_llm_params_with_defaults(db)
                    llm_cfg["context_tokens"] = int(
                        await LLMConfig.read_config(db, "llm_max_context_tokens", "128000")
                    )
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


async def _load_mix_edit_clips(db: aiosqlite.Connection, video_ids: List[str]) -> list[aiosqlite.Row]:
    all_rows: list[aiosqlite.Row] = []
    for vid in video_ids:
        async with db.execute(
            "SELECT id, video_id, clip_path, start_time, duration, asr_text, asr_segments, vlm_description "
            "FROM clips WHERE video_id = ? ORDER BY start_time ASC, id ASC",
            (vid,),
        ) as cur:
            all_rows.extend(await cur.fetchall())
    return all_rows


@router.post("/mix-edit-plan", response_model=AutoEditPlanResponse)
async def mix_edit_plan(req: MixEditPlanRequest) -> AutoEditPlanResponse:
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
            video_names = await load_video_names(db, list(req.video_ids))
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

    if not plan.segments:
        raise HTTPException(
            status_code=400,
            detail="混剪方案为空：请确认素材已处理，且至少有一段可用画面",
        )
    return AutoEditPlanResponse(plans=[plan])


@router.post("/mix-upload-asset")
async def mix_upload_asset(
    file: UploadFile = File(...),
    kind: str = "auto",
) -> dict:
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
            video_names = await load_video_names(db, list(req.video_ids))
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

    if req.tts_align is None:
        plan = plan.model_copy(
            update={
                "summary": (plan.summary or "")
                + " 成片对齐：保留画面时长（可在导出前于面板修改）。",
            }
        )
    return AutoEditPlanResponse(plans=[plan])
