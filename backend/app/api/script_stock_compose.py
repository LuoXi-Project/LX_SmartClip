"""文案素材成片与剪映草稿导出。"""
from __future__ import annotations

import logging
import os
import uuid
from typing import List, Optional

import aiosqlite
from fastapi import HTTPException

from app.api.tts import TTS_AUDIO_DIR, synthesize
from app.core.blocking_pool import run_heavy
from app.core.bgm.auto_bgm import apply_bgm_config_postprocess
from app.core.script_stock.compose import compose_stock_video_sync
from app.core.script_stock.jianying_export import build_script_stock_jianying_zip_sync
from app.db.database import DB_PATH
from app.models.script_stock import ScriptStockComposeRequest, ScriptStockComposeResponse
from app.models.subtitle import JianYingDraftExportResponse, SubtitleStyle
from app.models.tts import SynthesizeRequest
from app.utils.paths import (
    ensure_storage_subpath,
    normalize_jianying_parent_dir,
    storage_public_url_for_file,
    to_stored_path,
)

from app.api.script_stock_shared import load_export_render_opts, online_rels_from_segment, resolve_compose_rows, router

logger = logging.getLogger(__name__)


async def _synthesize_tts_paths(req: ScriptStockComposeRequest) -> List[Optional[str]]:
    tts_paths: List[Optional[str]] = []
    if req.audio_mode in ("tts_only", "mix"):
        for seg in req.segments:
            txt = (seg.text or "").strip()
            if not txt:
                tts_paths.append(None)
                continue
            try:
                res = await synthesize(
                    SynthesizeRequest(
                        text=txt,
                        voice=req.tts_voice,
                        rate=req.tts_rate,
                        volume=req.tts_volume,
                    )
                )
                tts_paths.append(os.path.join(TTS_AUDIO_DIR, res.filename))
            except HTTPException:
                raise
            except Exception as e:
                logger.exception("script-stock TTS failed")
                raise HTTPException(500, detail=f"TTS 合成失败: {e}") from e
    else:
        tts_paths = [None] * len(req.segments)
    return tts_paths


def _validate_multi_clip_tts_only(req: ScriptStockComposeRequest, *, jianying: bool = False) -> None:
    if req.audio_mode == "tts_only":
        return
    for seg in req.segments:
        if seg.kind == "library":
            n = len([x for x in (seg.library_video_ids or []) if str(x).strip()])
            if n > 1:
                msg = (
                    "多段本地素材按顺序拼接仅支持「仅 TTS」模式；导出剪映草稿时请改为单条或切换为仅 TTS。"
                    if jianying
                    else "多段本地素材按顺序拼接仅支持「仅 TTS」模式；使用原声或混合时请每段只选一条素材。"
                )
                raise HTTPException(400, msg)
        elif seg.kind in ("pexels", "pixabay", "unsplash"):
            rels = online_rels_from_segment(seg, seg.kind)
            if len(rels) > 1:
                msg = (
                    f"多段 {seg.kind} 素材按顺序拼接仅支持「仅 TTS」模式；导出剪映草稿时请改为单条或切换为仅 TTS。"
                    if jianying
                    else f"多段 {seg.kind} 素材按顺序拼接仅支持「仅 TTS」模式；使用原声或混合时请每段只选一条文件。"
                )
                raise HTTPException(400, msg)


