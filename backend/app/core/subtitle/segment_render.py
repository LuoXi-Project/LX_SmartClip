from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional, Tuple

from app.utils.ffprobe_utils import probe_duration, probe_keyframes_times, probe_video_dimensions

from app.utils.ffmpeg_utils import run_ffmpeg, write_concat_list
from .render_opts import (
    build_extra_video_filters,
    build_render_codec_args,
    force_video_reencode,
    sanitize_no_stream_copy,
)

logger = logging.getLogger(__name__)


def _make_even(x: int, *, min_v: int = 2) -> int:
    x = int(x)
    if x < min_v:
        x = min_v
    return x if (x % 2 == 0) else (x - 1)


def _is_near_keyframe(ts: float, keyframes: List[float], *, threshold_sec: float = 0.04) -> bool:
    if not keyframes:
        return False
    t = float(ts)
    for kf in keyframes:
        if abs(t - kf) <= threshold_sec:
            return True
    return False


def _nearest_keyframe_distance(ts: float, keyframes: List[float]) -> float:
    if not keyframes:
        return 1e9
    t = float(ts)
    return min(abs(t - kf) for kf in keyframes)


def _trim_list_from_seg(seg, clip_ids: List[str]) -> Optional[List[Tuple[float, float]]]:
    """
    clip_trims 存在时，返回与 clip_ids **同长度/同顺序**的 (start_sec, span_sec) 列表。

    不能用 dict[clip_id]->(...)：会丢顺序/丢重复（同一 clip_id 多段不同入点/时长）。
    若 clip_trims 不存在或长度与 clip_ids 不一致，返回 None 由上层走回退逻辑。
    """
    parts = getattr(seg, "clip_trims", None) or []
    if not parts:
        return None

    out: List[Tuple[float, float]] = []
    for p in parts:
        try:
            st = float(getattr(p, "clip_start_sec", None) or 0.0)
            sp = float(getattr(p, "duration_sec", None) or 0.0)
        except Exception:
            st, sp = 0.0, 0.0
        out.append((max(0.0, st), max(0.0, sp)))

    # clip_ids 在 clip_trims 分支下应与 parts 一一对应；若不一致说明上游数据不一致，返回 None 交由上层处理。
    if len(out) != len(clip_ids):
        return None
    return out


