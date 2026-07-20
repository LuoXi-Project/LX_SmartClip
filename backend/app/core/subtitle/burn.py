"""字幕烧录门面：对外提供稳定 API。

说明：
- 旧实现曾集中在 `burn.py`，单文件过大且难维护。
- 当前将实现拆分到多个模块，此文件作为唯一对外入口，便于企业级维护/测试/演进。
"""

import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from app.utils.ffprobe_utils import clear_probe_cache, probe_duration
from app.utils.paths import get_render_tmp_base_dir

from .ass_builder import build_ass  # noqa: F401 - re-export for backwards compatibility
from .composer import compose_final_video, compose_final_video_moviepy
from .render_opts import final_render_opts_from_export, sanitize_no_stream_copy, truthy_export_gpu
from .segment_render import (
    collect_segment_sources,
    render_muted_segment,
    render_original_segment,
    render_tts_segment,
    segment_has_tts,
)

if TYPE_CHECKING:
    from app.models.production import ProductionProfile
    from app.models.subtitle import SubtitleStyle, TtsVideoAlignConfig

logger = logging.getLogger(__name__)


def build_playlist_clip_ids_from_segments(
    segments,
    clip_map: dict,
    *,
    preferred_order: list[str] | None = None,
) -> list[str]:
    """
    收集 loop_playlist_to_cover 用的素材顺序。

    优先使用混剪方案 constraints.mix_playlist_clip_ids（全量素材库顺序）；
    否则按 segments 出现顺序展开（含 clip_trims 内每条 clip）。
    """
    if preferred_order:
        return [str(c) for c in preferred_order if str(c) in clip_map]

    out: list[str] = []
    seen: set[str] = set()

    def _add(cid: str | None) -> None:
        if not cid:
            return
        c = str(cid).strip()
        if c and c in clip_map and c not in seen:
            seen.add(c)
            out.append(c)

    for seg in segments:
        trims = getattr(seg, "clip_trims", None) or []
        if trims:
            for t in trims:
                _add(getattr(t, "clip_id", None))
            continue
        raw = list(getattr(seg, "clip_ids", None) or [])
        if not raw and getattr(seg, "clip_id", None):
            raw = [seg.clip_id]
        for cid in raw:
            _add(str(cid) if cid else None)

    # 兜底：clip_map 中其余素材按源片时间排序接上
    rest = sorted(
        [cid for cid in clip_map if cid not in seen],
        key=lambda cid: (float(clip_map[cid].get("src_start") or 0.0), cid),
    )
    for cid in rest:
        _add(cid)
    return out


def enrich_tts_align_for_burn(
    segments,
    clip_map: dict,
    tts_align: Optional["TtsVideoAlignConfig"],
    *,
    preferred_playlist_clip_ids: list[str] | None = None,
) -> Optional["TtsVideoAlignConfig"]:
    if tts_align is None or str(tts_align.policy) != "loop_playlist_to_cover":
        return tts_align
    existing = list(tts_align.playlist_clip_ids or [])
    if existing:
        filtered = [c for c in existing if c in clip_map]
        if filtered:
            logger.info("loop_playlist: 使用已注入播放列表 %d 条素材", len(filtered))
            return tts_align.model_copy(update={"playlist_clip_ids": filtered})
    playlist = build_playlist_clip_ids_from_segments(
        segments,
        clip_map,
        preferred_order=preferred_playlist_clip_ids,
    )
    if not playlist:
        return tts_align
    logger.info("loop_playlist: 播放列表共 %d 条素材", len(playlist))
    return tts_align.model_copy(update={"playlist_clip_ids": playlist})


def prepare_tts_burn_segments(
    segments: list,
    tts_audio_dir: str,
    tts_align: Optional["TtsVideoAlignConfig"],
) -> tuple[list, Optional["TtsVideoAlignConfig"]]:
    """
    有配音/原声切片的段落：以实测音轨时长为成片硬上限（timeline_duration_sec），
  未指定对齐策略时默认「组内循环素材直至盖住配音」。
    """
    from app.models.subtitle import TtsVideoAlignConfig

    prepared: list = []
    has_tts = False
    for seg in segments:
        fn = str(getattr(seg, "tts_filename", "") or "").strip()
        if fn:
            has_tts = True
            p = os.path.join(tts_audio_dir, os.path.basename(fn))
            td = float(probe_duration(p, log_on_failure=True) or 0.0)
            if td > 0.05 and hasattr(seg, "model_copy"):
                seg = seg.model_copy(update={"timeline_duration_sec": td})
        prepared.append(seg)

    align = tts_align
    if align is None and has_tts:
        align = TtsVideoAlignConfig(policy="loop_video_to_cover")
    return prepared, align


