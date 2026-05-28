"""
剪映草稿导出：基于 pyJianYingDraft 生成本地可打开的草稿目录并打包为 ZIP。

默认将素材 path 转为相对草稿根目录的路径并附带 patch_paths.bat，便于解压后迁移。
若配置了「剪映草稿解压目录」，则直接把素材写成该目录下草稿文件夹的完整绝对路径，且不再附带 bat/ps1。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import zipfile
from typing import Any, Dict, List, Literal, Optional, Tuple

from app.utils.ffprobe_utils import probe_duration
from app.utils.paths import normalize_jianying_parent_dir

logger = logging.getLogger(__name__)

SEC = 1_000_000  # 剪映草稿时间与 pyJianYingDraft 一致：微秒


def _safe_draft_name(name: str) -> str:
    n = re.sub(r'[<>:"/\\|?*\s]+', "_", (name or "smartclip").strip())[:80]
    return n or "smartclip"


def _copy_into_materials(src_path: str, materials_dir: str, cache: Dict[str, str]) -> str:
    src_path = os.path.abspath(src_path)
    if not os.path.isfile(src_path):
        raise FileNotFoundError(f"素材不存在: {src_path}")
    if src_path in cache:
        return cache[src_path]
    os.makedirs(materials_dir, exist_ok=True)
    base = os.path.basename(src_path)
    name, ext = os.path.splitext(base)
    dest_name = f"m_{len(cache):04d}_{name}{ext}"
    dest = os.path.join(materials_dir, dest_name)
    shutil.copy2(src_path, dest)
    cache[src_path] = os.path.abspath(dest)
    return cache[src_path]


def _relativize_draft_json(draft_folder: str, draft_content_path: str) -> None:
    """
    将 draft_content.json 内本地素材 path 改为相对 draft_folder 的路径，便于打 ZIP。

    剪映 Windows 端通常要能直接访问文件系统上的素材，多数情况下需要「本机绝对路径」。
    解压后请运行 _write_jianying_path_patch_helpers 生成的 patch_jianying_paths.py。
    """
    draft_folder = os.path.abspath(draft_folder)
    draft_nc = os.path.normcase(draft_folder)
    with open(draft_content_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    def fix_val(v: str) -> str:
        ap = os.path.abspath(v)
        ap_nc = os.path.normcase(ap)
        if ap_nc.startswith(draft_nc + os.sep) or ap_nc == draft_nc:
            rel = os.path.relpath(ap, draft_folder)
            return os.path.normpath(rel)
        return v

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "path" and isinstance(v, str) and v:
                    try:
                        o[k] = fix_val(v)
                    except Exception:
                        pass
                else:
                    walk(v)
        elif isinstance(o, list):
            for i in o:
                walk(i)

    walk(data)
    with open(draft_content_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def _absolutize_draft_json_install_paths(
    draft_folder: str, draft_content_path: str, install_parent_dir: str
) -> None:
    """
    将 draft_content.json 内位于 draft_folder 下的素材 path 改写为「解压目标」下的绝对路径。

    install_parent_dir：用户配置的目录；解压后草稿文件夹应位于
    ``{install_parent_dir}/{草稿文件夹名}/``（与 ZIP 内顶层文件夹名一致）。
    """
    draft_folder = os.path.abspath(draft_folder)
    parent = normalize_jianying_parent_dir(install_parent_dir)
    if not parent:
        raise ValueError("剪映草稿父目录无效")
    draft_name = os.path.basename(draft_folder)
    target_root = os.path.normpath(os.path.join(parent, draft_name))
    draft_nc = os.path.normcase(draft_folder)

    with open(draft_content_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    def map_path(v: str) -> str:
        if not v or not isinstance(v, str):
            return v
        try:
            if os.path.isabs(v):
                ap = os.path.abspath(v)
            else:
                ap = os.path.abspath(os.path.join(draft_folder, v))
            ap_nc = os.path.normcase(ap)
            if ap_nc.startswith(draft_nc + os.sep) or ap_nc == draft_nc:
                rel = os.path.relpath(ap, draft_folder)
                return os.path.normpath(os.path.join(target_root, rel))
            return v
        except Exception:
            return v

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "path" and isinstance(v, str) and v:
                    o[k] = map_path(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for i in o:
                walk(i)

    walk(data)
    with open(draft_content_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


# 使用 Windows 自带 PowerShell + .NET，无需安装 Python。
_PATCH_PS1 = r"""#Requires -Version 5.0
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
if (-not $root) { $root = Split-Path -Parent $MyInvocation.MyCommand.Path }
$jsonPath = Join-Path $root 'draft_content.json'
if (-not (Test-Path -LiteralPath $jsonPath)) {
    Write-Error '未找到 draft_content.json，请将脚本放在草稿文件夹内（与 draft_meta_info.json 同级）。'
    exit 1
}

