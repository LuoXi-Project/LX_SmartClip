"""将本地素材库视频与 Pexels 下载文件规范为统一分段，支持 TTS 配音 / 原声 / 混合后拼接成片。"""
from __future__ import annotations

import logging
import math
import os
import shutil
import subprocess
import tempfile
from tempfile import mkdtemp
from typing import List, Literal, Optional, Tuple

from app.core.subtitle.ass_builder import wrap_text_for_ass_display
from app.core.subtitle.composer import compose_final_video
from app.core.subtitle.render_opts import final_render_opts_from_export, sanitize_no_stream_copy
from app.core.subtitle.tts_align import build_atempo_filter_chain, resolve_stretch_audio_atempo
from app.models.subtitle import SubtitleStyle, TtsVideoAlignConfig
from app.utils.bin_paths import ffprobe_bin
from app.core.script_stock.stock_media import (
    default_image_hold_sec,
    is_stock_image_path,
)
from app.utils.ffprobe_utils import probe_duration
from app.utils.ffmpeg_utils import run_ffmpeg, write_concat_list
from app.utils.paths import ensure_storage_subpath, get_fonts_dir

logger = logging.getLogger(__name__)


def _build_script_stock_srt_entries(
    *,
    segment_texts: List[str],
    segment_durations: List[float],
    style: SubtitleStyle,
    include: bool,
) -> list:
    """各段成片顺序与时长：整段一条字幕（文案可折行），时间轴与 concat 顺序一致。"""
    if not include:
        return []
    mc = int(getattr(style, "max_chars_per_line", 20) or 20)
    entries: list = []
    t_acc = 0.0
    for i, d in enumerate(segment_durations):
        d = float(d or 0.0)
        if d <= 0.02:
            continue
        raw_txt = segment_texts[i] if i < len(segment_texts) else ""
        wrapped = wrap_text_for_ass_display(raw_txt, mc)
        if not wrapped:
            t_acc += d
            continue
        entries.append({"start": t_acc, "end": t_acc + d, "text": wrapped})
        t_acc += d
    return entries


StockAudioMode = Literal["tts_only", "original_only", "mix"]
StockTimelineMode = Literal["follow_narration", "follow_material"]
StockVideoExtendPolicy = Literal["loop_video_to_cover", "freeze_last_frame"]
StockMaterialTtsFill = Literal["pad_silence", "loop_audio"]
StockTtsLongerThanMaterial = Literal["trim_tts", "stretch_audio"]


def _stock_output_dimensions() -> Tuple[int, int]:
    try:
        w = int(os.environ.get("SMARTCLIP_SCRIPT_STOCK_WIDTH", "1280"))
        h = int(os.environ.get("SMARTCLIP_SCRIPT_STOCK_HEIGHT", "720"))
    except ValueError:
        w, h = 1280, 720
    return max(64, w), max(64, h)


def _stock_fps_filter_part() -> str:
    raw = (os.environ.get("SMARTCLIP_SCRIPT_STOCK_FPS", "30") or "").strip()
    if not raw or raw == "0":
        return ""
    try:
        f = float(raw)
        if f <= 0:
            return ""
        return f"fps={f}"
    except ValueError:
        return "fps=30"


def _build_normalize_vf(target_w: int, target_h: int) -> str:
    parts = [
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease",
        f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2",
        "setsar=1",
    ]
    fps_part = _stock_fps_filter_part()
    if fps_part:
        parts.append(fps_part)
    return ",".join(parts)


def _ffprobe_has_audio_stream(path: str) -> bool:
    probe = subprocess.run(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    return bool((probe.stdout or b"").decode(errors="replace").strip())


def _silence_wav(path: str, duration: float) -> None:
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            str(max(0.05, duration)),
            "-c:a",
            "pcm_s16le",
            path,
        ],
        desc="silence-wav",
    )