def _style_from_production(
    style: "SubtitleStyle",
    production_profile: Optional["ProductionProfile"],
) -> "SubtitleStyle":
    if not production_profile:
        return style
    from app.models.subtitle import SubtitleStyle

    motion = production_profile.subtitle_motion
    if motion.template == "static" and getattr(style, "motion_template", "static") != "static":
        return style
    return style.model_copy(
        update={
            "motion_template": motion.template,
            "motion_fade_ms": motion.fade_ms,
        }
    )


def _collect_segment_transitions(segments, production_profile: Optional["ProductionProfile"]) -> list:
    from app.core.postprod.transitions import resolve_segment_transitions

    raw = [getattr(s, "transition_in", None) for s in segments]
    if production_profile:
        return resolve_segment_transitions(len(segments), production_profile, plan_transitions=raw)
    return [t or "hard_cut" for t in raw]


def _resolve_segment_render_concurrency(render_mode_opts: Dict[str, str], n_segments: int) -> int:
    """
    跨段渲染并发数。

    - 环境变量 SMARTCLIP_BURN_SEGMENT_CONCURRENCY 显式指定时优先。
    - 否则：NVENC 默认 2（消费级 N 卡会话数上限常为 3，留一路给后续 compose）；
      CPU 编码默认 min(4, cpu//2)。
    - 下限 1（即完全串行，等同旧行为）；n_segments<=1 时为 1。
    """
    raw = (os.environ.get("SMARTCLIP_BURN_SEGMENT_CONCURRENCY") or "").strip()
    if raw:
        try:
            return max(1, int(float(raw)))
        except ValueError:
            pass
    if n_segments <= 1:
        return 1
    # NVENC 保守：多路并发受限于显卡编码会话数。
    vc = (render_mode_opts.get("clip_vcodec") or "").strip().lower()
    if vc in ("h264_nvenc", "hevc_nvenc"):
        return 2
    cpu = os.cpu_count() or 4
    return max(1, min(4, cpu // 2))


def burn_to_mp4(
    segments,
    srt_entries: list,
    clip_map: dict,
    style: "SubtitleStyle",
    project_name: str,
    tts_audio_dir: str,
    fonts_dir: str,
    render_opts: Optional[Dict[str, str]] = None,
    export_render_opts: Optional[Dict[str, str]] = None,
    render_mode: str = "auto",
    export_backend: str = "moviepy",  # ffmpeg | moviepy
    normalize_audio: bool = False,
    output_dir: str = None,
    materialize_from_source: bool = True,
    tts_align: Optional["TtsVideoAlignConfig"] = None,
    require_tts_audio: bool = False,
    production_profile: Optional["ProductionProfile"] = None,
) -> tuple:
    from fastapi import HTTPException

    if not segments:
        raise HTTPException(400, "segments不能为空")

    prefer_gpu = truthy_export_gpu((export_render_opts or {}).get("export_gpu"))
    final_render_opts = sanitize_no_stream_copy(
        final_render_opts_from_export(export_render_opts, render_opts)
    )
    # 从原片裁剪时用 export_* 合并结果；仅用预处理 clip 时用 clip_*（避免低质切片参数污染成片）
    segment_render_opts = final_render_opts if materialize_from_source else (render_opts or {})

    mode = (render_mode or "auto").strip().lower()
    if mode not in ("auto", "original", "tts"):
        mode = "auto"
    if mode == "auto":
        mode = (
            "tts"
            if any(segment_has_tts(seg, tts_audio_dir) for seg in segments)
            else "original"
        )
    logger.info(
        "burn_to_mp4 mode=%s segments=%d subtitles=%d",
        mode,
        len(segments),
        len(srt_entries),
    )

    if mode == "tts" and tts_align is not None:
        tts_align = enrich_tts_align_for_burn(segments, clip_map, tts_align)

    effective_style = _style_from_production(style, production_profile)
    seg_transitions = _collect_segment_transitions(segments, production_profile)
    tr_dissolve = 0.35
    tr_fade_ms = 80
    if production_profile:
        tr_dissolve = float(production_profile.transition.dissolve_sec)
        tr_fade_ms = int(production_profile.transition.segment_fade_ms)

    tmp_base_dir = get_render_tmp_base_dir()
    with tempfile.TemporaryDirectory(dir=tmp_base_dir, prefix="burn_") as tmp:
        logger.info("临时渲染目录: %s", tmp)

        # ===== 智能路由：尝试单进程直通路径（口播快剪等单源片场景）=====
        # 成功 → out_path 直接为成片；返回 None → 自动走下方通用管线。
        from .fast_render import try_fast_render

        fast_out = try_fast_render(
            segments=segments,
            srt_entries=srt_entries,
            clip_map=clip_map,
            style=effective_style,
            project_name=project_name,
            fonts_dir=fonts_dir,
            tmp=tmp,
            final_render_opts=final_render_opts,
            normalize_audio=normalize_audio,
            prefer_gpu=prefer_gpu,
            tts_audio_dir=tts_audio_dir,
            render_mode=mode,
            materialize_from_source=materialize_from_source,
            production_profile=production_profile,
        )

        if fast_out is not None:
            out_path = fast_out
            logger.info("导出 MP4 完成(直通): %s", out_path)
        else:
            out_path = _render_generic(
                segments=segments,
                srt_entries=srt_entries,
                clip_map=clip_map,
                style=effective_style,
                project_name=project_name,
                tts_audio_dir=tts_audio_dir,
                fonts_dir=fonts_dir,
                tmp=tmp,
                segment_render_opts=segment_render_opts,
                final_render_opts=final_render_opts,
                normalize_audio=normalize_audio,
                prefer_gpu=prefer_gpu,
                export_backend=export_backend,
                materialize_from_source=materialize_from_source,
                tts_align=tts_align,
                require_tts_audio=require_tts_audio,
                mode=mode,
                seg_transitions=seg_transitions,
                tr_dissolve=tr_dissolve,
                tr_fade_ms=tr_fade_ms,
            )

        with open(out_path, "rb") as f:
            data = f.read()

        saved_path = None
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            saved_path = os.path.join(output_dir, f"{project_name}.mp4")
            with open(saved_path, "wb") as f:
                f.write(data)
            logger.info("持久化保存: %s", saved_path)

    # 合成任务结束：清空进程内 probe 缓存，避免跨任务对源片/中间文件 stat 脏读或累积。
    clear_probe_cache()
    return data, saved_path


def _render_generic(
    *,
    segments: list,
    srt_entries: list,
    clip_map: dict,
    style,
    project_name: str,
    tts_audio_dir: str,
    fonts_dir: str,
    tmp: str,
    segment_render_opts,
    final_render_opts: Dict[str, str],
    normalize_audio: bool,
    prefer_gpu: bool,
    export_backend: str,
    materialize_from_source: bool,
    tts_align,
    require_tts_audio: bool,
    mode: str,
    seg_transitions: list,
    tr_dissolve: float,
    tr_fade_ms: int,
) -> str:
    """通用管线：逐段材质化 → 并发渲染 → composer 合成（混剪/TTS/多源等场景）。"""
    seg_paths: List[str] = [""] * len(segments)

    def _render_one(seg_idx: int) -> Tuple[int, str]:
        """单段渲染（线程安全：每段独立 keyframe/materialize cache，输出文件按 seg_idx 隔离）。"""
        seg = segments[seg_idx]
        clip_ids, infos = collect_segment_sources(seg, clip_map, seg_idx)
        mute_audio = bool(getattr(seg, "mute_audio", False))
        seg_use_tts = mode != "original" and segment_has_tts(seg, tts_audio_dir)
        if require_tts_audio and mode == "tts" and not seg_use_tts and not mute_audio:
            copy_text = str(getattr(seg, "copy_text", "") or "").strip()
            tts_name = str(getattr(seg, "tts_filename", "") or "").strip()
            if copy_text or tts_name:
                detail = (
                    f"分段 seg_{seg_idx + 1} 缺少可用 TTS 音频"
                    + (f"（已登记文件 {tts_name} 但磁盘不存在）" if tts_name else "（未合成配音）")
                    + "，请检查 TTS 服务后重试。"
                )
                raise HTTPException(status_code=400, detail=detail)
        elif mode == "tts" and not seg_use_tts and not mute_audio:
            if require_tts_audio:
                raise HTTPException(
                    status_code=400,
                    detail=f"分段 seg_{seg_idx + 1} 缺少原声/配音文件，无法按音轨上限成片（请同步原声或合成配音）",
                )
            logger.warning("seg_%d 无 TTS，回退原声渲染", seg_idx + 1)
        # 每段独立 cache：keyframe 探测只读且有进程级 probe 缓存；
        # materialize 输出文件按 seg_idx 命名天然隔离，段间无写冲突。
        kf_cache: Dict[str, List[float]] = {}
        if seg_use_tts:
            seg_out = render_tts_segment(
                seg=seg,
                clip_ids=clip_ids,
                infos=infos,
                tmp=tmp,
                seg_idx=seg_idx,
                tts_audio_dir=tts_audio_dir,
                render_opts=segment_render_opts,
                keyframe_cache=kf_cache,
                from_source_video=materialize_from_source,
                tts_align=tts_align,
                clip_map=clip_map,
            )
        elif mute_audio:
            seg_out = render_muted_segment(
                seg=seg,
                clip_ids=clip_ids,
                infos=infos,
                tmp=tmp,
                seg_idx=seg_idx,
                render_opts=segment_render_opts,
                keyframe_cache=kf_cache,
                from_source_video=materialize_from_source,
            )
        else:
            seg_out = render_original_segment(
                seg=seg,
                clip_ids=clip_ids,
                infos=infos,
                tmp=tmp,
                seg_idx=seg_idx,
                render_opts=segment_render_opts,
                keyframe_cache=kf_cache,
                from_source_video=materialize_from_source,
            )
        return seg_idx, seg_out

    concurrency = _resolve_segment_render_concurrency(segment_render_opts, len(segments))
    if concurrency <= 1 or len(segments) <= 1:
        # 串行：行为与改造前完全一致（含异常即时抛出）。
        for i in range(len(segments)):
            idx, out = _render_one(i)
            seg_paths[idx] = out
    else:
        logger.info("段渲染并发=%d（共 %d 段）", concurrency, len(segments))
        with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="burn-seg") as ex:
            futures = [ex.submit(_render_one, i) for i in range(len(segments))]
            for fut in futures:
                idx, out = fut.result()  # 任一段失败：result() 重抛异常，与串行一致
                seg_paths[idx] = out

    for i, p in enumerate(seg_paths, 1):
        d = float(probe_duration(p, log_on_failure=True) or 0.0)
        logger.info("mode=%s seg=%d final_seg_dur=%.3f path=%s", mode, i, d, p)

    backend = (export_backend or "moviepy").strip().lower()
    if backend not in ("ffmpeg", "moviepy"):
        backend = "moviepy"

    if backend == "moviepy":
        out_path = compose_final_video_moviepy(
            seg_paths=seg_paths,
            srt_entries=srt_entries,
            style=style,
            fonts_dir=fonts_dir,
            tmp=tmp,
            project_name=project_name,
            final_render_opts=final_render_opts,
            normalize_audio=normalize_audio,
            prefer_gpu=prefer_gpu,
            segment_transition_ins=seg_transitions,
            transition_dissolve_sec=tr_dissolve,
            segment_fade_ms=tr_fade_ms,
        )
    else:
        out_path = compose_final_video(
            seg_paths=seg_paths,
            srt_entries=srt_entries,
            style=style,
            fonts_dir=fonts_dir,
            tmp=tmp,
            project_name=project_name,
            final_render_opts=final_render_opts,
            normalize_audio=normalize_audio,
            prefer_gpu=prefer_gpu,
            segment_transition_ins=seg_transitions,
            transition_dissolve_sec=tr_dissolve,
            segment_fade_ms=tr_fade_ms,
        )
    logger.info("导出 MP4 完成: %s", out_path)
    return out_path

