"""subtitle.py — SRT字幕生成 & 烧录 路由层（薄封装，业务逻辑见 core/subtitle）"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import List
from urllib.parse import quote

import aiosqlite
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.models.subtitle import (
    BurnSubtitleRequest,
    BurnSubtitleResponse,
    ExportOriginalRequest,
    GenerateSRTRequest,
    GenerateSRTResponse,
    SRTEntry,
    SubtitleSegmentInput,
    SubtitleStyle,  # noqa: F401 - 用于模块级 re-export
)

from app.core.blocking_pool import run_heavy
from app.db.database import DB_PATH
from app.utils.paths import ensure_storage_subpath, get_fonts_dir, get_storage_root, resolve_stored_path, storage_public_url_for_file
from app.core.subtitle.srt import build_srt, parse_srt
from app.core.subtitle.timeline import (
    resolve_durations,
    rule_timeline,
    rule_timeline_equal_units,
    rule_timeline_weighted_chars,
)
from app.core.subtitle.burn import burn_to_mp4
from app.core.bgm.auto_bgm import apply_bgm_config_postprocess

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/subtitle", tags=["subtitle"])

TTS_AUDIO_DIR = os.path.abspath(os.path.join(os.path.dirname(DB_PATH), "tts_audio"))

_FONTS_DIR = get_fonts_dir()

def _burned_output_dir_for_clip_rows(rows: list) -> str:
    """由 clips 行得到烧录输出目录 ``storage/<video_id>/burned_videos/``。"""
    video_ids = {str(r["video_id"]) for r in rows if r["video_id"]}
    if len(video_ids) != 1:
        raise HTTPException(400, "segments 中的片段必须属于同一素材视频")
    material_id = next(iter(video_ids))
    return ensure_storage_subpath(material_id, "burned_videos")


async def _get_config_value(db, key: str, default: str) -> str:
    cur = await db.execute("SELECT value FROM config WHERE key = ?", (key,))
    row = await cur.fetchone()
    return row["value"] if row and row["value"] is not None else default


async def _load_render_opts(db) -> dict:
    """读取切片/预处理用 FFmpeg 参数（可含 copy，追求速度）。"""
    keys = [
        "clip_vcodec",
        "clip_acodec",
        "clip_preset",
        "clip_crf",
        "clip_video_bitrate_kbps",
        "clip_audio_bitrate_kbps",
        "clip_g",
        "clip_keyint_min",
        "clip_sc_threshold",
        "clip_fps",
        "clip_scale_width",
        "clip_scale_height",
        "clip_pix_fmt",
        "clip_container",
    ]
    opts = {}
    for key in keys:
        opts[key] = await _get_config_value(db, key, "")
    return opts


async def _load_export_render_opts(db) -> dict:
    """读取成片导出专用参数（最终 concat+烧录；与切片分离）。"""
    keys = [
        "export_vcodec",
        "export_acodec",
        "export_preset",
        "export_crf",
        "export_video_bitrate_kbps",
        "export_audio_bitrate_kbps",
        "export_g",
        "export_keyint_min",
        "export_sc_threshold",
        "export_fps",
        "export_scale_width",
        "export_scale_height",
        "export_pix_fmt",
        "export_container",
        "export_gpu",
    ]
    opts = {}
    for key in keys:
        opts[key] = await _get_config_value(db, key, "")
    return opts


async def _load_export_backend(db) -> str:
    v = (await _get_config_value(db, "export_backend", "moviepy")) or "moviepy"
    v = v.strip().lower()
    return v if v in ("ffmpeg", "moviepy") else "moviepy"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
#
# 注：Pydantic 模型已拆到 `app.models.subtitle`，此处通过 import
# 进行模块级 re-export，避免破坏其它代码的导入路径。

# ---------------------------------------------------------------------------
# Route: 生成 SRT 时间轴
# ---------------------------------------------------------------------------

@router.post("/generate", response_model=GenerateSRTResponse)
async def generate_srt(req: GenerateSRTRequest):
    """生成SRT时间轴，按TTS音频时长严格切分并对齐。"""
    if not req.segments:
        raise HTTPException(400, "segments不能为空")

    ids: List[str] = []
    for seg in req.segments:
        if seg.clip_id:
            ids.append(seg.clip_id)
        if seg.clip_ids:
            ids.extend([cid for cid in seg.clip_ids if cid])
    ids = list(dict.fromkeys(ids))
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT id,duration FROM clips WHERE id IN ({','.join(['?']*len(ids))})", ids
        ) as cur:
            rows = await cur.fetchall()

    clip_dur = {r["id"]: float(r["duration"] or 5.0) for r in rows}
    max_chars = req.style.max_chars_per_line if req.style else 20

    durs, src = resolve_durations(req.segments, clip_dur, TTS_AUDIO_DIR, req.use_tts_timing)

    # 一键成片默认走规则法，确保字幕与配音时长完全可控，避免 LLM 对齐偏差。
    # 启用 TTS timing 时：段内按字数权重分配时长，更贴近匀速配音。
    if req.use_tts_timing:
        raw_entries = rule_timeline_weighted_chars(req.segments, durs, max_chars)
    else:
        raw_entries = rule_timeline(req.segments, durs, max_chars)

    logger.warning(f"raw_entries: {raw_entries}")

    out = [
        SRTEntry(
            index=i,
            start=float(e.get("start", 0)),
            end=float(e.get("end", 1)),
            text=str(e.get("text", "")),
            clip_id=str(e.get("clip_id", "")),
        )
        for i, e in enumerate(raw_entries, 1)
    ]
    srt = build_srt([{"start": e.start, "end": e.end, "text": e.text} for e in out])
    return GenerateSRTResponse(
        srt_content=srt,
        entries=out,
        total_duration=max((e.end for e in out), default=0.0),
        timing_source=src,
    )


# ---------------------------------------------------------------------------
# 烧录 / 原声导出 · 可执行体（供 HTTP 路由与 auto_edit 等内部调用）
# ---------------------------------------------------------------------------


async def execute_burn_subtitle(req: BurnSubtitleRequest) -> dict:
    """合并视频 + 替换 TTS 音轨 + 硬烧字幕；重 CPU/ffmpeg 走专用线程池。"""
    if not req.segments:
        raise HTTPException(400, "segments不能为空")

    ids: List[str] = []
    for seg in req.segments:
        if seg.clip_id:
            ids.append(seg.clip_id)
        if seg.clip_ids:
            ids.extend([cid for cid in seg.clip_ids if cid])
    ids = list(dict.fromkeys(ids))
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT id, video_id, clip_path, duration FROM clips WHERE id IN ({','.join(['?']*len(ids))})",
            ids,
        ) as cur:
            rows = await cur.fetchall()
        render_opts = await _load_render_opts(db)
        export_render_opts = await _load_export_render_opts(db)
        export_backend_cfg = await _load_export_backend(db)

    if not rows:
        raise HTTPException(400, "未找到片段数据，请检查 clip_id 是否有效")

    burn_output_dir = _burned_output_dir_for_clip_rows(list(rows))

    clip_map = {
        r["id"]: {"path": resolve_stored_path(r["clip_path"]), "dur": float(r["duration"] or 5)}
        for r in rows
    }
    clip_dur = {cid: float(info.get("dur") or 5.0) for cid, info in clip_map.items()}

    # 兜底一致性：一键成片场景下，字幕默认与 TTS 音频“强绑定”。
    # 若前端传来的 srt_content 与当前 segments 的 TTS 时长/结构不一致（过期/编辑导致），
    # 则在烧录阶段按 TTS 时长重新生成时间轴，确保最终成片字幕对齐配音。
    #
    # 若 strict_use_client_srt=True：完全按传入 SRT 烧录（不做任何校验/重建）。
    client_srt_raw = (req.srt_content or "").strip()
    srt_entries = parse_srt(client_srt_raw)
    subtitle_enabled = bool(client_srt_raw)
    try:
        if getattr(req, "strict_use_client_srt", False):
            raise RuntimeError("严格使用客户端SRT功能；跳过重建")
        if not subtitle_enabled:
            raise RuntimeError("由于srt_content为空，字幕已禁用；跳过重建")

        tts_durs, _src = resolve_durations(req.segments, clip_dur, TTS_AUDIO_DIR, use_tts=True)
        expected_total = float(sum(float(x or 0.0) for x in tts_durs) or 0.0)

        def _needs_rebuild(entries: list, *, expected_total_sec: float) -> bool:
            if expected_total_sec <= 0.1:
                return False
            if not entries:
                return True

            # 基础合法性检查
            last_end = 0.0
            for e in entries:
                try:
                    st = float(e.get("start", 0.0) or 0.0)
                    ed = float(e.get("end", 0.0) or 0.0)
                except Exception:
                    return True
                if st < -0.001 or ed <= st:
                    return True
                if st + 0.001 < last_end:
                    return True
                last_end = max(last_end, ed)

            srt_total = float(max((e.get("end", 0.0) for e in entries), default=0.0) or 0.0)
            # 更严格的阈值：生成/烧录两端都按 ffprobe(TTS) 取时长，理论上差值应很小
            if abs(expected_total_sec - srt_total) > 0.15:
                return True
            # 覆盖不足也重建（避免字幕提前结束）
            if srt_total + 0.10 < expected_total_sec:
                return True
            # 若字幕明显超出音频，也重建（避免尾部“空字幕”）
            if srt_total - expected_total_sec > 0.20:
                return True
            return False

        if _needs_rebuild(srt_entries, expected_total_sec=expected_total):
            max_chars = req.style.max_chars_per_line if req.style else 20
            rebuilt_entries = rule_timeline_weighted_chars(req.segments, tts_durs, max_chars)
            rebuilt_srt = build_srt(
                [{"start": e["start"], "end": e["end"], "text": e["text"]} for e in rebuilt_entries]
            )
            logger.warning(
                "烧录阶段已按 TTS 重建时间轴: srt=%.3fs expected_tts=%.3fs",
                float(max((e.get("end", 0.0) for e in srt_entries), default=0.0) or 0.0),
                expected_total,
            )
            srt_entries = parse_srt(rebuilt_srt)
    except Exception as e:
        # strict_use_client_srt 会主动走到这里：属于预期行为，不输出 warning 降噪。
        if getattr(req, "strict_use_client_srt", False):
            logger.info("strict_use_client_srt=True，烧录阶段跳过字幕时间轴校验/重建")
        elif not subtitle_enabled:
            logger.info("srt_content 为空，视为未启用字幕；烧录阶段跳过字幕时间轴校验/重建")
        else:
            logger.warning("烧录阶段校验/重建字幕时间轴失败，继续使用原 srt_content: %s", e)

    logger.info("烧录: %d 段, %d 条字幕", len(req.segments), len(srt_entries))

    # 生成唯一的项目名，避免文件覆盖
    unique_project_name = f"{req.project_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    _, saved_path = await run_heavy(
        burn_to_mp4,
        segments=req.segments,
        srt_entries=srt_entries,
        clip_map=clip_map,
        style=req.style,
        project_name=unique_project_name,
        tts_audio_dir=TTS_AUDIO_DIR,
        fonts_dir=_FONTS_DIR,
        render_opts=render_opts,
        export_render_opts=export_render_opts,
        render_mode="tts",
        export_backend=(req.export_backend or export_backend_cfg),
        output_dir=burn_output_dir,
    )

    if not saved_path or not os.path.exists(saved_path):
        raise HTTPException(500, "字幕烧录失败")

    filename = os.path.basename(saved_path)
    logger.info("烧录完成，已保存: %s", saved_path)
    result = {
        "filename": filename,
        "url": storage_public_url_for_file(saved_path),
    }
    if req.bgm and req.bgm.enabled:
        mixed_filename, mixed_url = await run_heavy(
            apply_bgm_config_postprocess,
            result["filename"],
            result["url"],
            req.bgm.model_dump(),
        )
        result["filename"] = mixed_filename
        result["url"] = mixed_url
    return result


async def execute_export_original(req: ExportOriginalRequest) -> dict:
    """
    原声拼接导出（可选字幕）；ffmpeg 走专用线程池。
    """
    if not req.segments:
        raise HTTPException(400, "segments不能为空")

    ids: List[str] = []
    for seg in req.segments:
        if seg.clip_id:
            ids.append(seg.clip_id)
        if seg.clip_ids:
            ids.extend([cid for cid in seg.clip_ids if cid])
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise HTTPException(400, "segments 缺少 clip_id/clip_ids")

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT id, video_id, clip_path, duration FROM clips WHERE id IN ({','.join(['?']*len(ids))})",
            ids,
        ) as cur:
            rows = await cur.fetchall()
        render_opts = await _load_render_opts(db)
        export_render_opts = await _load_export_render_opts(db)
        export_backend_cfg = await _load_export_backend(db)

    if not rows:
        raise HTTPException(400, "未找到片段数据，请检查 clip_id 是否有效")

    burn_output_dir = _burned_output_dir_for_clip_rows(list(rows))

    clip_map = {
        r["id"]: {"path": resolve_stored_path(r["clip_path"]), "dur": float(r["duration"] or 5)}
        for r in rows
    }
    clip_dur = {cid: float(info["dur"] or 5) for cid, info in clip_map.items()}

    # 每段（segments 内每个 seg 对应的“段落”）总时长 = 该段选中 clip 组时长之和
    seg_durs: List[float] = []
    for seg in req.segments:
        manual_dur = getattr(seg, "duration_sec", None)
        try:
            manual_dur_v = float(manual_dur) if manual_dur is not None else None
        except Exception:
            manual_dur_v = None
        if manual_dur_v is not None and manual_dur_v > 0:
            seg_durs.append(manual_dur_v)
            continue
        raw_ids = list(getattr(seg, "clip_ids", None) or [])
        if not raw_ids and getattr(seg, "clip_id", None):
            raw_ids = [seg.clip_id]
        group_ids = list(dict.fromkeys([cid for cid in raw_ids if cid]))
        trims = getattr(seg, "clip_trims", None)
        if trims and group_ids:
            by_cid: dict[str, float] = {}
            for t in trims:
                try:
                    by_cid[str(t.clip_id)] = float(t.duration_sec)
                except Exception:
                    continue
            total_tr = 0.0
            for cid in group_ids:
                total_tr += float(by_cid.get(cid, clip_dur.get(cid, 5.0)))
            if total_tr > 0:
                seg_durs.append(total_tr)
                continue
        total = sum(clip_dur.get(cid, 5.0) for cid in group_ids)
        if total <= 0:
            total = 5.0
        seg_durs.append(total)

    max_chars = req.style.max_chars_per_line if req.style else 20
    srt_entries = rule_timeline_equal_units(req.segments, seg_durs, max_chars=max_chars) if req.include_subtitle else []

    # 显式忽略 tts_filename，确保 burn_to_mp4 走“保留原声/拼接”的分支。
    segments_for_burn: List[SubtitleSegmentInput] = []
    for seg in req.segments:
        segments_for_burn.append(
            SubtitleSegmentInput(
                copy_text=seg.copy_text,
                clip_id=seg.clip_id,
                clip_ids=seg.clip_ids,
                # 原声导出时也需要把用户/规划阶段的时长与裁剪偏移传给 burn_to_mp4
                duration_sec=getattr(seg, "duration_sec", None),
                clip_start_sec=getattr(seg, "clip_start_sec", None),
                clip_trims=getattr(seg, "clip_trims", None),
                tts_filename=None,
            )
        )

    unique_project_name = f"{req.project_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    _, saved_path = await run_heavy(
        burn_to_mp4,
        segments=segments_for_burn,
        srt_entries=srt_entries,
        clip_map=clip_map,
        style=req.style,
        project_name=unique_project_name,
        tts_audio_dir=TTS_AUDIO_DIR,
        fonts_dir=_FONTS_DIR,
        render_opts=render_opts,
        export_render_opts=export_render_opts,
        render_mode="original",
        output_dir=burn_output_dir,
        normalize_audio=req.normalize_audio,
        export_backend=(req.export_backend or export_backend_cfg),
    )

    if not saved_path or not os.path.exists(saved_path):
        raise HTTPException(500, "原声导出失败")

    filename = os.path.basename(saved_path)
    logger.info("原声导出完成，已保存: %s", saved_path)
    result = {
        "filename": filename,
        "url": storage_public_url_for_file(saved_path),
    }
    if req.bgm and req.bgm.enabled:
        mixed_filename, mixed_url = await run_heavy(
            apply_bgm_config_postprocess,
            result["filename"],
            result["url"],
            req.bgm.model_dump(),
        )
        result["filename"] = mixed_filename
        result["url"] = mixed_url
    return result


# ---------------------------------------------------------------------------
# Route: 烧录字幕
# ---------------------------------------------------------------------------

@router.post("/burn")
async def burn_subtitle(req: BurnSubtitleRequest, request: Request):
    """合并视频 + 替换TTS音轨 + 硬烧字幕，保存到静态目录，返回可访问的 URL。"""
    if await request.is_disconnected():
        raise HTTPException(400, "客户端已断开连接")
    return await execute_burn_subtitle(req)


# ---------------------------------------------------------------------------
# Route: 原声导出（保留原音 + 可选字幕）
# ---------------------------------------------------------------------------
@router.post("/export_original", response_model=BurnSubtitleResponse)
async def export_original(req: ExportOriginalRequest, request: Request):
    """
    根据原始素材（不使用 TTS）拼接视频：
    - 音频：保留原声，并对最终结果做归一化/限幅（可选）
    - 字幕：可选；字幕内容取文案，时间轴按“句子/换行等分”映射到每段总时长
    """
    if await request.is_disconnected():
        raise HTTPException(400, "客户端已断开连接")
    return await execute_export_original(req)


# ---------------------------------------------------------------------------
# Route: 下载视频
# ---------------------------------------------------------------------------

def _find_burned_export_file(filename: str) -> str | None:
    """在旧版扁平目录或各素材 ``storage/<id>/burned_videos/`` 下查找成片。"""
    base = os.path.basename(filename)
    legacy = os.path.join(ensure_storage_subpath("burned_videos"), base)
    if os.path.isfile(legacy):
        return legacy
    root = get_storage_root()
    try:
        for mid in os.listdir(root):
            candidate = os.path.join(str(root), mid, "burned_videos", base)
            if os.path.isfile(candidate):
                return candidate
    except Exception:
        pass
    return None


@router.get("/download/{filename}")
async def download_video(filename: str):
    """下载烧录后的视频文件"""
    filepath = _find_burned_export_file(filename)
    if not filepath:
        raise HTTPException(404, "文件不存在")
    # 避免中文文件名导致 latin-1 编码报错：使用 RFC 5987 filename*
    encoded_filename = quote(filename)
    content_disposition = (
        'attachment; filename="smartclip_subtitled.mp4"; '
        f"filename*=UTF-8''{encoded_filename}"
    )
    return FileResponse(
        filepath,
        media_type="video/mp4",
        headers={"Content-Disposition": content_disposition}
    )
