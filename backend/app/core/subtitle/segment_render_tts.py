from __future__ import annotations

import logging
import os
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from app.models.subtitle import TtsVideoAlignConfig
from app.core.subtitle.timeline import _tts_file_duration
from app.utils.ffprobe_utils import probe_duration, probe_keyframes_times, probe_video_dimensions
from app.utils.ffmpeg_utils import run_ffmpeg, write_concat_list
from app.core.subtitle.tts_align import (
    build_atempo_filter_chain,
    resolve_stretch_audio_atempo,
    resolve_stretch_video_pts_factor,
)
from app.core.auto_edit.mix_visual import build_segment_visual_filters
from app.core.subtitle.render_opts import (
    build_extra_video_filters,
    build_render_codec_args,
    force_video_reencode,
    sanitize_no_stream_copy,
)

logger = logging.getLogger(__name__)

_PLAYLIST_MATERIALIZE_SEG = SimpleNamespace(
    clip_trims=None,
    clip_start_sec=None,
    duration_sec=None,
)

from app.core.subtitle.segment_render_common import collect_segment_sources, resolve_desired_dur
from app.core.subtitle.segment_render_materialize import materialize_clip_paths_for_group
from app.core.subtitle.segment_render_helpers import (
    _cap_segment_to_duration,
    _expand_paths_playlist_cycle,
)

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
    tts_align: Optional[TtsVideoAlignConfig] = None,
    clip_map: Optional[dict] = None,
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

    audio_dur = float(_tts_file_duration(tts_path) or 0.0)
    if audio_dur <= 0:
        raise HTTPException(400, f"TTS 音频无效: seg_{(int(seg_idx) + 1)}")

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

    if tts_align is None:
        policy = "loop_video_to_cover"
        cfg = TtsVideoAlignConfig()
    else:
        cfg = tts_align
        policy = str(cfg.policy or "loop_video_to_cover")
    eps = 0.02
    video_shorter = base_video_dur + eps < audio_dur

    need_pad_sec = 0.0
    paths_group = list(paths_group)

    if video_shorter and policy == "loop_video_to_cover":
        path_durs: List[Tuple[str, float]] = []
        for p in paths_group:
            d = float(probe_duration(p, log_on_failure=True) or 0.0)
            path_durs.append((p, d if d > 0.05 else 0.5))
        paths_group, covered = _expand_paths_playlist_cycle(path_durs, audio_dur=audio_dur)
        need_pad_sec = max(0.0, audio_dur - covered)
        logger.info(
            "seg_%d loop_video_to_cover: group=%d clips, pieces=%d, covered=%.2fs audio=%.2fs",
            int(seg_idx) + 1,
            len(path_durs),
            len(paths_group),
            covered,
            audio_dur,
        )
    elif video_shorter and policy == "loop_playlist_to_cover":
        playlist_ids: List[str] = []
        if tts_align is not None:
            playlist_ids = list(getattr(tts_align, "playlist_clip_ids", None) or [])
        if not playlist_ids:
            playlist_ids = list(clip_ids)

        pl_ids: List[str] = []
        pl_infos: List[dict] = []
        if clip_map:
            for cid in playlist_ids:
                info = clip_map.get(cid)
                if info and os.path.isfile(info.get("path") or ""):
                    pl_ids.append(cid)
                    pl_infos.append(info)
        else:
            by_cid = {clip_ids[i]: infos[i] for i in range(min(len(clip_ids), len(infos)))}
            for cid in playlist_ids:
                if cid in by_cid:
                    pl_ids.append(cid)
                    pl_infos.append(by_cid[cid])

        if not pl_infos:
            pl_ids = list(clip_ids)
            pl_infos = list(infos)

        pl_paths, _pl_total = materialize_clip_paths_for_group(
            seg=_PLAYLIST_MATERIALIZE_SEG,
            clip_ids=pl_ids,
            infos=pl_infos,
            tmp=tmp,
            seg_idx=int(seg_idx) + 50000,
            render_opts=render_opts,
            keyframe_cache=keyframe_cache,
            materialize_cache=materialize_cache,
            force_materialize=True,
            from_source_video=from_source_video,
        )
        path_durs: List[Tuple[str, float]] = []
        for p in pl_paths:
            d = float(probe_duration(p, log_on_failure=True) or 0.0)
            path_durs.append((p, d if d > 0.05 else 0.5))
        if not path_durs:
            path_durs = [(p, float(probe_duration(p) or 0.5)) for p in paths_group]
        paths_group, covered = _expand_paths_playlist_cycle(path_durs, audio_dur=audio_dur)
        need_pad_sec = max(0.0, audio_dur - covered)
        logger.info(
            "seg_%d loop_playlist: playlist=%d clips, pieces=%d, covered=%.2fs audio=%.2fs",
            int(seg_idx) + 1,
            len(path_durs),
            len(paths_group),
            covered,
            audio_dur,
        )
    elif video_shorter and policy in ("freeze_last_frame", "preserve_video_duration"):
        need_pad_sec = max(0.0, audio_dur - base_video_dur)
    elif not video_shorter and policy != "preserve_video_duration":
        need_pad_sec = max(0.0, audio_dur - base_video_dur)

    # concat 要求所有输入视频参数一致（分辨率/SAR 等），否则会报
    # "Input link parameters ... do not match ..."。
    seg_codec_args = force_video_reencode(build_render_codec_args(render_opts), render_opts=render_opts)
    seg_codec_args = _force_audio_reencode(seg_codec_args, acodec="aac", abitrate_kbps=128)

    concat_list = os.path.join(tmp, f"seg_{seg_idx:03d}_vconcat.txt")
    write_concat_list(paths_group, concat_list)

    use_stretch_fc = (
        tts_align is not None
        and policy in ("stretch_audio", "stretch_video")
        and abs(audio_dur - base_video_dur) > eps
    )

    def _run_stretch_fc(*, output_dur: float, v_filters: str, a_filters: str) -> None:
        fc = f"[0:v]{v_filters}[vout];[1:a]{a_filters}[aout]"
        logger.info(
            "FFmpeg tts(seg stretch_fc) 段#%s policy=%s output_dur=%.3f fc=%s",
            int(seg_idx) + 1,
            policy,
            output_dur,
            fc,
        )
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
                "-filter_complex",
                fc,
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                "-t",
                f"{output_dur:.3f}",
                *seg_codec_args,
                "-movflags",
                "+faststart",
                seg_out,
            ],
            desc=f"tts seg {(int(seg_idx) + 1)} (stretch_fc)",
        )

    try:
        if use_stretch_fc:
            if policy == "stretch_audio":
                atempo_eff, out_audio = resolve_stretch_audio_atempo(
                    tts_sec=audio_dur, video_sec=base_video_dur, cfg=cfg
                )
                out_dur = max(base_video_dur, out_audio)
                a_chain = build_atempo_filter_chain(atempo_eff)
                v_body = "setpts=PTS-STARTPTS"
                if base_video_dur + eps < out_audio:
                    v_body += f",tpad=stop_mode=clone:stop_duration={out_audio - base_video_dur:.3f}"
                elif base_video_dur > out_dur + eps:
                    v_body += f",{_vf_trim_to_duration(out_dur)}"
                v_body += ",setsar=1"
                a_body = f"{a_chain},asetpts=PTS-STARTPTS"
                _run_stretch_fc(output_dur=out_dur, v_filters=v_body, a_filters=a_body)
            else:  # stretch_video
                fac, out_v = resolve_stretch_video_pts_factor(
                    tts_sec=audio_dur, video_sec=base_video_dur, cfg=cfg
                )
                v_body = f"setpts=PTS-STARTPTS,setpts=PTS*{fac:.6f}"
                if audio_dur + eps < out_v:
                    v_body += f",{_vf_trim_to_duration(audio_dur)}"
                elif audio_dur > out_v + eps:
                    v_body += f",tpad=stop_mode=clone:stop_duration={audio_dur - out_v:.3f}"
                v_body += ",setsar=1"
                a_body = "asetpts=PTS-STARTPTS"
                _run_stretch_fc(output_dur=audio_dur, v_filters=v_body, a_filters=a_body)
        elif policy == "preserve_video_duration" and audio_dur + eps < base_video_dur:
            pad_sec = max(0.0, base_video_dur - audio_dur)
            logger.info(
                "FFmpeg tts(seg preserve_video) 段#%s 画面=%.2fs 配音=%.2fs 补静音=%.2fs",
                int(seg_idx) + 1,
                base_video_dur,
                audio_dur,
                pad_sec,
            )
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
                    "-filter_complex",
                    f"[0:v]setpts=PTS-STARTPTS,setsar=1[v];[1:a]apad=pad_dur={pad_sec:.3f}[a]",
                    "-map",
                    "[v]",
                    "-map",
                    "[a]",
                    "-t",
                    f"{base_video_dur:.3f}",
                    *seg_codec_args,
                    "-movflags",
                    "+faststart",
                    seg_out,
                ],
                desc=f"tts seg {(int(seg_idx) + 1)} (preserve_video_duration)",
            )
        else:
            out_dur = audio_dur
            if policy == "preserve_video_duration":
                out_dur = max(audio_dur, base_video_dur)
            # 成片以配音（原声切片/TTS）为硬上限：画面只能在 [0, out_dur] 内，禁止溢出段落音轨。
            v_parts: List[str] = []
            if need_pad_sec > 0.02:
                v_parts.append(f"tpad=stop_mode=clone:stop_duration={need_pad_sec:.3f}")
            if policy != "preserve_video_duration":
                v_parts.append(_vf_trim_to_duration(out_dur))
            else:
                v_parts.append("setpts=PTS-STARTPTS")
            v_parts.append("setsar=1")
            v_chain = ",".join(v_parts)
            if policy == "preserve_video_duration" and out_dur > audio_dur + eps:
                pad_a = out_dur - audio_dur
                a_chain = f"apad=pad_dur={pad_a:.3f},{_af_trim_to_duration(out_dur)}"
            else:
                a_chain = _af_trim_to_duration(min(audio_dur, out_dur))
            logger.info(
                "FFmpeg tts(seg concat+trim) 段#%s out_dur=%.3f audio=%.3f base_video=%.3f policy=%s",
                int(seg_idx) + 1,
                out_dur,
                audio_dur,
                base_video_dur,
                policy,
            )
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
                    "-filter_complex",
                    f"[0:v]{v_chain}[vout];[1:a]{a_chain}[aout]",
                    "-map",
                    "[vout]",
                    "-map",
                    "[aout]",
                    "-shortest",
                    "-t",
                    f"{out_dur:.3f}",
                    *seg_codec_args,
                    "-movflags",
                    "+faststart",
                    seg_out,
                ],
                desc=f"tts seg {(int(seg_idx) + 1)} (concat+trim)",
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
        filter_parts.append(f"[vcat]{_vf_trim_to_duration(audio_dur)},setsar=1[vout]")
        filter_parts.append(f"[{len(paths_group)}:a]{_af_trim_to_duration(audio_dur)}[aout]")
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
                "-shortest",
                "-t",
                f"{audio_dur:.3f}",
                *seg_codec_args,
                "-movflags",
                "+faststart",
                seg_out,
            ],
            desc=f"tts seg {(int(seg_idx) + 1)} (fallback filter_complex)",
        )

    logger.info(f"FFmpeg tts 剪辑片段 {(int(seg_idx) + 1)} 完成")

    cap_dur = audio_dur if policy != "preserve_video_duration" else max(audio_dur, base_video_dur)
    return _cap_segment_to_duration(
        seg_out,
        cap_dur,
        tmp,
        f"seg_{int(seg_idx):03d}",
        seg_codec_args,
    )

