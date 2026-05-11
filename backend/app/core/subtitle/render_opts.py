from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _to_int(opts: Dict[str, str], key: str, default: int) -> int:
    try:
        return int(float((opts.get(key) or "").strip() or default))
    except Exception:
        return default


def _to_float(opts: Dict[str, str], key: str, default: float) -> float:
    try:
        return float((opts.get(key) or "").strip() or default)
    except Exception:
        return default


# libx264/libx265 的 preset 名与 NVENC（FFmpeg 4.4+ 的 p1~p7）不通用；成片/烧录若选 GPU 会切到 *_nvenc，需映射。
_X264_STYLE_PRESET_TO_NVENC: Dict[str, str] = {
    "ultrafast": "p1",
    "superfast": "p1",
    "veryfast": "p2",
    "faster": "p2",
    "fast": "p3",
    "medium": "p4",
    "slow": "p5",
    "slower": "p6",
    "veryslow": "p7",
}


def _effective_encoder_preset(vcodec: str, preset: str) -> str:
    """NVENC 不接受 ultrafast 等 x264 预设名；配置表仍用统一选项时需转换。"""
    vc = (vcodec or "").strip().lower()
    p = (preset or "").strip()
    if not p:
        return p
    if vc in ("h264_nvenc", "hevc_nvenc"):
        mapped = _X264_STYLE_PRESET_TO_NVENC.get(p.lower())
        if mapped:
            return mapped
    return p


def build_render_codec_args(render_opts: Optional[Dict[str, str]] = None) -> List[str]:
    """根据配置构建编码参数，避免硬编码渲染质量。"""
    opts = render_opts or {}
    vcodec = (opts.get("clip_vcodec") or "libx264").strip()
    acodec = (opts.get("clip_acodec") or "aac").strip()
    preset = (opts.get("clip_preset") or "veryfast").strip()
    preset = _effective_encoder_preset(vcodec, preset)
    pix_fmt = (opts.get("clip_pix_fmt") or "yuv420p").strip()
    crf = _to_int(opts, "clip_crf", 18)
    v_bitrate_kbps = _to_int(opts, "clip_video_bitrate_kbps", 0)
    a_bitrate_kbps = _to_int(opts, "clip_audio_bitrate_kbps", 128)
    gop = _to_int(opts, "clip_g", 48)
    keyint_min = _to_int(opts, "clip_keyint_min", 48)
    sc_threshold = _to_int(opts, "clip_sc_threshold", 0)

    args: List[str] = ["-c:v", vcodec]
    if vcodec in ("libx264", "libx265", "h264_nvenc", "hevc_nvenc") and preset:
        args += ["-preset", preset]
    if v_bitrate_kbps > 0:
        args += ["-b:v", f"{v_bitrate_kbps}k"]
    elif crf >= 0 and vcodec in ("libx264", "libx265"):
        args += ["-crf", str(crf)]
    elif crf >= 0 and vcodec in ("h264_nvenc", "hevc_nvenc"):
        # NVENC 不支持 CRF，使用 CQ 做质量控制。
        args += ["-rc", "vbr", "-cq", str(crf)]
    if gop > 0 and vcodec in ("libx264", "libx265", "h264_nvenc", "hevc_nvenc"):
        args += ["-g", str(gop)]
    if keyint_min > 0 and vcodec in ("libx264", "libx265"):
        args += ["-keyint_min", str(keyint_min)]
    if sc_threshold >= 0 and vcodec in ("libx264", "libx265"):
        args += ["-sc_threshold", str(sc_threshold)]
    if pix_fmt:
        args += ["-pix_fmt", pix_fmt]

    args += ["-c:a", acodec]
    if a_bitrate_kbps > 0 and acodec != "copy":
        args += ["-b:a", f"{a_bitrate_kbps}k"]
    return args


