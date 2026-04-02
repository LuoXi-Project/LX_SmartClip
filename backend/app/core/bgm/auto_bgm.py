from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import uuid
from typing import Dict, List, Optional, Tuple

from app.models.auto_edit import Plan
from app.utils.ffprobe_utils import probe_duration

logger = logging.getLogger(__name__)


_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
_BURNED_VIDEOS_DIR = os.path.join(_BACKEND_DIR, "storage", "burned_videos")
_BGM_LIBRARY_DIR = os.path.join(_BACKEND_DIR, "storage", "bgm")
_BGM_MANIFEST_PATH = os.path.join(_BGM_LIBRARY_DIR, "bgm_manifest.json")
_BGM_EXTENSIONS = (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")


def _run_ffmpeg(args: List[str], desc: str = "") -> None:
    cmd = ["ffmpeg", "-y"] + args
    logger.info("FFmpeg%s: %s", f" [{desc}]" if desc else "", " ".join(cmd))
    res = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=3600,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"FFmpeg 失败 [{desc}]\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stderr: {res.stderr.decode(errors='replace')[-2000:]}"
        )


def _resolve_bgm_path(track_id: Optional[str]) -> Optional[str]:
    if not track_id:
        return None
    raw = track_id.strip()
    if not raw:
        return None

    candidates: List[str] = []
    # 1) 绝对路径
    if os.path.isabs(raw):
        candidates.append(raw)
    # 2) 相对 backend 根目录
    candidates.append(os.path.join(_BACKEND_DIR, raw))
    # 3) 约定目录 storage/bgm
    candidates.append(os.path.join(_BGM_LIBRARY_DIR, raw))

    for p in candidates:
        ap = os.path.abspath(p)
        if os.path.isfile(ap):
            return ap
    return None


def _list_local_bgm_files() -> List[str]:
    if not os.path.isdir(_BGM_LIBRARY_DIR):
        return []
    bgm_files: List[str] = []
    for root, _, files in os.walk(_BGM_LIBRARY_DIR):
        for name in files:
            if name.lower().endswith(_BGM_EXTENSIONS):
                bgm_files.append(os.path.join(root, name))
    return sorted(bgm_files)


def _load_bgm_manifest() -> List[dict]:
    if not os.path.isfile(_BGM_MANIFEST_PATH):
        return []
    try:
        with open(_BGM_MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict) and isinstance(data.get("tracks"), list):
            return [x for x in data["tracks"] if isinstance(x, dict)]
    except Exception as e:
        logger.warning("BGM manifest 解析失败: %s", e)
    return []


def _mood_keywords() -> Dict[str, List[str]]:
    return {
        "happy": ["搞笑", "轻快", "欢乐", "活泼", "轻松", "funny", "happy", "vlog"],
        "calm": ["治愈", "温柔", "舒缓", "安静", "平静", "calm", "soft", "chill"],
        "epic": ["燃", "震撼", "史诗", "热血", "高潮", "epic", "power", "cinematic"],
        "sad": ["伤感", "遗憾", "催泪", "低落", "sad", "melancholy", "piano"],
        "tech": ["科技", "未来", "数码", "赛博", "tech", "electro", "synth"],
    }


def _plan_text(plan: Plan) -> str:
    parts: List[str] = [plan.title or "", plan.summary or ""]
    for seg in plan.segments:
        if seg.subtitle and seg.subtitle.text:
            parts.append(seg.subtitle.text)
    return " ".join(parts).lower()


def _detect_target_mood(text: str) -> Tuple[str, int]:
    mood_keywords = _mood_keywords()
    mood_score: Dict[str, int] = {k: 0 for k in mood_keywords.keys()}
    for mood, words in mood_keywords.items():
        for w in words:
            if w in text:
                mood_score[mood] += 1
    target_mood = max(mood_score, key=lambda k: mood_score[k])
    return target_mood, mood_score[target_mood]


def _normalize_mood(mood: str) -> str:
    raw = (mood or "").strip().lower()
    mapping = {
        "欢乐": "happy",
        "轻快": "happy",
        "治愈": "calm",
        "平静": "calm",
        "燃": "epic",
        "史诗": "epic",
        "伤感": "sad",
        "科技": "tech",
    }
    return mapping.get(raw, raw)


def _choose_bgm_from_manifest(plan: Plan) -> Optional[str]:
    manifest = _load_bgm_manifest()
    if not manifest:
        return None

    text = _plan_text(plan)
    target_mood, mood_signal = _detect_target_mood(text)
    preferred_bpm: Optional[float] = None
    # 根据风格粗略推断目标 BPM（可后续做成配置）
    if target_mood == "happy":
        preferred_bpm = 120
    elif target_mood == "epic":
        preferred_bpm = 132
    elif target_mood == "calm":
        preferred_bpm = 85
    elif target_mood == "sad":
        preferred_bpm = 78
    elif target_mood == "tech":
        preferred_bpm = 128

    best_score = -10**9
    best_path: Optional[str] = None
    mood_keywords = _mood_keywords()

    for item in manifest:
        path_val = str(item.get("path") or "").strip()
        if not path_val:
            continue
        resolved = _resolve_bgm_path(path_val)
        if not resolved:
            continue

        score = 0
        title = str(item.get("title") or "").lower()
        tags = [str(t).lower() for t in (item.get("tags") or []) if str(t).strip()]
        mood = _normalize_mood(str(item.get("mood") or ""))

        bpm_raw = item.get("bpm")
        bpm = None
        try:
            bpm = float(bpm_raw) if bpm_raw is not None else None
        except Exception:
            bpm = None

        # 情绪字段强匹配
        if mood and mood == target_mood:
            score += 12
        # tags/title 命中情绪关键词
        if mood_signal > 0:
            for token in mood_keywords.get(target_mood, []):
                tk = token.lower()
                if tk and (tk in title or any(tk in t for t in tags)):
                    score += 4
        # 文本 token 与 tags/title 的宽松匹配
        text_tokens = [t for t in re.split(r"[^a-z0-9\u4e00-\u9fff]+", text) if len(t) >= 2]
        for tk in text_tokens[:30]:
            if tk in title or any(tk in t for t in tags):
                score += 1
        # BPM 接近度奖励
        if preferred_bpm is not None and bpm is not None:
            score += max(0, int(8 - abs(preferred_bpm - bpm) / 8))

        if score > best_score:
            best_score = score
            best_path = resolved

    return best_path