@router.post("/compose", response_model=ScriptStockComposeResponse)
async def compose_stock(req: ScriptStockComposeRequest) -> ScriptStockComposeResponse:
    if not req.segments:
        raise HTTPException(400, "segments 不能为空")

    _validate_multi_clip_tts_only(req)
    tts_paths = await _synthesize_tts_paths(req)

    async with aiosqlite.connect(DB_PATH) as db:
        rows = await resolve_compose_rows(db, req)
        export_opts = await load_export_render_opts(db)

    base_name = (req.project_name or "stock_clip").replace(" ", "_")[:80]
    unique = f"{base_name}_{uuid.uuid4().hex[:10]}"

    def _sync() -> str:
        texts = [(s.text or "") for s in req.segments]
        return compose_stock_video_sync(
            segment_rows=rows,
            tts_paths=tts_paths,
            audio_mode=req.audio_mode,
            tts_volume_db=float(req.tts_volume_db),
            original_volume_db=float(req.original_volume_db),
            timeline_mode=req.timeline_mode,
            video_extend_policy=req.video_extend_policy,
            material_tts_fill=req.material_tts_fill,
            material_tts_longer=req.material_tts_longer,
            include_subtitle=bool(req.include_subtitle),
            subtitle_style=req.subtitle_style,
            segment_texts=texts,
            export_render_opts=export_opts,
            project_name=unique,
        )

    try:
        final_abs = await run_heavy(_sync)
    except ValueError as e:
        raise HTTPException(400, detail=str(e)) from e
    except Exception as e:
        logger.exception("compose_stock failed")
        raise HTTPException(500, detail=f"成片失败: {e}") from e

    filename = os.path.basename(final_abs)
    public_url = storage_public_url_for_file(final_abs)
    if req.bgm and req.bgm.enabled:
        try:
            mixed_filename, mixed_url = await run_heavy(
                apply_bgm_config_postprocess,
                filename,
                public_url,
                req.bgm.model_dump(),
            )
            filename = mixed_filename
            public_url = mixed_url
        except Exception as e:
            logger.warning("script-stock BGM mix failed, using video without BGM: %s", e)

    rel = (public_url or "").lstrip("/")
    if not rel.startswith("storage/"):
        rel = to_stored_path(final_abs)
    return ScriptStockComposeResponse(
        filename=filename,
        public_url=public_url,
        stored_rel_path=rel,
    )


@router.post("/export-jianying-draft", response_model=JianYingDraftExportResponse)
async def export_jianying_draft_stock(req: ScriptStockComposeRequest) -> JianYingDraftExportResponse:
    if not req.segments:
        raise HTTPException(400, "segments 不能为空")

    if req.audio_mode in ("tts_only", "mix"):
        for idx, seg in enumerate(req.segments):
            if not (seg.text or "").strip():
                raise HTTPException(
                    400,
                    f"导出剪映草稿（配音轨）时，第 {idx + 1} 段须填写配音文案（与「成片可含静音段」不同）。",
                )

    _validate_multi_clip_tts_only(req, jianying=True)

    try:
        tts_paths = await _synthesize_tts_paths(req)

        async with aiosqlite.connect(DB_PATH) as db:
            rows = await resolve_compose_rows(db, req)
            async with db.execute(
                "SELECT value FROM config WHERE key = ?", ("jianying_draft_parent_dir",)
            ) as cur:
                cfg_row = await cur.fetchone()
            jy_parent = (
                normalize_jianying_parent_dir(str(cfg_row[0])) if cfg_row and cfg_row[0] is not None else ""
            )

        base_name = (req.project_name or "stock_clip").replace(" ", "_")[:80]
        unique = f"{base_name}_jy_{uuid.uuid4().hex[:10]}"
        jy_dir = ensure_storage_subpath("jianying_drafts")
        jy_zip = os.path.join(jy_dir, f"{unique}_jianying.zip")

        out_path, out_mode = await run_heavy(
            build_script_stock_jianying_zip_sync,
            segment_rows=rows,
            tts_paths=tts_paths,
            segment_texts=[(s.text or "") for s in req.segments],
            audio_mode=req.audio_mode,
            timeline_mode=req.timeline_mode,
            include_subtitle=bool(req.include_subtitle),
            subtitle_style=req.subtitle_style or SubtitleStyle(),
            project_name=unique,
            tts_audio_dir=TTS_AUDIO_DIR,
            output_zip_path=jy_zip,
            jianying_draft_parent_dir=jy_parent or None,
        )

        if out_mode == "direct":
            return JianYingDraftExportResponse(mode="direct", filename="", url="", local_path=out_path)
        return JianYingDraftExportResponse(
            mode="zip",
            filename=os.path.basename(out_path),
            url=storage_public_url_for_file(out_path),
            local_path="",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("export_jianying_draft_stock failed")
        raise HTTPException(500, detail=f"剪映草稿导出失败: {e}") from e