def force_video_reencode(codec_args: List[str], render_opts: Optional[Dict[str, str]] = None) -> List[str]:
    """
    当存在视频滤镜（如 ass/subtitles）时，不能使用 -c:v copy。
    若配置为 copy，这里回退到默认可用编码参数。
    """
    next_args = list(codec_args)
    try:
        v_idx = next_args.index("-c:v")
    except ValueError:
        return next_args
    if v_idx + 1 >= len(next_args):
        return next_args
    if (next_args[v_idx + 1] or "").strip().lower() != "copy":
        return next_args

    fallback_opts = dict(render_opts or {})
    fallback_opts["clip_vcodec"] = "libx264"
    fallback_opts.setdefault("clip_preset", "veryfast")
    fallback_opts.setdefault("clip_crf", "18")
    fallback_opts.setdefault("clip_g", "48")
    fallback_opts.setdefault("clip_keyint_min", "48")
    fallback_opts.setdefault("clip_sc_threshold", "0")
    fallback_opts.setdefault("clip_pix_fmt", "yuv420p")
    fallback_codec_args = build_render_codec_args(fallback_opts)
    logger.warning("检测到视频滤镜 + clip_vcodec=copy，已自动回退为 libx264 重编码")
    return fallback_codec_args


def sanitize_merged_opts_for_final_burn(
    merged_opts: Optional[Dict[str, str]],
    reference_video_path: str,
) -> Dict[str, str]:
    """
    成片最后一道 encode 前：merged_opts 里的 clip_scale_* 来自 export_scale_*，
    常与「切片/预览」共用为 960×540；而分段 materialize 已按导出分辨率或素材基准拉齐时，
    再套 scale=960:540 会严重发糊。此时去掉缩放，保持与拼接一致的分辨率。

    仍允许显式导出 1280×720 等（宽或高大于 960）的合理下采样。
    """
    opts = dict(merged_opts or {})
    sw = _to_int(opts, "clip_scale_width", 0)
    sh = _to_int(opts, "clip_scale_height", 0)
    if sw <= 0 or sh <= 0:
        return opts

    try:
        from app.utils.ffprobe_utils import probe_video_dimensions

        rw, rh = probe_video_dimensions(reference_video_path, default=(1920, 1080), logger_=logger)
    except Exception:
        return opts

    # 参考已是高清，且配置为典型低清预览档 → 视为误用，不在成片再压一遍
    if rw >= 1280 and rh >= 720 and sw <= 960 and sh <= 540 and (sw < rw or sh < rh):
        logger.info(
            "成片最终编码：忽略过小导出分辨率 %dx%d（参考画面约 %dx%d），避免二次缩糊",
            sw,
            sh,
            rw,
            rh,
        )
        opts["clip_scale_width"] = "0"
        opts["clip_scale_height"] = "0"
    return opts


def _make_even_dim(x: int, *, min_v: int = 2) -> int:
    x = int(x)
    if x < min_v:
        x = min_v
    return x if (x % 2 == 0) else (x - 1)


def canvas_wh_from_clip_scale_opts(
    clip_opts: Optional[Dict[str, str]],
    reference_video_path: str,
) -> Tuple[int, int]:
    """
    剪映草稿画布尺寸：与 materialize 中 clip_scale_* 语义一致。
    未配置缩放时与参考视频一致，避免「素材已按导出分辨率压制，画布仍按原片」导致剪映侧拉伸发糊。
    """
    from app.utils.ffprobe_utils import probe_video_dimensions

    rw, rh = probe_video_dimensions(reference_video_path, default=(1920, 1080), logger_=logger)
    opts = clip_opts or {}
    sw = _to_int(opts, "clip_scale_width", 0)
    sh = _to_int(opts, "clip_scale_height", 0)
    if sw <= 0 and sh <= 0:
        return int(rw), int(rh)
    src_w = max(1, int(rw))
    src_h = max(1, int(rh))
    if sw > 0 and sh > 0:
        return _make_even_dim(sw), _make_even_dim(sh)
    if sw > 0:
        th = int(round(src_h * sw / src_w))
        return _make_even_dim(sw), _make_even_dim(th)
    tw = int(round(src_w * sh / src_h))
    return _make_even_dim(tw), _make_even_dim(sh)


def build_extra_video_filters(render_opts: Optional[Dict[str, str]] = None) -> List[str]:
    """根据配置构建额外视频滤镜（缩放/帧率）。"""
    opts = render_opts or {}
    fps = _to_float(opts, "clip_fps", 0.0)
    scale_w = _to_int(opts, "clip_scale_width", 0)
    scale_h = _to_int(opts, "clip_scale_height", 0)

    filters: List[str] = []
    if scale_w > 0 or scale_h > 0:
        sw = scale_w if scale_w > 0 else -2
        sh = scale_h if scale_h > 0 else -2
        filters.append(f"scale={sw}:{sh}:flags=lanczos")
    if fps > 0:
        filters.append(f"fps={fps}")
    return filters