def _choose_auto_bgm_track(plan: Plan) -> Optional[str]:
    """
    最小可用自动选曲：
    - 从 storage/bgm 扫描本地音频
    - 根据 plan 标题/摘要/字幕文本关键词做简单打分
    - 选最高分；无关键词命中则回退第一个文件
    """
    # 优先使用 manifest 元数据选曲
    from_manifest = _choose_bgm_from_manifest(plan)
    if from_manifest:
        return from_manifest

    candidates = _list_local_bgm_files()
    if not candidates:
        return None

    text = _plan_text(plan)
    target_mood, mood_signal = _detect_target_mood(text)
    mood_keywords = _mood_keywords()
    has_signal = mood_signal > 0

    ranked: List[Tuple[int, str]] = []
    for p in candidates:
        name = os.path.basename(p).lower()
        name_tokens = set(re.split(r"[^a-z0-9\u4e00-\u9fff]+", name))
        score = 0
        if has_signal:
            for token in mood_keywords.get(target_mood, []):
                if token and token.lower() in name:
                    score += 3

        # 通用 token 命中（标题摘要词）
        for token in re.split(r"[^a-z0-9\u4e00-\u9fff]+", text):
            if token and len(token) >= 2 and token in name_tokens:
                score += 1
        ranked.append((score, p))

    ranked.sort(key=lambda x: x[0], reverse=True)
    best_score, best_path = ranked[0]
    if best_score <= 0:
        return candidates[0]
    return best_path


def _mix_bgm_for_video(
    video_path: str,
    bgm_path: str,
    volume_db: float,
    loop: bool,
    fade_in_sec: float,
    fade_out_sec: float,
) -> str:
    video_dur = probe_duration(video_path)
    if video_dur <= 0:
        raise RuntimeError("无法探测成片时长，跳过 BGM 混音")

    fade_in = max(0.0, float(fade_in_sec or 0.0))
    fade_out = max(0.0, float(fade_out_sec or 0.0))
    fade_out_start = max(0.0, video_dur - fade_out)

    out_filename = f"{os.path.splitext(os.path.basename(video_path))[0]}_bgm_{uuid.uuid4().hex[:6]}.mp4"
    out_path = os.path.join(_BURNED_VIDEOS_DIR, out_filename)

    # BGM 音轨处理：音量 + 淡入 + 淡出（按总时长）
    bgm_filter_parts = [f"volume={float(volume_db):.2f}dB"]
    if fade_in > 0:
        bgm_filter_parts.append(f"afade=t=in:st=0:d={fade_in:.3f}")
    if fade_out > 0:
        bgm_filter_parts.append(
            f"afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}"
        )
    bgm_filter = ",".join(bgm_filter_parts)

    if loop:
        # loop 背景音乐到视频时长，再与原声混合
        filter_complex = (
            f"[1:a]{bgm_filter},aloop=loop=-1:size=2000000000,atrim=0:{video_dur:.3f}[bgm];"
            f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        args = [
            "-i",
            video_path,
            "-i",
            bgm_path,
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            out_path,
        ]
    else:
        # 不 loop 时，BGM 按原长度参与混音
        filter_complex = (
            f"[1:a]{bgm_filter}[bgm];"
            f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        args = [
            "-i",
            video_path,
            "-i",
            bgm_path,
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            out_path,
        ]

    _run_ffmpeg(args, desc="auto-edit mix bgm")
    return out_path


def apply_bgm_postprocess_if_needed(plan: Plan, filename: str, url: str) -> Tuple[str, str]:
    bgm = plan.bgm
    if not bgm or not bgm.enabled:
        return filename, url

    src_video_path = os.path.join(_BURNED_VIDEOS_DIR, filename)
    if not os.path.isfile(src_video_path):
        logger.warning("BGM 混音跳过：成片文件不存在 %s", src_video_path)
        return filename, url

    bgm_path = _resolve_bgm_path(bgm.track_id)
    if not bgm_path and bgm.source in ("library", "ai"):
        bgm_path = _choose_auto_bgm_track(plan)
        if bgm_path:
            logger.info("BGM 自动选曲命中: %s", bgm_path)

    if not bgm_path:
        logger.warning("BGM 混音跳过：无法解析 track_id=%s", bgm.track_id)
        return filename, url

    try:
        mixed_path = _mix_bgm_for_video(
            video_path=src_video_path,
            bgm_path=bgm_path,
            volume_db=bgm.volume_db,
            loop=bgm.loop,
            fade_in_sec=bgm.fade_in_sec,
            fade_out_sec=bgm.fade_out_sec,
        )
    except Exception as e:
        logger.error("BGM 混音失败，已回退原成片: %s", e)
        return filename, url

    mixed_filename = os.path.basename(mixed_path)
    return mixed_filename, f"/storage/burned_videos/{mixed_filename}"

