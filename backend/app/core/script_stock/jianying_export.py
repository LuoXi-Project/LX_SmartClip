"""文案素材成片 → 剪映草稿 ZIP（与 compose 时间轴规则对齐的轻量实现，不渲染 MP4）。"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple

from app.core.jianying.draft_export import build_jianying_draft_zip
from app.core.script_stock.compose import StockAudioMode, StockTimelineMode, _build_script_stock_srt_entries
from app.models.subtitle import ClipTrimPart, SubtitleSegmentInput, SubtitleStyle
from app.utils.ffprobe_utils import probe_duration

logger = logging.getLogger(__name__)


def _segment_material_span_sec(trim_pairs: List[Tuple[float, float]]) -> float:
    s = 0.0
    for a, b in trim_pairs:
        s += max(0.0, float(b) - float(a))
    return max(s, 0.05)


def build_script_stock_jianying_zip_sync(
    *,
    segment_rows: List[Tuple[List[str], str, List[Tuple[float, float]]]],
    tts_paths: List[Optional[str]],
    segment_texts: List[str],
    audio_mode: StockAudioMode,
    timeline_mode: StockTimelineMode,
    include_subtitle: bool,
    subtitle_style: Optional[SubtitleStyle],
    project_name: str,
    tts_audio_dir: str,
    output_zip_path: str,
    jianying_draft_parent_dir: Optional[str] = None,
) -> str:
    """
    根据 script-stock 已解析的 segment_rows + TTS 路径生成剪映草稿 ZIP。

    - original_only：原声草稿（画面音量 1.0）。
    - tts_only / mix：配音轨草稿（画面静音 + TTS）；mix 在剪映侧不保留「混合原声」，与成片 MP4 可能略有差异。
    """
    if not segment_rows:
        raise ValueError("segment_rows 不能为空")

    style = subtitle_style or SubtitleStyle()
    clip_map: Dict[str, Dict[str, Any]] = {}
    segments: List[SubtitleSegmentInput] = []
    segment_durations: List[float] = []

    jy_mode: Literal["tts", "original"] = "original" if audio_mode == "original_only" else "tts"

    for i, (paths, _kind, trim_pairs) in enumerate(segment_rows):
        if not paths or len(trim_pairs) != len(paths):
            raise ValueError(f"第 {i + 1} 段素材与 trim 数量不一致")
        for p in paths:
            if not p or not os.path.isfile(p):
                raise FileNotFoundError(f"第 {i + 1} 段素材不存在: {p}")

        V = _segment_material_span_sec(trim_pairs)
        tts_p = tts_paths[i] if i < len(tts_paths) else None
        T = float(probe_duration(tts_p) or 0.0) if (tts_p and os.path.isfile(tts_p)) else 0.0
        use_tts = audio_mode in ("tts_only", "mix") and bool(tts_p and os.path.isfile(tts_p))

        if audio_mode == "original_only":
            out_dur = V
        elif timeline_mode == "follow_material":
            out_dur = V
        else:
            out_dur = T if (use_tts and T > 0.05) else V

        out_dur = max(float(out_dur or 0.0), 0.05)
        segment_durations.append(out_dur)

        cids = [f"ss_{i}_{j}" for j in range(len(paths))]
        trims: List[ClipTrimPart] = []
        for j, (a, b) in enumerate(trim_pairs):
            du = max(0.05, float(b) - float(a))
            cid = cids[j]
            full_d = float(probe_duration(paths[j]) or 0.0) or du
            clip_map[cid] = {
                "path": os.path.abspath(paths[j]),
                "dur": max(full_d, du),
                "src_video_path": "",
                "src_start": 0.0,
                "src_end": 0.0,
            }
            trims.append(ClipTrimPart(clip_id=cid, clip_start_sec=float(a), duration_sec=du))

        txt = segment_texts[i] if i < len(segment_texts) else ""
        tts_fn = os.path.basename(str(tts_p)) if use_tts and tts_p else None
        if jy_mode == "tts" and not tts_fn:
            raise ValueError(
                f"第 {i + 1} 段缺少 TTS 文件：在仅配音/混合模式下导出剪映草稿时，每段需填写文案并成功合成配音"
            )

        segments.append(
            SubtitleSegmentInput(
                copy_text=str(txt or ""),
                clip_id=cids[0],
                clip_ids=cids if len(cids) > 1 else None,
                clip_trims=trims,
                tts_filename=tts_fn,
                timeline_duration_sec=out_dur,
            )
        )

    texts_padded = [(segment_texts[i] if i < len(segment_texts) else "") for i in range(len(segment_rows))]
    srt_entries = _build_script_stock_srt_entries(
        segment_texts=texts_padded,
        segment_durations=segment_durations,
        style=style,
        include=bool(include_subtitle),
    )

    safe_name = (project_name or "stock_jy").replace(" ", "_")[:80]
    unique_name = f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    return build_jianying_draft_zip(
        segments=segments,
        clip_map=clip_map,
        mode=jy_mode,
        srt_entries=srt_entries,
        tts_audio_dir=tts_audio_dir,
        project_name=unique_name,
        output_zip_path=output_zip_path,
        jianying_draft_parent_dir=jianying_draft_parent_dir,
        subtitle_style=style,
    )  # Tuple[str, Literal["zip", "direct"]]