def materialize_clip_paths_for_group(
    *,
    seg,
    clip_ids: List[str],
    infos: List[dict],
    tmp: str,
    seg_idx: int,
    render_opts: Optional[Dict[str, str]],
    keyframe_cache: Optional[Dict[str, List[float]]] = None,
    materialize_cache: Optional[Dict[str, Tuple[str, float]]] = None,
    force_materialize: bool = False,
    from_source_video: bool = True,
) -> Tuple[List[str], float]:
    """
    按顺序处理 clip 组：必要时逐段 ffmpeg 裁剪，返回 concat 用的路径列表与总视频时长。

    from_source_video=True 且 clip_map 提供 src_video_path/src_start/src_end 时，
    在「切片文件时间轴」上解析出的入点会映射到整片素材上的绝对时间，从原片裁剪（成片画质不受预处理 clip 影响）。
    """
    trim_list = _trim_list_from_seg(seg, clip_ids)
    # 优化1（最重要）：提前统一尺寸/SAR，避免后续 filter_complex 对每路反复 scale。
    # 这里固定输出到 1920x1080 + setsar=1（像素方形）。
    # 若上层还配置了额外滤镜（如 fps），继续追加；但避免重复 scale。
    base_norm_filters = ["scale=1920:1080", "setsar=1"]
    extra_filters = build_extra_video_filters(render_opts)
    extra_filters = [f for f in extra_filters if not (f or "").strip().lower().startswith("scale=")]
    seg_filter_parts = [*base_norm_filters, *extra_filters]
    seg_vf_args = ["-vf", ",".join(seg_filter_parts)] if seg_filter_parts else []

    kf_cache = keyframe_cache if keyframe_cache is not None else {}
    mat_cache = materialize_cache if materialize_cache is not None else {}
    paths_out: List[str] = []
    total_dur = 0.0
    for j, (cid, info) in enumerate(zip(clip_ids, infos)):
        clip_disk_path = info["path"]
        clip_probe_total = float(probe_duration(clip_disk_path, log_on_failure=True) or 0.0)
        if clip_probe_total <= 0.05:
            clip_probe_total = float(info.get("dur") or 0.0)
        if clip_probe_total <= 0.05:
            clip_probe_total = 0.05

        # --- 先在「预处理 clip 文件」时间轴上得到 (clip_rel_start, clip_rel_span) ---
        if trim_list is not None:
            clip_rel_start, clip_rel_span = trim_list[j]
            if clip_rel_span <= 0.05:
                clip_rel_start, clip_rel_span = 0.0, clip_probe_total
            clip_rel_start = max(0.0, min(clip_rel_start, clip_probe_total - 0.05))
            clip_rel_span = min(max(0.05, clip_rel_span), max(0.05, clip_probe_total - clip_rel_start))
        else:
            rel_cs = getattr(seg, "clip_start_sec", None)
            try:
                clip_rel_start = float(rel_cs) if rel_cs is not None else 0.0
            except Exception:
                clip_rel_start = 0.0
            clip_rel_start = max(0.0, min(clip_rel_start, clip_probe_total - 0.05))
            dur_want = resolve_desired_dur(seg)
            if dur_want is not None and float(dur_want) > 0:
                clip_rel_span = min(float(dur_want), max(0.05, clip_probe_total - clip_rel_start))
            else:
                clip_rel_span = max(0.05, clip_probe_total - clip_rel_start)

        src_video = str(info.get("src_video_path") or "").strip()
        use_src = bool(from_source_video and src_video and os.path.isfile(src_video))
        if use_src:
            src_path = src_video
            src_total = float(probe_duration(src_path, log_on_failure=True) or 0.0)
            if src_total <= 0.05:
                use_src = False

        if use_src:
            clip_abs_start = float(info.get("src_start") or 0.0)
            clip_abs_end = float(info.get("src_end") or 0.0)
            if clip_abs_end <= clip_abs_start + 0.02:
                clip_abs_end = clip_abs_start + clip_probe_total
            abs_start = clip_abs_start + clip_rel_start
            abs_start = max(0.0, min(abs_start, src_total - 0.05, clip_abs_end - 0.05))
            max_span = min(
                clip_rel_span,
                max(0.05, clip_abs_end - abs_start),
                max(0.05, src_total - abs_start),
            )
            start, span = abs_start, max(0.05, max_span)
        else:
            src_path = clip_disk_path
            src_total = clip_probe_total
            start, span = clip_rel_start, clip_rel_span

        need_trim = start > 0.001 or (span + 0.02) < (src_total - start - 0.001)
        # 即便不裁剪，只要尺寸不一致也先 materialize 成统一规格，便于后续 concat demuxer/copy。
        # 已是目标尺寸时可直通（节省一次重编码）；SAR 这里不探测，依赖绝大多数素材已为 1:1。
        w, h = probe_video_dimensions(src_path, default=(1920, 1080), logger_=logger)
        need_norm = (w, h) != (1920, 1080)

        if (not force_materialize) and (not need_trim) and (not need_norm):
            paths_out.append(src_path)
            piece_dur = src_total
        else:
            tmp_name = "trim" if need_trim else "norm"
            # cache key：相同输入 + 相同裁剪参数 + 相同视频滤镜 → 复用同一个预处理文件（跨 seg）
            # 注意：这里不把 seg_idx/j 写入 key，避免同素材重复引用时重复编码。
            vf_key = ",".join(seg_filter_parts)
            src_flag = "src1" if use_src else "src0"
            cache_key = f"{src_path}|{tmp_name}|{start:.3f}|{span:.3f}|vf={vf_key}|{src_flag}"
            cached = mat_cache.get(cache_key)
            if cached and os.path.isfile(cached[0]):
                paths_out.append(cached[0])
                piece_dur = cached[1] if cached[1] > 0.05 else (span if need_trim else src_total)
                total_dur += max(piece_dur, 0.05)
                continue

            trim_tmp = os.path.join(tmp, f"seg_{seg_idx:03d}_p{j:02d}_{tmp_name}.mp4")
            end = start + span

            # 只有“纯裁剪”（不带视频滤镜）才可能安全 stream copy。
            can_try_copy = not seg_filter_parts
            did_copy = False
            if can_try_copy:
                if src_path not in kf_cache:
                    kf_cache[src_path] = probe_keyframes_times(src_path, logger_=logger)
                kfs = kf_cache.get(src_path) or []

                start_aligned = start <= 0.01 or _is_near_keyframe(start, kfs)
                end_aligned = (src_total - end) <= 0.05 or _is_near_keyframe(end, kfs)
                near_enough = _nearest_keyframe_distance(start, kfs) <= 0.20 and _nearest_keyframe_distance(end, kfs) <= 0.20

                # 情况1：关键帧对齐（或贴近片尾）→ 直接 copy（快且更可靠）
                if start_aligned and end_aligned:
                    run_ffmpeg(
                        [
                            "-ss",
                            f"{start:.3f}",
                            "-t",
                            f"{span:.3f}",
                            "-i",
                            src_path,
                            "-c",
                            "copy",
                            "-avoid_negative_ts",
                            "make_zero",
                            "-movflags",
                            "+faststart",
                            trim_tmp,
                        ],
                        desc=f"pretrim(copy) clip {cid} seg{(int(seg_idx) + 1)}",
                    )
                    did_copy = True
                # 情况2：轻微偏移 → 先试 copy，失败/异常再回退重编码
                elif near_enough:
                    try:
                        run_ffmpeg(
                            [
                                "-ss",
                                f"{start:.3f}",
                                "-t",
                                f"{span:.3f}",
                                "-i",
                                src_path,
                                "-c",
                                "copy",
                                "-avoid_negative_ts",
                                "make_zero",
                                "-movflags",
                                "+faststart",
                                trim_tmp,
                            ],
                            desc=f"pretrim(try_copy) clip {cid} seg{(int(seg_idx) + 1)}",
                        )
                        did_copy = True
                    except Exception:
                        did_copy = False

            if not did_copy:
                # 精确裁剪：回退到重编码（保证切点准确）
                trim_opts = sanitize_no_stream_copy(dict(render_opts or {}))
                seg_codec_args = build_render_codec_args(trim_opts)
                if seg_filter_parts:
                    seg_codec_args = force_video_reencode(seg_codec_args, render_opts=trim_opts)
                logger.info(f"FFmpeg pretrim(encode) 剪辑片段 {cid} 第 {(int(seg_idx) + 1)} 段 参数: {seg_codec_args}")
                run_ffmpeg(
                    [
                        "-i",
                        src_path,
                        # 不裁剪时不要带 -ss/-t，避免不必要的 seek/精度差异
                        *([] if not need_trim else ["-ss", f"{start:.3f}", "-t", f"{span:.3f}"]),
                        *seg_vf_args,
                        *seg_codec_args,
                        "-movflags",
                        "+faststart",
                        trim_tmp,
                    ],
                    desc=f"pre{tmp_name}(encode) clip {cid} seg{(int(seg_idx) + 1)}",
                )
                logger.info(f"FFmpeg pre{tmp_name}(encode) 剪辑片段 {cid} 第 {(int(seg_idx) + 1)} 段 完成")

            paths_out.append(trim_tmp)
            # 对“裁剪片段”，优先使用期望 span 作为时长来源：
            # - ffprobe/容器 metadata 偶发不准会导致后续 TTS 段“补齐判断”失效，从而生成视频短、音频长的坏文件
            # - span 已在上面按源文件总长做过 clamp，足够可信
            if need_trim:
                piece_dur = float(span)
            else:
                probed = float(probe_duration(trim_tmp, log_on_failure=True) or 0.0)
                piece_dur = probed if probed > 0.05 else src_total
            mat_cache[cache_key] = (trim_tmp, piece_dur)

        total_dur += max(piece_dur, 0.05)

    return paths_out, total_dur