Add-Type -AssemblyName System.Web.Extensions
$ser = New-Object System.Web.Script.Serialization.JavaScriptSerializer
$ser.MaxJsonLength = [int]::MaxValue
$utf8 = New-Object System.Text.UTF8Encoding $false
$raw = [System.IO.File]::ReadAllText($jsonPath, $utf8)
$obj = $ser.DeserializeObject($raw)

function Repair-Paths([object]$node, [string]$DraftRoot) {
    if ($null -eq $node) { return }
    if ($node -is [string]) { return }
    if ($node -is [System.Collections.IDictionary]) {
        foreach ($key in @($node.Keys)) {
            $val = $node[$key]
            if ($key -eq 'path') {
                if ($val -is [string] -and $val.Length -gt 0) {
                    if (-not [System.IO.Path]::IsPathRooted($val)) {
                        $norm = $val.Replace('/', [System.IO.Path]::DirectorySeparatorChar)
                        $node[$key] = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($DraftRoot, $norm))
                    }
                }
            } else {
                Repair-Paths $val $DraftRoot
            }
        }
        return
    }
    if ($node -is [System.Collections.IEnumerable]) {
        foreach ($item in $node) { Repair-Paths $item $DraftRoot }
    }
}

Repair-Paths $obj $root
$newJson = $ser.Serialize($obj)
[System.IO.File]::WriteAllText($jsonPath, $newJson, $utf8)
Write-Host '已写入绝对路径:' $jsonPath
"""

_PATCH_BAT = (
    "@echo off\r\n"
    "chcp 65001 >nul\r\n"
    'cd /d "%~dp0"\r\n'
    'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0patch_paths.ps1"\r\n'
    "if errorlevel 1 pause\r\n"
)

_PATCH_README = """剪映草稿素材路径说明（SmartClip 导出）
========================================

若提示「媒体丢失」，多半是草稿 JSON 里仍是相对路径（materials\\\\...），
剪映需要能直接访问的本机绝对路径。

步骤（无需安装 Python）：
1. 将整个草稿文件夹解压到任意目录。
2. 双击运行 patch_paths.bat（会调用系统自带的 Windows PowerShell）。
3. 把整个文件夹复制到剪映设置的「草稿位置」，再打开剪映。

