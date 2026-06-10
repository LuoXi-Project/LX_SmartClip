"""Plan 成片与剪映草稿导出。"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set

import aiosqlite
from fastapi import HTTPException, Request

from app.core.auto_edit.mix_postprocess import apply_mix_overlay_if_needed
from app.core.auto_edit.segments import ClipCandidate, collect_plan_clip_ids, segments_from_plan
from app.core.bgm.auto_bgm import apply_bgm_postprocess_if_needed
from app.core.blocking_pool import run_heavy
from app.core.jianying.export_pipeline import export_jianying_draft_zip_async
from app.core.postprod.pipeline import apply_postprod_master_if_needed
from app.core.postprod.profile import resolve_production_profile, style_with_production
from app.core.subtitle.tts_align import apply_timeline_duration_overrides
from app.db.database import DB_PATH
from app.models.auto_edit import (
    AutoEditExportJianyingDraftRequest,
    AutoEditRealizeRequest,
    AutoEditRealizeResponse,
    Plan,
)
from app.models.subtitle import (
    BurnSubtitleRequest,
    ExportOriginalRequest,
    GenerateSRTRequest,
    JianYingDraftExportResponse,
    SubtitleStyle,
    TtsVideoAlignConfig,
)
from app.api.subtitle import TTS_AUDIO_DIR, execute_burn_subtitle, execute_export_original

from app.api.auto_edit_shared import resolve_fine_grain_split, router

logger = logging.getLogger(__name__)


async def prepare_auto_edit_segments_from_plan(
    *,
    plan: Plan,
    project_name: Optional[str],
    style: Optional[SubtitleStyle],
    force_tts_pipeline: bool,
    tts_align: Optional[TtsVideoAlignConfig],
) -> tuple[list, SubtitleStyle, str, bool]:
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
        fail_fast_on_tts_error=use_tts_branch and plan_has_tts_segments,
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


# 兼容旧 import 路径
_prepare_auto_edit_segments_from_plan = prepare_auto_edit_segments_from_plan


async def _run_realize_postprocess(
    plan: Plan,
    filename: str,
    url: str,
    profile,
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
    return final_filename, final_url


@router.post("/realize", response_model=AutoEditRealizeResponse)
async def realize_auto_edit_plan(
    req: AutoEditRealizeRequest,
    request: Request,
) -> AutoEditRealizeResponse:
    if await request.is_disconnected():
        raise HTTPException(status_code=400, detail="客户端已断开连接")
    plan = req.plan
    profile = resolve_production_profile(
        explicit=req.production_profile,
        plan=plan,
    )
    logger.info("realize production: %s", profile.human_summary())

    seg_inputs, style, project_name, use_tts_branch = await prepare_auto_edit_segments_from_plan(
        plan=plan,
        project_name=req.project_name,
        style=req.style,
        force_tts_pipeline=req.force_tts_pipeline,
        tts_align=req.tts_align,
    )
    style = style_with_production(style, profile)
    align_cfg = req.tts_align

    if use_tts_branch:
        from app.api.subtitle import generate_srt as generate_srt_route

        fine_grain = resolve_fine_grain_split(tts_align=align_cfg, plan=plan)

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
            burn_req = BurnSubtitleRequest(
                segments=seg_inputs,
                srt_content=srt_res.srt_content,
                style=style,
                project_name=project_name,
                tts_align=align_cfg,
                require_tts_audio=True,
                production_profile=profile,
            )
            burn_res = await execute_burn_subtitle(burn_req)
        else:
            if await request.is_disconnected():
                raise HTTPException(status_code=400, detail="客户端已断开连接")
            burn_req = BurnSubtitleRequest(
                segments=seg_inputs,
                srt_content="",
                style=style,
                project_name=project_name,
                tts_align=align_cfg,
                require_tts_audio=True,
                production_profile=profile,
            )
            burn_res = await execute_burn_subtitle(burn_req)
        if await request.is_disconnected():
            raise HTTPException(status_code=400, detail="客户端已断开连接")
        final_filename, final_url = burn_res["filename"], burn_res["url"]
        final_filename, final_url = await _run_realize_postprocess(
            plan, final_filename, final_url, profile
        )
        return AutoEditRealizeResponse(
            mode="voiceover",
            filename=final_filename,
            url=final_url,
        )

    export_req = ExportOriginalRequest(
        segments=seg_inputs,
        style=style,
        project_name=project_name,
        include_subtitle=req.include_subtitle,
        normalize_audio=True,
        production_profile=profile,
    )
    if await request.is_disconnected():
        raise HTTPException(status_code=400, detail="客户端已断开连接")
    res = await execute_export_original(export_req)
    if await request.is_disconnected():
        raise HTTPException(status_code=400, detail="客户端已断开连接")
    final_filename, final_url = res.get("filename") or "", res.get("url") or ""
    final_filename, final_url = await _run_realize_postprocess(
        plan, final_filename, final_url, profile
    )
    return AutoEditRealizeResponse(
        mode="original",
        filename=final_filename,
        url=final_url,
    )


@router.post("/export-jianying-draft", response_model=JianYingDraftExportResponse)
async def export_jianying_draft_from_plan(
    req: AutoEditExportJianyingDraftRequest,
    request: Request,
) -> JianYingDraftExportResponse:
    if await request.is_disconnected():
        raise HTTPException(status_code=400, detail="客户端已断开连接")
    try:
        plan = req.plan
        seg_inputs, style, project_name, use_tts_branch = await prepare_auto_edit_segments_from_plan(
            plan=plan,
            project_name=req.project_name,
            style=req.style,
            force_tts_pipeline=req.force_tts_pipeline,
            tts_align=req.tts_align,
        )
        if use_tts_branch:
            from app.api.subtitle import generate_srt as generate_srt_route

            align_cfg = req.tts_align
            fine_grain = resolve_fine_grain_split(tts_align=align_cfg, plan=plan)

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