def collect_segment_sources(seg, clip_map: dict, seg_idx: int) -> Tuple[List[str], List[dict]]:
    from fastapi import HTTPException

    # 强约束：只要 clip_trims 存在，就“只能使用 clip_trims 指定的素材顺序与出入点”。
    # 绝不能回退到 clip_ids（匹配组）或 clip_id（单素材），否则会混入用户未选中的素材。
    trims = getattr(seg, "clip_trims", None) or []
    if trims:
        clip_ids: List[str] = []
        for ti, t in enumerate(trims, 1):
            cid = str(getattr(t, "clip_id", "") or "").strip()
            if not cid:
                raise HTTPException(400, f"clip_trims 第 {ti} 条缺少 clip_id: seg_{(int(seg_idx) + 1)}")
            clip_ids.append(cid)
    else:
        raw_ids = list(getattr(seg, "clip_ids", None) or [])
        if not raw_ids and getattr(seg, "clip_id", None):
            raw_ids = [seg.clip_id]
        clip_ids = list(dict.fromkeys([cid for cid in raw_ids if cid]))

    if not clip_ids:
        raise HTTPException(400, f"片段缺少 clip_id: seg_{(int(seg_idx) + 1)}")
    infos: List[dict] = []
    for cid in clip_ids:
        info = clip_map.get(cid)
        if not info or not os.path.isfile(info["path"] or ""):
            raise HTTPException(404, f"片段不存在: {cid}")
        infos.append(info)

    if trims:
        try:
            trims_brief = [
                {
                    "clip_id": str(getattr(t, "clip_id", "") or ""),
                    "start": float(getattr(t, "clip_start_sec", 0.0) or 0.0),
                    "dur": float(getattr(t, "duration_sec", 0.0) or 0.0),
                }
                for t in trims
            ]
        except Exception:
            trims_brief = ["<unprintable clip_trims>"]
        logger.info(
            "seg_%d sources=%s (clip_trims=True) trims=%s",
            int(seg_idx) + 1,
            clip_ids,
            trims_brief,
        )
    else:
        logger.info("seg_%d sources=%s (clip_trims=False)", int(seg_idx) + 1, clip_ids)
    return clip_ids, infos