EXPORT_FLAT_TO_CLIP_SHAPE: List[Tuple[str, str]] = [
    ("export_vcodec", "clip_vcodec"),
    ("export_acodec", "clip_acodec"),
    ("export_preset", "clip_preset"),
    ("export_crf", "clip_crf"),
    ("export_video_bitrate_kbps", "clip_video_bitrate_kbps"),
    ("export_audio_bitrate_kbps", "clip_audio_bitrate_kbps"),
    ("export_g", "clip_g"),
    ("export_keyint_min", "clip_keyint_min"),
    ("export_sc_threshold", "clip_sc_threshold"),
    ("export_fps", "clip_fps"),
    ("export_scale_width", "clip_scale_width"),
    ("export_scale_height", "clip_scale_height"),
    ("export_pix_fmt", "clip_pix_fmt"),
    ("export_container", "clip_container"),
]


def _export_scale_dim_unspecified(raw: Optional[str]) -> bool:
    """成片导出单边分辨率：空或 ≤0 视为未指定（跟随素材 / 由另一侧推导）。"""
    s = (raw or "").strip()
    if not s:
        return True
    try:
        return int(float(s)) <= 0
    except Exception:
        return True


def export_resolution_fully_unspecified(export_render_opts: Optional[Dict[str, str]]) -> bool:
    """
    成片导出宽高均未指定：语义为「按素材原始分辨率」，不与切片预览 clip_scale_* 共用缩放。

    用于剪映草稿等与成片导出对齐的路径；避免 export_scale 全空时仍回落到 DB 里的预览档宽高。
    """
    ex = export_render_opts or {}
    return _export_scale_dim_unspecified(ex.get("export_scale_width")) and _export_scale_dim_unspecified(
        ex.get("export_scale_height")
    )


def final_render_opts_from_export(
    export_render_opts: Optional[Dict[str, str]],
    clip_fallback: Optional[Dict[str, str]],
) -> Dict[str, str]:
    """成片扁平配置 export_* → 与 build_render_codec_args 一致的 clip_* 形；空项回落到切片配置。"""
    fb = dict(clip_fallback or {})
    ex = dict(export_render_opts or {})
    out: Dict[str, str] = {}
    for ek, ck in EXPORT_FLAT_TO_CLIP_SHAPE:
        v = (ex.get(ek) or "").strip()
        out[ck] = v if v else (fb.get(ck) or "")
    return out


def sanitize_no_stream_copy(opts: Dict[str, str]) -> Dict[str, str]:
    """将 video/audio 的 stream copy 改为实际编码器（滤镜与 copy 不能同时使用；成片时间线也需重编码）。"""
    fixed = dict(opts)
    vc = (fixed.get("clip_vcodec") or "libx264").strip().lower()
    if vc == "copy":
        fixed["clip_vcodec"] = "libx264"
    ac = (fixed.get("clip_acodec") or "aac").strip().lower()
    if ac == "copy":
        fixed["clip_acodec"] = "aac"
    return fixed


def to_int(opts: Dict[str, str], key: str, default: int) -> int:
    return _to_int(opts, key, default)


def truthy_export_gpu(val: Optional[str]) -> bool:
    return str(val or "").strip().lower() in ("1", "true", "yes", "on")


def iter_export_gpu_render_attempts(render_opts: Dict[str, str], prefer_gpu: bool) -> List[Dict[str, str]]:
    """
    成片最终重编码：prefer_gpu 时按序尝试 NVENC → CPU（或 NVENC 直连失败再回退）。
    libvpx-vp9 等无常见 NVENC 映射时仅返回一档配置。
    """
    base = dict(render_opts)
    if not prefer_gpu:
        return [base]
    vc = (base.get("clip_vcodec") or "libx264").strip().lower()
    if vc == "libx264":
        gpu = dict(base)
        gpu["clip_vcodec"] = "h264_nvenc"
        return [gpu, base]
    if vc == "libx265":
        gpu = dict(base)
        gpu["clip_vcodec"] = "hevc_nvenc"
        return [gpu, base]
    if vc == "h264_nvenc":
        cpu = dict(base)
        cpu["clip_vcodec"] = "libx264"
        return [base, cpu]
    if vc == "hevc_nvenc":
        cpu = dict(base)
        cpu["clip_vcodec"] = "libx265"
        return [base, cpu]
    return [base]