说明：patch_paths.ps1 会把 draft_content.json 中的 path 写成当前电脑上的绝对路径。
若 bat 报错，可右键「使用 PowerShell 运行」patch_paths.ps1。
"""


def _write_jianying_path_patch_helpers(draft_folder: str) -> None:
    ps1_path = os.path.join(draft_folder, "patch_paths.ps1")
    with open(ps1_path, "w", encoding="utf-8-sig", newline="\r\n") as f:
        f.write(_PATCH_PS1)
    with open(os.path.join(draft_folder, "patch_paths.bat"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write(_PATCH_BAT)
    with open(os.path.join(draft_folder, "剪映草稿路径说明.txt"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write(_PATCH_README)


def _jy_resolve_trim_media(
    info: Dict[str, Any],
    clip_rel_start_sec: float,
    clip_rel_span_sec: float,
) -> Tuple[str, float, float]:
    """
    主轨一条 trim 对应的本地文件路径，以及在该文件时间轴上的 [start_sec, span_sec)（与 segment_render 原片映射一致）。
    优先使用 clip_map 的整片 src_video_path + src_start/src_end；否则使用切片文件 path + 相对入点。
    """
    clip_path = str(info.get("path") or "")
    if not clip_path or not os.path.isfile(clip_path):
        raise FileNotFoundError("切片素材 path 无效")

    clip_probe_total = float(probe_duration(clip_path, log_on_failure=True) or 0.0)
    if clip_probe_total <= 0.05:
        clip_probe_total = float(info.get("dur") or 0.0)
    if clip_probe_total <= 0.05:
        clip_probe_total = 0.05

    src_vp = str(info.get("src_video_path") or "").strip()
    if src_vp and os.path.isfile(src_vp):
        src_total = float(probe_duration(src_vp, log_on_failure=True) or 0.0)
        if src_total > 0.05:
            clip_abs_start = float(info.get("src_start") or 0.0)
            clip_abs_end = float(info.get("src_end") or 0.0)
            if clip_abs_end <= clip_abs_start + 0.02:
                clip_abs_end = clip_abs_start + clip_probe_total
            abs_start = clip_abs_start + max(0.0, clip_rel_start_sec)
            abs_start = max(0.0, min(abs_start, src_total - 0.05, clip_abs_end - 0.05))
            max_span = min(
                max(0.05, clip_rel_span_sec),
                max(0.05, clip_abs_end - abs_start),
                max(0.05, src_total - abs_start),
            )
            return src_vp, abs_start, max_span

    rel_cs = max(0.0, min(float(clip_rel_start_sec), clip_probe_total - 0.05))
    rel_span = min(max(0.05, float(clip_rel_span_sec)), max(0.05, clip_probe_total - rel_cs))
    return clip_path, rel_cs, rel_span


def _canvas_from_first_video(path: str) -> tuple[int, int]:
    try:
        import pymediainfo

        info = pymediainfo.MediaInfo.parse(path)
        if info.video_tracks:
            w = int(info.video_tracks[0].width or 1920)
            h = int(info.video_tracks[0].height or 1080)
            if w > 0 and h > 0:
                return w, h
    except Exception as e:
        logger.warning("读取视频分辨率失败，使用 1920x1080: %s", e)
    return 1920, 1080


def _seg_trims(seg: Any) -> List[tuple[str, float, float]]:
    """返回 [(clip_id, clip_start_sec, duration_sec), ...]"""
    trims = getattr(seg, "clip_trims", None) or []
    out: List[tuple[str, float, float]] = []
    if trims:
        for t in trims:
            cid = str(getattr(t, "clip_id", "") or "").strip()
            if not cid:
                continue
            cs = float(getattr(t, "clip_start_sec", 0.0) or 0.0)
            du = float(getattr(t, "duration_sec", 0.0) or 0.0)
            if du <= 0:
                continue
            out.append((cid, max(0.0, cs), du))
        return out

    raw_ids: List[str] = []
    ext = list(getattr(seg, "clip_ids", None) or [])
    if ext:
        raw_ids = [str(x) for x in ext if x]
    elif getattr(seg, "clip_id", None):
        raw_ids = [str(seg.clip_id)]
    if not raw_ids:
        return []

    cs = float(getattr(seg, "clip_start_sec", 0.0) or 0.0)
    du = getattr(seg, "duration_sec", None)
    try:
        du_v = float(du) if du is not None else None
    except Exception:
        du_v = None
    # 单段：第一个 clip 使用 duration_sec 或整段 clip 文件时长（由上层 clip_map 兜底）
    cid0 = raw_ids[0]
    if du_v is not None and du_v > 0:
        return [(cid0, max(0.0, cs), du_v)]
    return [(cid0, max(0.0, cs), 0.0)]  # 0 表示由 clip_map.dur 填充


_VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v")


def _jy_first_reference_video_path(segments: list, clip_map: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """画布/首帧参考：优先整片原素材路径，否则切片文件。"""
    for seg in segments:
        for cid, _cs, _du in _seg_trims(seg) or []:
            inf = clip_map.get(cid)
            if not inf:
                continue
            src = str(inf.get("src_video_path") or "").strip()
            if src and os.path.isfile(src) and src.lower().endswith(_VIDEO_EXTS):
                return src
            p = str(inf.get("path") or "")
            if p and os.path.isfile(p) and p.lower().endswith(_VIDEO_EXTS):
                return p
    for _cid, inf in clip_map.items():
        src = str(inf.get("src_video_path") or "").strip()
        if src and os.path.isfile(src) and src.lower().endswith(_VIDEO_EXTS):
            return src
        p = str(inf.get("path") or "")
        if p and os.path.isfile(p):
            return p
    return None


def build_jianying_draft_zip(
    *,
    segments: list,
    clip_map: Dict[str, Dict[str, Any]],
    mode: Literal["tts", "original"],
    srt_entries: list,
    tts_audio_dir: str,
    project_name: str,
    output_zip_path: str,
    fps: int = 30,
    export_segment_opts: Optional[Dict[str, str]] = None,
    jianying_draft_parent_dir: Optional[str] = None,
    subtitle_style: Optional[Any] = None,
) -> Tuple[str, Literal["zip", "direct"]]:
    """
    生成剪映草稿：未配置父目录时打包为 ZIP；配置后写入父目录下草稿子文件夹并跳过 ZIP。

    返回 ``(路径, 模式)``：ZIP 模式为 zip 文件绝对路径；direct 模式为草稿文件夹绝对路径。

    :param segments: SubtitleSegmentInput 列表，顺序与成片一致。
    :param srt_entries: parse_srt 后的条目 [{"start","end","text"}, ...] 或 SRTEntry 对象列表。
    :param export_segment_opts: 已废弃，保留仅为兼容旧调用。剪映草稿只引用**原始视频/切片文件**与
        ``source_timerange`` 裁剪点，由剪映自行解码与预览，不再做 FFmpeg 成片式重编码。
    :param jianying_draft_parent_dir: 非空时，将 ``draft_content.json`` 内素材 path 写为该目录下草稿
        子文件夹的绝对路径，整夹复制到该目录且不生成 ZIP/bat；留空则打 ZIP + 相对路径 + bat。
    :param subtitle_style: 非空时通过 pyJianYingDraft ``import_srt`` 的 ``style_reference`` 同步字体、
        颜色、描边、背景、位置等与前端 ``SubtitleStyle`` 一致；为空则保留库默认导入样式。
    """
    try:
        import pyJianYingDraft as draft
        from pyJianYingDraft import TrackType, VideoSegment, AudioSegment
        from pyJianYingDraft.local_materials import AudioMaterial, VideoMaterial
        from pyJianYingDraft.time_util import Timerange
    except ImportError as e:
        raise RuntimeError("未安装 pyJianYingDraft，无法导出剪映草稿") from e

    def _jy_material_total_us(mat_path: str, fallback_sec: float) -> int:
        """
        与 VideoSegment 内部校验使用同一套时长来源（VideoMaterial / pymediainfo）。
        若仍用 ffprobe 当上限，常会多出几毫秒而触发「截取超出素材时长」；最终用户不应靠改代码规避。
        """
        try:
            vm = VideoMaterial(mat_path)
            if getattr(vm, "material_type", "") == "photo":
                return max(1, int(round(max(fallback_sec, 0.05) * SEC)))
            return max(1, int(vm.duration))
        except Exception as ex:
            logger.warning("VideoMaterial 时长失败，回退 ffprobe: %s", ex)
            probe_us = int(round(max(fallback_sec, 0.05) * SEC))
            guard_us = min(120_000, max(40_000, probe_us // 30))
            return max(probe_us - guard_us, 1)

    def _jy_audio_material_total_us(mat_path: str, fallback_sec: float) -> int:
        """
        与 AudioSegment 内部校验使用同一套时长来源（AudioMaterial / pymediainfo）。
        ffprobe 常会多出几毫秒而触发「截取超出素材时长」。
        """
        try:
            am = AudioMaterial(mat_path)
            return max(1, int(am.duration))
        except Exception as ex:
            logger.warning("AudioMaterial 时长失败，回退 ffprobe: %s", ex)
            probe_us = int(round(max(fallback_sec, 0.05) * SEC))
            guard_us = min(120_000, max(40_000, probe_us // 30))
            return max(probe_us - guard_us, 1)

    if not segments:
        raise ValueError("segments 不能为空")

    tmp_parent = tempfile.mkdtemp(prefix="jy_export_")
    try:
        first_video_path = _jy_first_reference_video_path(segments, clip_map)
        if not first_video_path:
            raise ValueError("没有可用的视频素材用于草稿")

        if export_segment_opts:
            logger.info("剪映草稿：主轨仅引用原素材与裁剪入点，已忽略 export_segment_opts（不再预压制）")

        w, h = _canvas_from_first_video(first_video_path)

        draft_title = _safe_draft_name(project_name)
        df = draft.DraftFolder(tmp_parent)
        script = df.create_draft(draft_title, w, h, fps=fps, allow_replace=True)
        draft_folder = os.path.join(tmp_parent, draft_title)
        materials_dir = os.path.join(draft_folder, "materials")
        os.makedirs(materials_dir, exist_ok=True)
        path_cache: Dict[str, str] = {}

        script.add_track(TrackType.video)
        if mode == "tts":
            script.add_track(TrackType.audio, "tts")

        # 各段成片时间轴起点（秒），与字幕/TTS 对齐
        from app.core.subtitle.timeline import resolve_durations

        clip_dur = {cid: float(info.get("dur") or 5.0) for cid, info in clip_map.items()}
        use_tts = mode == "tts"
        seg_durs, _src = resolve_durations(segments, clip_dur, tts_audio_dir, use_tts=use_tts)
        starts_sec: List[float] = []
        acc = 0.0
        for d in seg_durs:
            starts_sec.append(acc)
            acc += float(d or 0.0)

        # 主轨视频实际结束微秒；与 resolve_durations 计划起点若有漂移则后移起点，避免 SegmentOverlap
        main_video_tail_us = 0

        from app.core.jianying.visual_effect_bridge import visual_effect_to_clip_settings

        for seg_idx, seg in enumerate(segments):
            seg_clip_settings = visual_effect_to_clip_settings(
                getattr(seg, "visual_effect", None)
            )
            seg_dur_sec = float(seg_durs[seg_idx] or 0.0)
            seg_window_us = max(0, int(round(seg_dur_sec * SEC)))
            seg_start_planned_us = int(round(starts_sec[seg_idx] * SEC))
            seg_start_us = max(seg_start_planned_us, main_video_tail_us)
            seg_end_us = seg_start_us + seg_window_us
            trims = _seg_trims(seg)
            if not trims:
                raise ValueError(f"第 {seg_idx + 1} 段缺少 clip_trims/clip_id")

            cursor_us = seg_start_us
            for _tri, (cid, cs, du) in enumerate(trims):
                if cursor_us >= seg_end_us:
                    break
                remaining_us = seg_end_us - cursor_us
                if remaining_us <= 0:
                    break

                info = clip_map.get(cid)
                if not info:
                    raise ValueError(f"第 {seg_idx + 1} 段 clip_id 无效: {cid}")

                duration_sec = float(du)
                if duration_sec <= 0:
                    clip_p = str(info.get("path") or "")
                    duration_sec = float(
                        info.get("dur") or probe_duration(clip_p, log_on_failure=True) or 5.0
                    )

                src_file, abs_start_sec, span_sec = _jy_resolve_trim_media(info, float(cs), float(duration_sec))
                mat_path = _copy_into_materials(src_file, materials_dir, path_cache)

                src_start_us = int(round(float(abs_start_sec) * SEC))
                natural_dur_us = int(round(float(span_sec) * SEC))
                cap_sec = float(
                    probe_duration(mat_path, log_on_failure=True)
                    or probe_duration(src_file, log_on_failure=True)
                    or info.get("dur")
                    or 0.0
                )
                if cap_sec <= 0.02:
                    cap_sec = 5.0

                mat_total_us = _jy_material_total_us(mat_path, cap_sec)
                src_start_us = max(0, min(src_start_us, max(0, mat_total_us - 1)))
                max_span_us = max(0, mat_total_us - src_start_us)
                natural_dur_us = min(max(natural_dur_us, 0), max_span_us)

                target_dur_us = min(natural_dur_us, remaining_us)
                target_dur_us = min(target_dur_us, max_span_us)
                if target_dur_us < 1000:
                    break

                vol = 0.0 if mode == "tts" else 1.0
                vs_kw: dict = {
                    "volume": vol,
                }
                if seg_clip_settings is not None:
                    vs_kw["clip_settings"] = seg_clip_settings
                vs = VideoSegment(
                    mat_path,
                    Timerange(cursor_us, target_dur_us),
                    source_timerange=Timerange(src_start_us, target_dur_us),
                    **vs_kw,
                )
                script.add_segment(vs)
                cursor_us += target_dur_us

            main_video_tail_us = max(main_video_tail_us, cursor_us)

            if mode == "tts":
                tts_name = getattr(seg, "tts_filename", None)
                if not tts_name:
                    raise ValueError(f"第 {seg_idx + 1} 段缺少 TTS 文件（配音成片模式）")
                tts_path = os.path.join(tts_audio_dir, os.path.basename(str(tts_name)))
                if not os.path.isfile(tts_path):
                    raise FileNotFoundError(f"TTS 音频不存在: {tts_path}")
                tts_copy = _copy_into_materials(tts_path, materials_dir, path_cache)
                tts_dur = float(probe_duration(tts_copy, log_on_failure=True) or seg_durs[seg_idx] or 1.0)
                mat_total_us = _jy_audio_material_total_us(tts_copy, tts_dur)
                tts_dur_us = min(int(round(tts_dur * SEC)), mat_total_us)
                if tts_dur_us < 1000:
                    tts_dur_us = min(mat_total_us, max(tts_dur_us, 1))
                planned_us = int(round(tts_dur * SEC))
                if planned_us > mat_total_us:
                    logger.info(
                        "剪映草稿 TTS 时长对齐素材: %s %d -> %d us",
                        os.path.basename(str(tts_name)),
                        planned_us,
                        tts_dur_us,
                    )
                au = AudioSegment(
                    tts_copy,
                    Timerange(seg_start_us, tts_dur_us),
                    source_timerange=Timerange(0, tts_dur_us),
                    volume=1.0,
                )
                script.add_segment(au, track_name="tts")

        # 字幕：写入临时 SRT 再导入
        if srt_entries:
            from app.core.subtitle.srt import build_srt

            rows = []
            for e in srt_entries:
                if hasattr(e, "start"):
                    rows.append({"start": float(e.start), "end": float(e.end), "text": str(e.text)})
                else:
                    rows.append(
                        {
                            "start": float(e.get("start", 0)),
                            "end": float(e.get("end", 0)),
                            "text": str(e.get("text", "")),
                        }
                    )
            srt_body = build_srt(rows)
            srt_path = os.path.join(draft_folder, "import_subtitles.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_body)
            script.add_track(TrackType.text, "subtitle")
            if subtitle_style is not None:
                from app.core.jianying.subtitle_style_bridge import (
                    build_subtitle_style_reference_for_srt,
                )

                _ref = build_subtitle_style_reference_for_srt(
                    subtitle_style, canvas_w=w, canvas_h=h
                )
                script.import_srt(
                    srt_path, track_name="subtitle", style_reference=_ref, clip_settings=None
                )
            else:
                script.import_srt(srt_path, track_name="subtitle")

        script.save()
        draft_json_path = os.path.join(draft_folder, "draft_content.json")
        parent_cfg = normalize_jianying_parent_dir(jianying_draft_parent_dir or "")
        if parent_cfg:
            _absolutize_draft_json_install_paths(draft_folder, draft_json_path, parent_cfg)
            os.makedirs(parent_cfg, exist_ok=True)
            target_root = os.path.normpath(os.path.join(parent_cfg, draft_title))
            if os.path.exists(target_root):
                shutil.rmtree(target_root)
            shutil.copytree(draft_folder, target_root)
            return (target_root, "direct")

        _relativize_draft_json(draft_folder, draft_json_path)
        _write_jianying_path_patch_helpers(draft_folder)

        os.makedirs(os.path.dirname(os.path.abspath(output_zip_path)) or ".", exist_ok=True)
        basezip = os.path.abspath(output_zip_path)
        if os.path.isfile(basezip):
            os.remove(basezip)
        with zipfile.ZipFile(basezip, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(draft_folder):
                for fn in files:
                    fp = os.path.join(root, fn)
                    arc = os.path.relpath(fp, tmp_parent).replace("\\", "/")
                    zf.write(fp, arcname=arc)
        return (basezip, "zip")
    finally:
        try:
            shutil.rmtree(tmp_parent, ignore_errors=True)
        except Exception:
            pass