def resolve_desired_dur(seg) -> Optional[float]:
    try:
        v = float(getattr(seg, "duration_sec", None)) if getattr(seg, "duration_sec", None) is not None else None
    except Exception:
        v = None
    if v is not None and v <= 0:
        return None
    return v


def segment_has_tts(seg, tts_audio_dir: str) -> bool:
    name = str(getattr(seg, "tts_filename", "") or "").strip()
    if not name:
        return False
    return os.path.isfile(os.path.join(tts_audio_dir, os.path.basename(name)))


def render_original_segment(
    *,
    seg,
    clip_ids,
    infos,
    tmp,
    seg_idx,
    render_opts,
    keyframe_cache: Optional[Dict[str, List[float]]] = None,
    materialize_cache: Optional[Dict[str, Tuple[str, float]]] = None,
    from_source_video: bool = True,
) -> str:
    seg_out = os.path.join(tmp, f"seg_{seg_idx:03d}.mp4")

    paths_group, source_total_after = materialize_clip_paths_for_group(
        seg=seg,
        clip_ids=clip_ids,
        infos=infos,
        tmp=tmp,
        seg_idx=seg_idx,
        render_opts=render_opts,
        keyframe_cache=keyframe_cache,
        materialize_cache=materialize_cache,
        force_materialize=False,
        from_source_video=from_source_video,
    )

    desired_dur = resolve_desired_dur(seg)
    trim_dur = min(desired_dur, source_total_after) if desired_dur else None

    # 快路径：单段且不需要再裁剪 → 直接复用（避免无意义的重编码）
    if len(paths_group) == 1 and not trim_dur:
        return paths_group[0]

    # 快路径：多段且不需要 segment-level trim/滤镜 → 优先 concat demuxer + copy（失败再回退）
    if len(paths_group) > 1 and not trim_dur:
        concat_list = os.path.join(tmp, f"seg_{seg_idx:03d}_concat.txt")
        write_concat_list(paths_group, concat_list)
        try:
            run_ffmpeg(
                [
                    "-fflags",
                    "+genpts",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    concat_list,
                    "-c",
                    "copy",
                    "-avoid_negative_ts",
                    "make_zero",
                    "-movflags",
                    "+faststart",
                    seg_out,
                ],
                desc=f"original seg {(int(seg_idx) + 1)} (concat+copy)",
            )
            return seg_out
        except Exception:
            # fallback: 走原 filter_complex 路径
            pass

    seg_codec_args = build_render_codec_args(sanitize_no_stream_copy(dict(render_opts or {})))

    # 🚀 输入
    cmd = []
    for p in paths_group:
        cmd += ["-i", p]

    filter_parts = []
    concat_inputs = []

    # 👉 每段重建时间轴
    for i in range(len(paths_group)):
        filter_parts.append(f"[{i}:v]setpts=PTS-STARTPTS[v{i}]")
        filter_parts.append(f"[{i}:a]asetpts=PTS-STARTPTS[a{i}]")
        concat_inputs.append(f"[v{i}][a{i}]")

    # 👉 拼接
    filter_parts.append(f"{''.join(concat_inputs)}concat=n={len(paths_group)}:v=1:a=1[vcat][acat]")

    # 👉 精准裁剪（关键）
    if trim_dur:
        filter_parts.append(f"[vcat]trim=0:{trim_dur},setpts=PTS-STARTPTS[vout]")
        filter_parts.append(f"[acat]atrim=0:{trim_dur},asetpts=PTS-STARTPTS[aout]")
    else:
        filter_parts.append("[vcat]setpts=PTS-STARTPTS[vout]")
        filter_parts.append("[acat]asetpts=PTS-STARTPTS[aout]")

    filter_complex = ";".join(filter_parts)

    run_ffmpeg(
        [
            *cmd,
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            *seg_codec_args,
            "-movflags",
            "+faststart",
            seg_out,
        ],
        desc=f"original seg {(int(seg_idx) + 1)}",
    )

    return seg_out