def _normalize_multi_source_parts(
    *,
    src_list: List[str],
    trim_pairs: List[Tuple[float, float]],
    tmp: str,
    seg_idx: int,
    target_w: int,
    target_h: int,
) -> List[str]:
    """
    多段拼接前逐段归一化；同源路径且同一选用区间只编码一次，其余位次复制文件。
    trim_pairs[j] = (in_sec, out_sec) 源时间轴绝对秒。
    """
    parts_norm: List[str] = []
    encoded: dict[Tuple[str, float, float], str] = {}
    for j, sabs in enumerate(src_list):
        ins, outs = trim_pairs[j]
        path_k = os.path.normcase(os.path.normpath(os.path.abspath(sabs)))
        cache_k = (path_k, round(float(ins), 4), round(float(outs), 4))
        pj = os.path.join(tmp, f"v_part_{seg_idx:03d}_{j:02d}.mp4")
        if cache_k in encoded:
            shutil.copyfile(encoded[cache_k], pj)
        else:
            _normalize_segment_video_only(
                src_abs=sabs,
                dst_mp4=pj,
                target_w=target_w,
                target_h=target_h,
                in_sec=ins,
                out_sec=outs,
            )
            encoded[cache_k] = pj
        parts_norm.append(pj)
    return parts_norm


def _normalize_segment_video_only(
    *,
    src_abs: str,
    dst_mp4: str,
    target_w: int,
    target_h: int,
    in_sec: float = 0.0,
    out_sec: Optional[float] = None,
) -> None:
    """无声画面规范化；图片在成片时按 out_sec-in_sec 做静帧；视频按源时间轴截取。"""
    os.makedirs(os.path.dirname(dst_mp4), exist_ok=True)
    ins = max(0.0, float(in_sec or 0.0))
    vf = _build_normalize_vf(target_w, target_h)

    if is_stock_image_path(src_abs):
        oe = float(out_sec) if out_sec is not None else ins + default_image_hold_sec()
        span = max(0.05, oe - ins)
        run_ffmpeg(
            [
                "-loop",
                "1",
                "-framerate",
                "30",
                "-i",
                src_abs,
                "-t",
                f"{span:.6f}",
                "-vf",
                vf,
                "-map",
                "0:v:0",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-an",
                "-movflags",
                "+faststart",
                dst_mp4,
            ],
            desc="stock-img-freeze",
        )
        return

    ss_args: List[str] = []
    if ins >= 0.001:
        ss_args = ["-ss", f"{ins:.6f}"]
    t_args: List[str] = []
    if out_sec is not None:
        oe = float(out_sec)
        span = max(0.05, oe - ins)
        t_args = ["-t", f"{span:.6f}"]
    run_ffmpeg(
        [
            *ss_args,
            "-i",
            src_abs,
            "-vf",
            vf,
            *t_args,
            "-map",
            "0:v:0",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-an",
            dst_mp4,
        ],
        desc="stock-vid-only",
    )


def _segment_video_duration_estimate(
    src_list: List[str],
    trim_pairs: List[Tuple[float, float]],
) -> float:
    total = 0.0
    for path, (ins, outs) in zip(src_list, trim_pairs):
        if is_stock_image_path(path):
            continue
        d = float(probe_duration(path) or 0.0)
        if outs > ins + 0.02:
            total += max(0.05, outs - ins)
        elif d > 0.02:
            total += d
        else:
            total += 5.0
    return total


def _resolve_segment_out_dur_and_trims(
    *,
    src_list: List[str],
    trim_pairs: List[Tuple[float, float]],
    timeline_mode: StockTimelineMode,
    audio_mode: StockAudioMode,
    tts_p: Optional[str],
) -> Tuple[float, List[Tuple[float, float]]]:
    """
    计算本段成片时长与每条素材的 (in,out)。
    多图时默认将 out_dur 均分到各图；配音更长时仍由后续 _adjust_video_to_duration 循环整段画面。
    """
    n = len(src_list)
    if n == 0:
        raise ValueError("素材列表为空")
    image_flags = [is_stock_image_path(p) for p in src_list]
    if any(image_flags) and not all(image_flags):
        raise ValueError("同一段落请勿混用图片与视频，请只选图片或只选视频")

    use_tts = audio_mode in ("tts_only", "mix") and bool(tts_p and os.path.isfile(tts_p))
    T = float(probe_duration(tts_p) or 0.0) if use_tts else 0.0

    if all(image_flags):
        hold = default_image_hold_sec()
        if audio_mode == "original_only":
            out_dur = hold * n
        elif timeline_mode == "follow_material":
            out_dur = hold * n
        else:
            out_dur = T if (use_tts and T > 0.05) else hold * n
        per = max(0.05, float(out_dur) / n)
        return float(out_dur), [(0.0, per) for _ in range(n)]

    V = _segment_video_duration_estimate(src_list, trim_pairs)
    if V <= 0.02:
        V = 5.0
    if audio_mode == "original_only":
        out_dur = V
    elif timeline_mode == "follow_material":
        out_dur = V
    else:
        out_dur = T if (use_tts and T > 0.05) else V
    return float(out_dur), list(trim_pairs)


def _ensure_audio_duration_and_vol(in_audio: str, out_wav: str, target_dur: float, vol_db: float) -> None:
    """将任意音频转为 48kHz stereo PCM，时长对齐 target_dur，并施加音量（dB）。"""
    if not in_audio or not os.path.isfile(in_audio):
        _silence_wav(out_wav, target_dur)
        return
    di = float(probe_duration(in_audio) or 0.0)
    vol_f = f"{vol_db:.2f}dB"
    parts: List[str] = [
        f"volume={vol_f}",
        "aresample=48000",
        "aformat=sample_fmts=fltp:channel_layouts=stereo",
    ]
    if di <= 0:
        _silence_wav(out_wav, target_dur)
        return
    td = max(0.05, float(target_dur))
    if di > td + 0.05:
        parts.append(f"atrim=0:{td}")
    elif di < td - 0.05:
        parts.append(f"apad=whole_dur={td:.6f}")
    af = ",".join(parts)
    run_ffmpeg(
        [
            "-i",
            in_audio,
            "-af",
            af,
            "-t",
            str(td),
            "-ac",
            "2",
            "-ar",
            "48000",
            "-y",
            out_wav,
        ],
        desc="audio-fit-vol",
    )


def _fit_tts_to_target_wav(
    in_audio: str,
    out_wav: str,
    target_dur: float,
    vol_db: float,
    *,
    shorter: Literal["pad", "loop"],
    longer: Literal["trim", "stretch"],
    stretch_cfg: TtsVideoAlignConfig,
) -> None:
    """按素材时长为主轴时，将 TTS 对齐到 target_dur（补静音 / 循环 / 裁切 / 变速）。"""
    td = max(0.05, float(target_dur))
    if not in_audio or not os.path.isfile(in_audio):
        _silence_wav(out_wav, td)
        return
    di = float(probe_duration(in_audio) or 0.0)
    vol_f = f"{vol_db:.2f}dB"
    if di <= 0:
        _silence_wav(out_wav, td)
        return
    if abs(di - td) <= 0.08:
        _ensure_audio_duration_and_vol(in_audio, out_wav, td, vol_db)
        return
    if di > td + 0.05:
        if longer == "trim":
            _ensure_audio_duration_and_vol(in_audio, out_wav, td, vol_db)
            return
        eff, _out_a = resolve_stretch_audio_atempo(tts_sec=di, video_sec=td, cfg=stretch_cfg)
        chain = f"{build_atempo_filter_chain(eff)},volume={vol_f},aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=0:{td}"
        run_ffmpeg(
            ["-i", in_audio, "-af", chain, "-t", str(td), "-ac", "2", "-ar", "48000", "-y", out_wav],
            desc="tts-stretch-fit",
        )
        return
    if shorter == "loop":
        chain = (
            f"aloop=loop=-1:size=2000000000,"
            f"volume={vol_f},aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=0:{td}"
        )
        run_ffmpeg(
            ["-i", in_audio, "-af", chain, "-t", str(td), "-ac", "2", "-ar", "48000", "-y", out_wav],
            desc="tts-loop-fit",
        )
        return
    _ensure_audio_duration_and_vol(in_audio, out_wav, td, vol_db)


def _extract_original_voice_track(
    *,
    src_video: str,
    target_dur: float,
    vol_db: float,
    out_wav: str,
    in_sec: float = 0.0,
    out_sec: Optional[float] = None,
) -> None:
    """从素材视频抽取原声片段并对齐到 target_dur；可选 in_sec/out_sec 与画面选用区间一致（首条素材）。"""
    if not _ffprobe_has_audio_stream(src_video):
        _silence_wav(out_wav, target_dur)
        return
    ins = max(0.0, float(in_sec or 0.0))
    ss_args: List[str] = []
    if ins >= 0.001:
        ss_args = ["-ss", f"{ins:.6f}"]
    t_args: List[str] = []
    if out_sec is not None:
        span = max(0.05, float(out_sec) - ins)
        t_args = ["-t", f"{span:.6f}"]
    fd, raw_extract = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        run_ffmpeg(
            [
                *ss_args,
                "-i",
                src_video,
                "-vn",
                *t_args,
                "-ac",
                "2",
                "-ar",
                "48000",
                "-c:a",
                "pcm_s16le",
                "-y",
                raw_extract,
            ],
            desc="extract-audio",
        )
        _ensure_audio_duration_and_vol(raw_extract, out_wav, target_dur, vol_db)
    finally:
        try:
            os.unlink(raw_extract)
        except OSError:
            pass