def render_tts_segment(
    *,
    seg,
    clip_ids,
    infos,
    tmp,
    seg_idx,
    tts_audio_dir,
    render_opts,
    keyframe_cache: Optional[Dict[str, List[float]]] = None,
    materialize_cache: Optional[Dict[str, Tuple[str, float]]] = None,
    from_source_video: bool = True,
) -> str:
    from fastapi import HTTPException

    def _force_audio_reencode(codec_args: List[str], *, acodec: str = "aac", abitrate_kbps: int = 128) -> List[str]:
        """
        filter_complex 输出的音频不能 stream copy（-c:a copy）。
        这里强制将音频编码器改为可用的实际编码器（默认 aac）。
        """
        out = list(codec_args)
        try:
            a_idx = out.index("-c:a")
        except ValueError:
            out += ["-c:a", acodec, "-b:a", f"{abitrate_kbps}k"]
            return out
        if a_idx + 1 >= len(out):
            out += [acodec]
        else:
            out[a_idx + 1] = acodec
        # 确保有 -b:a（若后续已存在则不重复添加）
        if "-b:a" not in out:
            out += ["-b:a", f"{abitrate_kbps}k"]
        return out

    name = str(getattr(seg, "tts_filename", "") or "").strip()
    if not name:
        raise HTTPException(400, f"TTS 文件名为空: seg_{(int(seg_idx) + 1)}，请先合成配音")

    tts_path = os.path.join(tts_audio_dir, os.path.basename(name))
    if not os.path.isfile(tts_path):
        raise HTTPException(400, f"TTS 音频不存在: seg_{(int(seg_idx) + 1)}")

    seg_out = os.path.join(tmp, f"seg_{seg_idx:03d}.mp4")

    paths_group, source_total_after = materialize_clip_paths_for_group(
        seg=seg,
        clip_ids=clip_ids,
        infos=infos,
        tmp=tmp,
        seg_idx=seg_idx,
        render_opts=render_opts,
        keyframe_cache=keyframe_cache,
        materialize_cache=materialize_cache,
        # TTS 模式后续用 concat demuxer 拼接，必须确保每段输入规格尽量一致，否则容易生成“容器时长很长但后半段读不到帧”的坏文件。
        force_materialize=True,
        from_source_video=from_source_video,
    )

    if not paths_group:
        raise HTTPException(400, f"分段 seg_{(int(seg_idx) + 1)} 没有可用视频素材")

    audio_dur = float(probe_duration(tts_path) or 0.0)
    if audio_dur <= 0:
        raise HTTPException(400, "TTS 音频无效")

    # 如果视频总时长短于配音时长：重复追加第一个素材直到覆盖，然后再 trim 精准裁剪。
    # 这样实现“复制拼接”，不需要 loop/tpad。
    # 这里必须“强保证”视频 >= 音频，否则 ffmpeg 会以 shortest 截断音频导致字幕后半段错位。
    # 早期实现按首段时长估算可能因 probe 失败而不补足；这里改为按“整组素材”重复补齐，更稳。
    base_video_dur = float(source_total_after or 0.0)
    if base_video_dur <= 0.05:
        # 兜底：逐个 probe（可能较慢，但尽量正确）
        durs = [float(probe_duration(p) or 0.0) for p in paths_group]
        base_video_dur = sum(max(0.0, d) for d in durs)

    if base_video_dur <= 0.05:
        raise HTTPException(400, f"分段 seg_{(int(seg_idx) + 1)} 视频时长无效，无法对齐 TTS")

    need_pad_sec = 0.0
    if base_video_dur + 0.02 < audio_dur:
        import math

        need = audio_dur - base_video_dur
        # 重复“整组素材”，避免依赖单段 probe；上限防止异常音频时长导致无限膨胀
        rep = int(math.ceil(need / base_video_dur)) + 1
        rep = max(1, min(200, rep))
        paths_group = [*paths_group, *([*paths_group] * rep)]
        # 仍然给出 pad 兜底（concat/探测误差/编码尾帧等都会导致视频比预期短一点点）
        need_pad_sec = max(0.0, audio_dur - (base_video_dur * (rep + 1)))
    else:
        # 允许微小误差；若视频仍比音频短，则后续用 tpad 冻帧补齐
        need_pad_sec = max(0.0, audio_dur - base_video_dur)

    # concat 要求所有输入视频参数一致（分辨率/SAR 等），否则会报
    # "Input link parameters ... do not match ..."。
    seg_codec_args = force_video_reencode(build_render_codec_args(render_opts), render_opts=render_opts)
    seg_codec_args = _force_audio_reencode(seg_codec_args, acodec="aac", abitrate_kbps=128)

    # 优化2：尽量避免 filter_complex concat，优先 concat demuxer。
    # 前提是输入视频规格一致（分辨率/编码参数/SAR 等）。我们已在 materialize 阶段统一到 1920x1080 + SAR=1，成功率很高。
    concat_list = os.path.join(tmp, f"seg_{seg_idx:03d}_vconcat.txt")
    write_concat_list(paths_group, concat_list)
    try:
        logger.info(f"FFmpeg tts(seg concat demuxer) 段#{(int(seg_idx) + 1)} 参数: {seg_codec_args}")
        # 关键：不要让视频长度决定输出长度（-shortest 会截断音频）。
        # 若视频仍短于音频，用 tpad 冻帧补齐到 audio_dur，确保配音完整输出。
        vf_pad = []
        if need_pad_sec > 0.02:
            vf_pad = ["-vf", f"tpad=stop_mode=clone:stop_duration={need_pad_sec:.3f},setsar=1"]
        run_ffmpeg(
            [
                "-fflags",
                "+genpts",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_list,
                "-i",
                tts_path,
                # 只取拼接后的 video + 独立 tts audio
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                *vf_pad,
                # 精准控制总时长为音频时长；视频将被重编码（避免关键帧限制）
                "-t",
                f"{audio_dur:.3f}",
                *seg_codec_args,
                "-movflags",
                "+faststart",
                seg_out,
            ],
            desc=f"tts seg {(int(seg_idx) + 1)} (concat demuxer)",
        )
    except Exception:
        # fallback：仍走 filter_complex concat，但不再做多路 scale/pad（尺寸/SAR 已在 materialize 统一）
        cmd = []
        for p in paths_group:
            cmd += ["-i", p]
        cmd += ["-i", tts_path]

        filter_parts = []
        concat_inputs = []
        for i in range(len(paths_group)):
            filter_parts.append(f"[{i}:v]setsar=1,setpts=PTS-STARTPTS[v{i}]")
            concat_inputs.append(f"[v{i}]")
        filter_parts.append(f"{''.join(concat_inputs)}concat=n={len(paths_group)}:v=1:a=0[vcat]")
        filter_parts.append(f"[vcat]trim=0:{audio_dur},setpts=PTS-STARTPTS[vout]")
        filter_parts.append(f"[{len(paths_group)}:a]atrim=0:{audio_dur},asetpts=PTS-STARTPTS[aout]")
        filter_complex = ";".join(filter_parts)

        logger.info(f"FFmpeg tts(seg fallback filter_complex) 段#{(int(seg_idx) + 1)} 参数: {seg_codec_args}")
        run_ffmpeg(
            [
                *cmd,
                "-filter_complex",
                filter_complex,
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                *seg_codec_args,
                "-movflags",
                "+faststart",
                seg_out,
            ],
            desc=f"tts seg {(int(seg_idx) + 1)} (fallback filter_complex)",
        )

    logger.info(f"FFmpeg tts 剪辑片段 {(int(seg_idx) + 1)} 完成")

    return seg_out