def _mix_two_wavs(a_path: str, b_path: str, out_path: str, target_dur: float) -> None:
    run_ffmpeg(
        [
            "-i",
            a_path,
            "-i",
            b_path,
            "-filter_complex",
            "[0:a][1:a]amix=inputs=2:duration=longest:normalize=0[a]",
            "-map",
            "[a]",
            "-t",
            str(target_dur),
            "-ac",
            "2",
            "-ar",
            "48000",
            "-c:a",
            "pcm_s16le",
            "-y",
            out_path,
        ],
        desc="amix-tts-orig",
    )


def _mux_video_and_audio(video_mp4: str, audio_wav: str, out_mp4: str, out_dur: float) -> None:
    od = max(0.05, float(out_dur))
    run_ffmpeg(
        [
            "-i",
            video_mp4,
            "-i",
            audio_wav,
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            "-t",
            str(od),
            out_mp4,
        ],
        desc="mux-v+a",
    )


def _concat_mp4_demuxer_copy(parts: List[str], out_mp4: str) -> None:
    if not parts:
        raise ValueError("concat 路径为空")
    if len(parts) == 1:
        shutil.copyfile(parts[0], out_mp4)
        return
    lst = out_mp4 + ".concat.txt"
    write_concat_list(parts, lst)
    try:
        run_ffmpeg(
            ["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out_mp4],
            desc="stock-concat-copy",
        )
    except RuntimeError:
        fc_in = "".join(f"[{i}:v]" for i in range(len(parts)))
        fc = f"{fc_in}concat=n={len(parts)}:v=1:a=0[v]"
        cmd: List[str] = []
        for p in parts:
            cmd += ["-i", p]
        cmd += [
            "-filter_complex",
            fc,
            "-map",
            "[v]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            out_mp4,
        ]
        run_ffmpeg(cmd, desc="stock-concat-reenc")


def _adjust_video_to_duration(
    *,
    in_mp4: str,
    out_mp4: str,
    out_sec: float,
    policy: StockVideoExtendPolicy,
) -> None:
    """将无声视频对齐到 out_sec：可裁短、循环拼接或尾帧定格。"""
    od = max(0.05, float(out_sec))
    vin = float(probe_duration(in_mp4) or 0.0)
    if vin <= 0.02:
        raise RuntimeError("画面时长探测失败")
    if abs(vin - od) <= 0.06:
        shutil.copyfile(in_mp4, out_mp4)
        return
    if vin > od + 0.05:
        run_ffmpeg(
            [
                "-i",
                in_mp4,
                "-t",
                str(od),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-an",
                "-movflags",
                "+faststart",
                out_mp4,
            ],
            desc="stock-v-trim",
        )
        return
    need = od - vin
    if policy == "freeze_last_frame":
        run_ffmpeg(
            [
                "-i",
                in_mp4,
                "-vf",
                f"tpad=stop_mode=clone:stop_duration={need:.6f},setsar=1",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-t",
                str(od),
                "-movflags",
                "+faststart",
                out_mp4,
            ],
            desc="stock-v-freeze",
        )
        return
    # loop_video_to_cover：与手动匹配 segment_render 一致——重复「整段输入」若干次再裁到目标时长。
    # 多素材时 in_mp4 已含完整一组拼接；用 concat 列表重复该文件，而不是 -stream_loop 单输入
    # （后者在部分封装/GOP 下易表现为只重复首段画面）。
    n_cycles = max(1, int(math.ceil(od / vin)))
    n_cycles = min(200, n_cycles)
    parts_repeat = [in_mp4] * n_cycles
    concat_tmp = out_mp4 + ".__group_loop__.mp4"
    try:
        _concat_mp4_demuxer_copy(parts_repeat, concat_tmp)
        run_ffmpeg(
            [
                "-i",
                concat_tmp,
                "-t",
                str(od),
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                out_mp4,
            ],
            desc="stock-v-loop-group-trim",
        )
    finally:
        if os.path.isfile(concat_tmp):
            try:
                os.remove(concat_tmp)
            except OSError:
                pass


def compose_stock_video_sync(
    *,
    segment_rows: List[Tuple[List[str], str, List[Tuple[float, float]]]],
    tts_paths: List[Optional[str]],
    audio_mode: StockAudioMode,
    tts_volume_db: float,
    original_volume_db: float,
    timeline_mode: StockTimelineMode,
    video_extend_policy: StockVideoExtendPolicy,
    material_tts_fill: StockMaterialTtsFill,
    material_tts_longer: StockTtsLongerThanMaterial,
    include_subtitle: bool,
    subtitle_style: Optional[SubtitleStyle],
    segment_texts: List[str],
    export_render_opts: dict,
    project_name: str,
) -> str:
    """
    segment_rows: ([素材绝对路径…], kind, trim_pairs)；trim_pairs 与路径等长，每项为源文件上的 (in_sec, out_sec) 秒。
    tts_paths: 与分段等长；None 表示未生成 TTS。
    timeline_mode: follow_narration 与手动匹配一致（以配音时长裁/补画面）；follow_material 以素材时长为准。
    """
    tmp = mkdtemp(prefix="lx_script_stock_")
    tw, th = _stock_output_dimensions()
    stretch_cfg = TtsVideoAlignConfig()
    try:
        prepared: List[str] = []
        segment_durations: List[float] = []
        for i, (src_list, _kind, trim_pairs) in enumerate(segment_rows):
            if not src_list or any(not p or not os.path.isfile(p) for p in src_list):
                raise FileNotFoundError(f"素材不存在: {src_list}")
            if len(trim_pairs) != len(src_list):
                raise ValueError("trim_pairs 与素材路径数量不一致")
            audio_src = src_list[0]
            tts_p: Optional[str] = tts_paths[i] if i < len(tts_paths) else None
            use_tts = audio_mode in ("tts_only", "mix") and bool(tts_p and os.path.isfile(tts_p))

            out_dur, trim_pairs_eff = _resolve_segment_out_dur_and_trims(
                src_list=src_list,
                trim_pairs=trim_pairs,
                timeline_mode=timeline_mode,
                audio_mode=audio_mode,
                tts_p=tts_p,
            )
            first_in, first_out = trim_pairs_eff[0]

            vid_base = os.path.join(tmp, f"v_base_{i:03d}.mp4")
            if len(src_list) == 1:
                _normalize_segment_video_only(
                    src_abs=src_list[0],
                    dst_mp4=vid_base,
                    target_w=tw,
                    target_h=th,
                    in_sec=trim_pairs_eff[0][0],
                    out_sec=trim_pairs_eff[0][1],
                )
            else:
                parts_norm = _normalize_multi_source_parts(
                    src_list=src_list,
                    trim_pairs=trim_pairs_eff,
                    tmp=tmp,
                    seg_idx=i,
                    target_w=tw,
                    target_h=th,
                )
                merged = os.path.join(tmp, f"v_cat_{i:03d}.mp4")
                _concat_mp4_demuxer_copy(parts_norm, merged)
                _normalize_segment_video_only(
                    src_abs=merged,
                    dst_mp4=vid_base,
                    target_w=tw,
                    target_h=th,
                    in_sec=0.0,
                    out_sec=None,
                )

            vid_fit = os.path.join(tmp, f"v_fit_{i:03d}.mp4")
            _adjust_video_to_duration(
                in_mp4=vid_base,
                out_mp4=vid_fit,
                out_sec=out_dur,
                policy=video_extend_policy,
            )

            aud_final = os.path.join(tmp, f"aud_final_{i:03d}.wav")
            shorter_m = "loop" if material_tts_fill == "loop_audio" else "pad"
            longer_m = "stretch" if material_tts_longer == "stretch_audio" else "trim"

            if audio_mode == "original_only":
                if is_stock_image_path(audio_src):
                    _silence_wav(aud_final, out_dur)
                else:
                    _extract_original_voice_track(
                        src_video=audio_src,
                        target_dur=out_dur,
                        vol_db=original_volume_db,
                        out_wav=aud_final,
                        in_sec=first_in,
                        out_sec=first_out,
                    )
            elif audio_mode == "tts_only":
                if use_tts:
                    if timeline_mode == "follow_narration":
                        _ensure_audio_duration_and_vol(tts_p, aud_final, out_dur, tts_volume_db)
                    else:
                        _fit_tts_to_target_wav(
                            tts_p,
                            aud_final,
                            out_dur,
                            tts_volume_db,
                            shorter=shorter_m,
                            longer=longer_m,
                            stretch_cfg=stretch_cfg,
                        )
                else:
                    _silence_wav(aud_final, out_dur)
            else:
                tts_fit = os.path.join(tmp, f"tts_fit_{i:03d}.wav")
                orig_fit = os.path.join(tmp, f"orig_fit_{i:03d}.wav")
                if use_tts:
                    if timeline_mode == "follow_narration":
                        _ensure_audio_duration_and_vol(tts_p, tts_fit, out_dur, tts_volume_db)
                    else:
                        _fit_tts_to_target_wav(
                            tts_p,
                            tts_fit,
                            out_dur,
                            tts_volume_db,
                            shorter=shorter_m,
                            longer=longer_m,
                            stretch_cfg=stretch_cfg,
                        )
                else:
                    _silence_wav(tts_fit, out_dur)
                if is_stock_image_path(audio_src):
                    _silence_wav(orig_fit, out_dur)
                else:
                    _extract_original_voice_track(
                        src_video=audio_src,
                        target_dur=out_dur,
                        vol_db=original_volume_db,
                        out_wav=orig_fit,
                        in_sec=first_in,
                        out_sec=first_out,
                    )
                _mix_two_wavs(tts_fit, orig_fit, aud_final, out_dur)

            seg_out = os.path.join(tmp, f"seg_final_{i:03d}.mp4")
            _mux_video_and_audio(vid_fit, aud_final, seg_out, out_dur)
            prepared.append(seg_out)
            seg_probe = float(probe_duration(seg_out) or 0.0)
            segment_durations.append(seg_probe if seg_probe > 0.02 else float(out_dur))

        style = subtitle_style or SubtitleStyle()
        srt_entries = _build_script_stock_srt_entries(
            segment_texts=segment_texts,
            segment_durations=segment_durations,
            style=style,
            include=bool(include_subtitle),
        )

        logger.info(
            "文案素材成片：画面统一 %dx%d，音频模式=%s，timeline=%s，extend=%s，字幕=%d 条",
            tw,
            th,
            audio_mode,
            timeline_mode,
            video_extend_policy,
            len(srt_entries),
        )

        merged_opts = sanitize_no_stream_copy(final_render_opts_from_export(export_render_opts, {}))
        merged_opts["clip_scale_width"] = "0"
        merged_opts["clip_scale_height"] = "0"
        merged_opts["clip_fps"] = "0"

        use_export_gpu = os.environ.get("SMARTCLIP_SCRIPT_STOCK_USE_EXPORT_GPU", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        prefer_gpu = use_export_gpu and str(export_render_opts.get("export_gpu") or "").lower() == "true"
        if not prefer_gpu:
            vc = (merged_opts.get("clip_vcodec") or "").strip().lower()
            if vc == "h264_nvenc":
                merged_opts["clip_vcodec"] = "libx264"
            elif vc == "hevc_nvenc":
                merged_opts["clip_vcodec"] = "libx265"

        out_abs = compose_final_video(
            seg_paths=prepared,
            srt_entries=srt_entries,
            style=style,
            fonts_dir=get_fonts_dir(),
            tmp=tmp,
            project_name=(project_name or "stock_clip").replace(" ", "_")[:80],
            final_render_opts=merged_opts,
            normalize_audio=False,
            prefer_gpu=prefer_gpu,
        )
        dest_dir = ensure_storage_subpath("stock_media", "exports")
        base = (project_name or "stock_clip").replace(" ", "_")[:80]
        final_name = f"{base}.mp4"
        dest = os.path.join(dest_dir, final_name)
        if os.path.exists(dest):
            root, ext = os.path.splitext(final_name)
            final_name = f"{root}_{os.path.basename(tmp)[-6:]}{ext}"
            dest = os.path.join(dest_dir, final_name)
        shutil.move(out_abs, dest)
        return dest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def is_under_pexels_download_dir(abs_path: str) -> bool:
    from app.core.script_stock.stock_media import is_under_pexels_download_dir as _check

    return _check(abs_path)
