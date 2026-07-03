"""replica.py — 复刻模板生成（链接下载 + ASR 驱动）"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
import sqlite3

import aiosqlite
from fastapi import APIRouter, HTTPException, Query

from app.core.llm import LLMClient, LLMConfig
from app.core.llm.response_utils import extract_json_object
from app.db.database import get_db_conn
from app.models.replica import (
    ReplicaConfirmTemplateRequest,
    ReplicaGenerateTemplateRequest,
    ReplicaIngestRequest,
    ReplicaIngestResponse,
    ReplicaTemplateConfirmed,
    ReplicaTemplateDraft,
    ReplicaTemplateGetResponse,
    ReplicaTemplateListItem,
    ReplicaTemplateListResponse,
)
from app.utils.ffprobe_utils import probe_duration
from app.utils.paths import ensure_storage_subpath, to_stored_path
from app.utils.video_thumbnail import generate_thumbnail
from app.utils.video_link_downloader import VideoLinkDownloadError, download_video_from_link

from app.utils.logging_utils import stage_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/replica", tags=["replica"])

_REPLICA_TYPE_DEFAULT = "short_video"
_STYLE_PROFILE_FALLBACK = "通用"
_QUALITY_DEFAULT = "high_quality"

_REPLICA_TYPE_RULES = {
    "short_video": {
        "label": "短视频模板",
        "roles": ["hook", "context", "highlight", "proof", "cta"],
        "structure_len": "5~6",
        "sampling": {"first": 0.4, "middle": 0.3, "last": 0.3},
        "context_chars": 14000,
        "chunk_target": 6,
    },
    "film_commentary": {
        "label": "影视解说",
        "roles": ["opening", "background", "setup", "conflict", "turning_point", "climax", "reflection", "value", "cta"],
        "structure_len": "7~10",
        "sampling": {"first": 0.25, "middle": 0.45, "last": 0.30},
        "context_chars": 22000,
        "chunk_target": 10,
    },
    "scene_story": {
        "label": "场景剧情",
        "roles": ["opening", "setting", "character", "conflict", "resolution", "emotion", "cta"],
        "structure_len": "6~8",
        "sampling": {"first": 0.30, "middle": 0.45, "last": 0.25},
        "context_chars": 18000,
        "chunk_target": 8,
    },
}


class ReplicaGenerateError(Exception):
    """复刻模板生成失败，携带可读 detail 与建议的 HTTP 状态码。"""

    def __init__(self, detail: str, status_code: int = 502) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _build_stage_a_system_prompt(replica_type: str, style_profile: str) -> str:
    cfg = _REPLICA_TYPE_RULES.get(replica_type, _REPLICA_TYPE_RULES[_REPLICA_TYPE_DEFAULT])
    return f"""
你是“{cfg['label']}”复刻分析助手，当前风格标签是“{style_profile}”。
你将收到单个时间窗的「多模态对齐块」：每个镜头同时包含 台词(ASR)、画面(VLM)、旁白适配摘要、关键词、情绪标签、时长。
请综合多模态信息做局部结构化摘要——尤其要结合画面与情绪判断该镜头的真实叙事功能（钩子/铺垫/冲突/证据/收口等）。

只输出 JSON，不要解释，结构严格为：
{{
  "window_role": "该时间窗在整体叙事中的作用（综合台词+画面+情绪判断）",
  "summary": "该时间窗关键内容（综合 ASR 与画面，不要遗漏画面信息）",
  "tone": "calm|neutral|energetic",
  "pace": "slow|medium|fast",
  "signals": {{
    "emotion_curve": "情绪变化",
    "transition_pattern": "衔接方式（画面切换/转场词）",
    "information_density": "low|medium|high"
  }},
  "shot_hint": "该窗口镜头特征（如：快切/长镜头/特写/字幕密集，没有则留空）"
}}
"""


def _build_stage_b_system_prompt(replica_type: str, style_profile: str) -> str:
    cfg = _REPLICA_TYPE_RULES.get(replica_type, _REPLICA_TYPE_RULES[_REPLICA_TYPE_DEFAULT])
    role_csv = ", ".join(cfg["roles"])
    return f"""
你是“{cfg['label']}复刻模板”的高级分析助手，风格标签“{style_profile}”。
你会收到参考视频的「多模态上下文」（台词+画面+情绪+关键词）和 StageA 分段摘要，请提炼一份可被下游剪辑引擎直接消费的复刻模板。

核心目标：提取参考视频的「可复刻要素」——不只是叙事大纲，还要提取能直接影响成片观感的「钩子句式、镜头节奏、情绪曲线、转场方式」。

任务：
1) 输出 pace/tone/structure，structure 长度要求：{cfg['structure_len']}，并优先使用角色集合：{role_csv}
2) 生成 template_json（用于长期复用 + 驱动下游 auto_edit 编排）
3) 生成 template_guide（可直接粘贴到后续文案/成片规划提示词）
4) 补充 narrative_arc/chapter_plan/transition_patterns/cta_style/quality_signals

★ template_json 必须包含的三层结构（极其重要）：
- slots：可被剪辑引擎直接消费的槽位定义，长度建议 5~8。
  每个 slot 的 role 必须从 hook|context|highlight|cta 中选一个（强约束，下游编排器按 role 匹配事件）。
  description 要写成「该槽位应呈现给观众的内容要求」，可融入参考视频的具体话术风格。
  duration_ratio 为该槽位建议时长占比（0~1，各项之和≈1）。
- hook_templates：从参考视频前 3~5 秒 ASR 中提取的「钩子原句句式」（2~4 条），这是复刻能否抓住开场的核心。
- shot_rhythm：参考视频的镜头节奏特征，含 avg_shot_sec（单镜头平均秒数）、cut_frequency（high|medium|low）。
- emotion_curve：情绪曲线，按 phase 列出各阶段情绪目标（如开场=悬念、中段=紧张、结尾=释然）。

硬约束：
- 只输出 JSON，不要 Markdown，不要解释。
- 结构严格为：
{{
  "pace": "slow|medium|fast",
  "tone": "calm|neutral|energetic",
  "structure": ["..."],
  "template_json": {{
    "replica_type": "{replica_type}",
    "style_profile": "{style_profile}",
    "pace": "...",
    "tone": "...",
    "structure": ["..."],
    "slots": [
      {{
        "name": "hook",
        "role": "hook|context|highlight|cta",
        "description": "该槽位要呈现给观众的内容要求（可融入参考视频话术风格）",
        "duration_ratio": 0.12
      }}
    ],
    "hook_templates": ["参考视频前3秒钩子句式1", "句式2"],
    "shot_rhythm": {{"avg_shot_sec": 4.5, "cut_frequency": "high|medium|low"}},
    "emotion_curve": [{{"phase": "开场", "emotion": "悬念"}}],
    "slot_guidelines": {{}},
    "narrative_arc": "...",
    "chapter_plan": [
      {{
        "chapter": "章节名",
        "goal": "该章目标",
        "emotion_target": "该章情绪目标",
        "density": "low|medium|high",
        "transition_hint": "衔接句式建议"
      }}
    ],
    "transition_patterns": ["..."],
    "cta_style": "...",
    "quality_signals": {{
      "coverage": 0,
      "coherence": 0,
      "density_stability": 0
    }}
  }},
  "template_guide": "复刻执行说明（含钩子策略/节奏/转场/情绪等可执行指引）"
}}
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_preview(text: str, max_len: int = 160) -> str:
    s = (text or "").strip().replace("\r", "").replace("\t", " ")
    s = " ".join(s.split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def _parse_template_meta(raw_template_json: object) -> tuple[str | None, str | None, dict | None]:
    obj: dict = {}
    if isinstance(raw_template_json, str):
        try:
            parsed = json.loads(raw_template_json)
            obj = parsed if isinstance(parsed, dict) else {}
        except Exception:
            obj = {}
    elif isinstance(raw_template_json, dict):
        obj = raw_template_json
    replica_type = str(obj.get("replica_type") or "").strip() or None
    style_profile = str(obj.get("style_profile") or "").strip() or None
    q = obj.get("quality_signals")
    quality_signals = q if isinstance(q, dict) else None
    return replica_type, style_profile, quality_signals


def _fmt_time(seconds: float) -> str:
    # 同 copy_gen 的分钟:秒格式，便于模型理解节奏
    m, sec = divmod(int(seconds), 60)
    return f"{m}:{sec:02d}"


async def _download_reference_video(req: ReplicaIngestRequest, *, video_id: str) -> str:
    """
    下载参考视频到 ``storage/<video_id>/videos/``（抖音匿名解析，其它站点 yt-dlp）。
    """
    try:
        path, _ = download_video_from_link(
            url=req.url,
            output_dir=ensure_storage_subpath(video_id, "videos"),
            file_stem="source",
        )
        return path
    except VideoLinkDownloadError as exc:
        detail = str(exc)
        status = 501 if "未检测到 yt-dlp" in detail else 502
        raise HTTPException(status_code=status, detail=detail) from exc


async def _insert_video_row(*, video_id: str, name: str, file_path: str) -> None:
    db = await get_db_conn()
    try:
        await db.execute(
            """
            INSERT INTO videos (id, name, file_path, thumbnail_path, duration, total_clips, split_mode, status, is_replica_ref, upload_at)
            VALUES (?, ?, ?, ?, NULL, 0, 'scene', 'pending', 1, ?)
            """,
            (video_id, name, to_stored_path(file_path), None, _utc_now_iso()),
        )
        await db.commit()
    finally:
        await db.close()


async def _build_reference_asr_context(
    db: aiosqlite.Connection,
    video_id: str,
    *,
    max_clips: int,
    context_max_chars: int = 12000,
) -> str:
    """
    从 clips 表聚合 ASR 文本，作为“复刻风格推断”的上下文输入。
    """
    rows: list[aiosqlite.Row] = []  # type: ignore[name-defined]
    # 兼容：只取单个 video 的 clips
    async with db.execute(
        """
        SELECT id, start_time, end_time, duration, asr_text,
               vlm_description, abstract_summary, keywords, emotion_tags
        FROM clips
        WHERE video_id = ?
          AND TRIM(COALESCE(asr_text, '')) <> ''
        ORDER BY start_time
        LIMIT ?
        """,
        (video_id, max_clips),
    ) as cur:
        rows = await cur.fetchall()

    if not rows:
        return ""

    total = 0
    lines: list[str] = []
    for r in rows:
        block = _row_to_multimodal_block(r)
        if not block:
            continue

        if lines and total + len(block) > context_max_chars:
            break
        lines.append(block)
        total += len(block)

    return "\n".join(lines).strip()


async def _fetch_reference_asr_rows(
    db: aiosqlite.Connection,
    video_id: str,
    *,
    max_clips: int,
) -> list[aiosqlite.Row]:
    async with db.execute(
        """
        SELECT id, start_time, end_time, duration, asr_text,
               vlm_description, abstract_summary, keywords, emotion_tags
        FROM clips
        WHERE video_id = ?
          AND TRIM(COALESCE(asr_text, '')) <> ''
        ORDER BY start_time
        LIMIT ?
        """,
        (video_id, max_clips),
    ) as cur:
        return await cur.fetchall()


def _row_to_multimodal_block(r: aiosqlite.Row) -> str:
    """
    把单个 clip 行拼成「多模态对齐块」供 LLM 复刻分析：
    台词(ASR) + 画面(VLM) + 旁白适配摘要 + 关键词 + 情绪 + 时长。
    各字段空则跳过，避免噪音；asr 为空直接返回空串（与旧逻辑一致，保证过滤）。
    """
    asr = (r["asr_text"] or "").strip()
    if not asr:
        return ""

    clip_id = str(r["id"])
    t0 = float(r["start_time"] or 0.0)
    t1 = float(r["end_time"] or 0.0)
    dur = r["duration"] if "duration" in r.keys() else None
    dur_str = f" ({float(dur):.1f}s)" if isinstance(dur, (int, float)) and dur > 0 else ""

    parts: list[str] = [f"\n[clip_id={clip_id}] [{_fmt_time(t0)}→{_fmt_time(t1)}]{dur_str}", f"台词：{asr}"]

    vlm = ((r["vlm_description"] or "") if "vlm_description" in r.keys() else "").strip()
    if vlm:
        parts.append(f"画面：{vlm}")

    summary = ((r["abstract_summary"] or "") if "abstract_summary" in r.keys() else "").strip()
    if summary:
        parts.append(f"旁白摘要：{summary}")

    kw_raw = r["keywords"] if "keywords" in r.keys() else None
    kw = _parse_str_or_json_list(kw_raw)
    if kw:
        parts.append(f"关键词：{', '.join(kw)}")

    em_raw = r["emotion_tags"] if "emotion_tags" in r.keys() else None
    em = _parse_str_or_json_list(em_raw)
    if em:
        parts.append(f"情绪：{', '.join(em)}")

    return "\n".join(parts)


def _parse_str_or_json_list(raw: object) -> list[str]:
    """关键词/情绪字段可能是 JSON 数组字符串，也可能是逗号分隔文本，统一解析成列表。"""
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    s = str(raw).strip()
    if not s:
        return []
    if s.startswith("["):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass
    return [x.strip() for x in s.replace("，", ",").split(",") if x.strip()]


def _select_rows_by_ratio(rows: list[aiosqlite.Row], ratio: dict[str, float], cap: int) -> list[aiosqlite.Row]:
    if not rows:
        return []
    n = min(len(rows), max(1, cap))
    first_n = max(1, int(n * ratio.get("first", 0.34)))
    mid_n = max(1, int(n * ratio.get("middle", 0.33)))
    last_n = max(1, n - first_n - mid_n)
    if first_n + mid_n + last_n > n:
        last_n = max(1, n - first_n - mid_n)

    first = rows[:first_n]
    mid_start = max(first_n, (len(rows) // 2) - (mid_n // 2))
    middle = rows[mid_start: mid_start + mid_n]
    last = rows[-last_n:]

    dedup: dict[str, aiosqlite.Row] = {}
    for r in [*first, *middle, *last]:
        dedup[str(r["id"])] = r
    return sorted(dedup.values(), key=lambda x: float(x["start_time"] or 0.0))


def _rows_to_context(rows: list[aiosqlite.Row], *, context_max_chars: int) -> str:
    total = 0
    lines: list[str] = []
    for r in rows:
        block = _row_to_multimodal_block(r)
        if not block:
            continue
        if lines and total + len(block) > context_max_chars:
            break
        lines.append(block)
        total += len(block)
    return "\n".join(lines).strip()


def _build_stage_a_windows(rows: list[aiosqlite.Row], target_windows: int) -> list[list[aiosqlite.Row]]:
    if not rows:
        return []
    k = max(1, min(target_windows, len(rows)))
    step = max(1, len(rows) // k)
    windows: list[list[aiosqlite.Row]] = []
    idx = 0
    while idx < len(rows):
        windows.append(rows[idx: idx + step])
        idx += step
    return windows[:k]


async def _run_stage_a_summaries(
    llm: LLMClient,
    *,
    replica_type: str,
    style_profile: str,
    rows: list[aiosqlite.Row],
    target_windows: int,
) -> list[dict]:
    sys_prompt = _build_stage_a_system_prompt(replica_type, style_profile)
    windows = _build_stage_a_windows(rows, target_windows)
    summaries: list[dict] = []
    total_win = len(windows)
    stage_log("复刻模板", f"StageA 分段摘要开始，共 {total_win} 个窗口", status="running")
    for i, win in enumerate(windows, start=1):
        context = _rows_to_context(win, context_max_chars=5000)
        if not context:
            continue
        stage_log("复刻模板", f"StageA 正在处理窗口 {i}/{total_win}…", status="running")
        user = f"【窗口序号】{i}\n【窗口ASR】\n{context}"
        raw = await llm.chat(messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}])
        cleaned = extract_json_object(raw if isinstance(raw, str) else "")
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("stageA json parse failed at window=%s", i)
            continue
        if isinstance(parsed, dict):
            summaries.append(parsed)
    return summaries


_ALLOWED_SLOT_ROLES = {"hook", "context", "highlight", "cta"}


def _sanitize_slots(raw: object) -> list[dict]:
    """
    规范化 LLM 输出的 slots：
    - 只保留 role 落在 {hook,context,highlight,cta} 的槽位（编排器强约束）
    - 缺失 role 的槽位尝试按 name 兜底映射，仍无效则丢弃
    - 兜底：若结果为空，按 replica_type 角色集合生成一个最小默认序列
    """
    _NAME_TO_ROLE = {
        "hook": "hook", "钩子": "hook", "开场": "hook", "opening": "hook",
        "context": "context", "背景": "context", "铺垫": "context", "setting": "context", "background": "context",
        "highlight": "highlight", "亮点": "highlight", "冲突": "highlight", "高潮": "highlight", "proof": "highlight",
        "cta": "cta", "行动": "cta", "收口": "cta", "结尾": "cta",
    }
    out: list[dict] = []
    if isinstance(raw, list):
        for s in raw:
            if not isinstance(s, dict):
                continue
            role = str(s.get("role") or "").strip().lower()
            if role not in _ALLOWED_SLOT_ROLES:
                name = str(s.get("name") or "").strip().lower()
                role = _NAME_TO_ROLE.get(name, "")
            if role not in _ALLOWED_SLOT_ROLES:
                continue
            slot = {
                "name": str(s.get("name") or role).strip() or role,
                "role": role,
                "description": str(s.get("description") or "").strip(),
            }
            dr = s.get("duration_ratio")
            if isinstance(dr, (int, float)) and 0 < float(dr) <= 1:
                slot["duration_ratio"] = float(dr)
            out.append(slot)
    return out


def _calc_quality_signals(template_json: dict, *, summary_count: int, expected_chapters: int) -> dict:
    chapters = template_json.get("chapter_plan")
    chapter_count = len(chapters) if isinstance(chapters, list) else 0
    coverage = min(1.0, summary_count / max(1, expected_chapters))
    coherence = min(1.0, chapter_count / max(1, expected_chapters))
    density = template_json.get("quality_signals", {}).get("density_stability")
    density_stability = float(density) if isinstance(density, (int, float)) else 0.7
    return {
        "coverage": round(coverage, 3),
        "coherence": round(coherence, 3),
        "density_stability": round(max(0.0, min(1.0, density_stability)), 3),
    }


def _replica_template_id_dynamic(template_id: str) -> str:
    """复刻模板对应的动态 preset id（注册进 template_config 的 key）。"""
    return f"replica_dyn_{template_id[:8]}"


def _build_template_def_spec(template_json: dict, *, label: str) -> dict:
    """
    把复刻模板的 template_json 转成 template_config.TemplateDefSpec 结构。
    slots 取自三层结构里的 slots（已 sanitize）；若为空，按 structure/默认兜底。
    pace/tone 容错。
    """
    pace = str(template_json.get("pace") or "medium")
    if pace not in ("slow", "medium", "fast"):
        pace = "medium"
    tone = str(template_json.get("tone") or "neutral")
    if tone not in ("calm", "neutral", "energetic"):
        tone = "neutral"

    slots_raw = template_json.get("slots")
    slots = _sanitize_slots(slots_raw)
    if not slots:
        # 兜底：按 structure role 序列生成最小 slot
        structure = template_json.get("structure")
        if isinstance(structure, list) and structure:
            seen = set()
            for s in structure:
                role = str(s).strip().lower() if isinstance(s, str) else ""
                # structure 元素可能是 "hook"/"opening" 等名字，映射成合法 role
                role_map = {"hook": "hook", "context": "context", "background": "context",
                            "highlight": "highlight", "proof": "highlight", "cta": "cta",
                            "opening": "hook", "setup": "context"}
                mapped = role_map.get(role, "")
                if mapped and mapped not in seen:
                    seen.add(mapped)
                    slots.append({"name": role or mapped, "role": mapped, "description": ""})
        if not slots:
            slots = [
                {"name": "hook", "role": "hook", "description": "开场强钩子成品句"},
                {"name": "context", "role": "context", "description": "背景铺垫一句"},
                {"name": "highlight", "role": "highlight", "description": "核心亮点一句"},
                {"name": "cta", "role": "cta", "description": "收口行动一句"},
            ]
    return {"label": label, "slots": slots, "pace": pace, "tone": tone}


def _register_replica_template_in_memory(template_id: str, template_json: dict, *, label: str) -> str:
    """
    把一条复刻模板注册进 template_config.TEMPLATES，使其成为 auto_edit 可消费的动态 preset。
    返回动态 preset id（如 replica_dyn_abcd1234）。
    """
    from app.core.auto_edit_v2.template_config import register_template

    dyn_id = _replica_template_id_dynamic(template_id)
    spec = _build_template_def_spec(template_json, label=label)
    register_template(dyn_id, spec)
    return dyn_id


async def register_replica_templates_from_db() -> int:
    """
    app 启动恢复：把 replica_templates 表里 status=confirmed 的模板批量注册进内存。
    返回成功注册数量。供 main.py lifespan 调用。
    """
    db = await get_db_conn()
    count = 0
    try:
        cur = await db.execute(
            "SELECT id, name, template_json FROM replica_templates WHERE status = 'confirmed'"
        )
        rows = await cur.fetchall()
        for r in rows:
            try:
                tj_raw = r["template_json"]
                tj = json.loads(tj_raw) if isinstance(tj_raw, str) else tj_raw
                if not isinstance(tj, dict):
                    continue
                label = (str(r["name"]) if r["name"] else f"复刻模板_{str(r['id'])[:8]}") or "复刻模板"
                _register_replica_template_in_memory(str(r["id"]), tj, label=label)
                count += 1
            except Exception:
                logger.warning("启动恢复复刻模板注册失败 template_id=%s", r["id"])
    finally:
        await db.close()
    if count:
        logger.info("启动恢复：已注册 %d 个复刻模板为动态 preset", count)
    return count


def _is_template_quality_ok(template_json: dict, *, expected_min_chapters: int) -> bool:
    structure = template_json.get("structure")
    chapters = template_json.get("chapter_plan")
    if not isinstance(structure, list) or len(structure) < 5:
        return False
    if not isinstance(chapters, list) or len(chapters) < expected_min_chapters:
        return False
    return True


@router.post("/ingest", response_model=ReplicaIngestResponse)
async def ingest_reference_video(req: ReplicaIngestRequest) -> ReplicaIngestResponse:
    """
    通过 URL 下载参考视频并入库（status=pending）。
    前端随后调用 /api/videos/{id}/process-ws 触发 ASR。
    """
    video_id = str(uuid.uuid4())
    name = (req.title or "").strip() or f"replica_source_{video_id[:8]}"

    file_path = await _download_reference_video(req, video_id=video_id)

    # 可选：记录 duration（用于 UI 展示/后续预算；失败不影响）
    duration = None
    try:
        duration = probe_duration(file_path)
    except Exception:
        duration = None
    thumbnail_path = generate_thumbnail(file_path, video_id)

    # 若超时长限制：MVP 不做二次转码（避免引入额外复杂度）
    # 后续可以在这里扩展为 ffmpeg trim。

    db = await get_db_conn()
    try:
        # 写入 videos 行（duration 可先不填，process 可后续覆盖/不覆盖都不影响 ASR）
        await db.execute(
            """
            INSERT INTO videos (id, name, file_path, thumbnail_path, duration, total_clips, split_mode, status, is_replica_ref, upload_at)
            VALUES (?, ?, ?, ?, ?, 0, 'scene', 'pending', 1, ?)
            """,
            (video_id, name, to_stored_path(file_path), to_stored_path(thumbnail_path), duration, _utc_now_iso()),
        )
        await db.commit()
    finally:
        await db.close()

    return ReplicaIngestResponse(video_id=video_id, name=name, status="pending")


async def _generate_replica_template_core(
    video_id: str,
    *,
    replica_type: str,
    style_profile: str,
    quality_mode: str,
    max_clips: int,
    auto_status: str = "draft",
) -> dict:
    """
    复刻模板核心生成逻辑（与 HTTP 层解耦）：读全字段多模态 clips → StageA 分窗摘要 → StageB 合并模板 → 入库。

    供 HTTP 路由 /generate-template 与预处理 pipeline 后置 step 复用。
    - auto_status: 入库时落的状态（pipeline 后置直接 confirmed；HTTP 默认 draft）。
    - 失败抛 ReplicaGenerateError（携带 detail / status_code）。
    - 成功返回 {"template_id", "template_json", "template_guide", "pace", "tone", "structure", "status"}。
    """
    db = await get_db_conn()
    source_url: str | None = None
    raw_rows: list[aiosqlite.Row] = []  # type: ignore[name-defined]
    try:
        selected_replica_type = replica_type if replica_type in _REPLICA_TYPE_RULES else _REPLICA_TYPE_DEFAULT
        sp = (style_profile or "").strip() or _STYLE_PROFILE_FALLBACK
        qm = quality_mode if quality_mode in ("balanced", "high_quality") else _QUALITY_DEFAULT
        cfg_by_type = _REPLICA_TYPE_RULES[selected_replica_type]

        raw_rows = await _fetch_reference_asr_rows(db, video_id, max_clips=max_clips)
        sampled_rows = _select_rows_by_ratio(raw_rows, cfg_by_type["sampling"], max_clips)
        context = _rows_to_context(sampled_rows, context_max_chars=int(cfg_by_type["context_chars"]))
        if not sampled_rows or not context:
            raise ReplicaGenerateError(
                "未找到参考视频的 ASR 内容。请先触发 /api/videos/{video_id}/process（至少完成 asr）。",
                status_code=400,
            )
        # 来源统一从 videos 表读取：链接导入可落 source_url，本地上传/素材库则为 None
        # 兼容旧库：videos 可能不存在 source_url 列
        try:
            cur = await db.execute("SELECT source_url FROM videos WHERE id = ?", (video_id,))
            video_row = await cur.fetchone()
            source_url = (str(video_row["source_url"]).strip() if video_row and video_row["source_url"] else None)
        except (sqlite3.OperationalError, aiosqlite.OperationalError):
            source_url = None

        cfg = await LLMConfig.get_llm_params_with_defaults(
            db,
            base_url_key="llm_base_url",
            api_key_key="llm_api_key",
            model_key="llm_model",
            fallback_model_key="vlm_model",
            temperature_key="llm_temperature",
            max_tokens_key="llm_max_tokens",
            default_temperature=0.35,
            default_max_tokens=65536,
        )
    finally:
        await db.close()

    # 这里用单独连接再走 LLM，不复用 db 连接变量（减少误用风险）
    llm = LLMClient(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        model=cfg["model"],
        temperature=cfg["temperature"],
        max_tokens=cfg["max_tokens"],
        timeout=3600,
    )

    stage_log(
        "复刻模板",
        f"开始生成复刻模板 video_id={video_id} type={selected_replica_type}",
        status="running",
    )
    stage_a_target = int(cfg_by_type["chunk_target"])
    if qm == "balanced":
        stage_a_target = max(3, stage_a_target - 2)
    stage_a = await _run_stage_a_summaries(
        llm,
        replica_type=selected_replica_type,
        style_profile=sp,
        rows=sampled_rows,
        target_windows=stage_a_target,
    )
    if not stage_a:
        raise ReplicaGenerateError("分段摘要失败，无法生成模板")

    stage_log("复刻模板", "StageB 正在生成最终模板 JSON…", status="running")
    stage_b_prompt = _build_stage_b_system_prompt(selected_replica_type, sp)
    stage_b_user = (
        f"【复刻类型】\n{selected_replica_type}\n\n"
        f"【风格标签】\n{sp}\n\n"
        "【参考视频多模态上下文（台词+画面+情绪+关键词，采样）】\n"
        f"{context}\n\n"
        "【分段摘要（StageA）】\n"
        f"{json.dumps(stage_a, ensure_ascii=False)}\n\n"
        "请输出最终 JSON 模板。"
    )
    raw = await llm.chat(messages=[{"role": "system", "content": stage_b_prompt}, {"role": "user", "content": stage_b_user}])
    if not isinstance(raw, str) or not raw.strip():
        raise ReplicaGenerateError("LLM 返回模板为空")

    cleaned = extract_json_object(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        raise ReplicaGenerateError("LLM 返回的模板 JSON 无法解析")

    if not isinstance(data, dict) or "template_guide" not in data or "template_json" not in data:
        raise ReplicaGenerateError("LLM 返回的模板 JSON 缺少必要字段")

    template_id = str(uuid.uuid4())
    pace = data.get("pace")
    tone = data.get("tone")
    structure = data.get("structure")
    template_json = data.get("template_json") or {}
    template_guide = str(data.get("template_guide") or "").strip()
    if not template_guide:
        raise ReplicaGenerateError("LLM 未生成 template_guide")
    if not isinstance(template_json, dict):
        template_json = {"raw": template_json}

    template_json.setdefault("replica_type", selected_replica_type)
    template_json.setdefault("style_profile", sp)
    template_json.setdefault("quality_mode", qm)
    template_json.setdefault("structure", structure if isinstance(structure, list) else [])
    template_json.setdefault("narrative_arc", "")
    template_json.setdefault("chapter_plan", [])
    template_json.setdefault("transition_patterns", [])
    template_json.setdefault("cta_style", "")
    # 三层结构字段兜底（slots/hook_templates/shot_rhythm/emotion_curve）
    template_json.setdefault("slots", [])
    template_json.setdefault("hook_templates", [])
    template_json.setdefault("shot_rhythm", {})
    template_json.setdefault("emotion_curve", [])
    # 规范 slots 的 role（必须落在编排器可消费的集合内）
    template_json["slots"] = _sanitize_slots(template_json.get("slots"))
    template_json["quality_signals"] = _calc_quality_signals(
        template_json,
        summary_count=len(stage_a),
        expected_chapters=max(5, stage_a_target // 2),
    )

    if not _is_template_quality_ok(template_json, expected_min_chapters=3) and qm == "high_quality":
        logger.info("replica quality retry video_id=%s type=%s", video_id, selected_replica_type)
        raw_retry = await llm.chat(
            messages=[
                {"role": "system", "content": stage_b_prompt},
                {"role": "user", "content": stage_b_user + "\n\n请补足章节完整度，确保 chapter_plan 至少 3 章并与 structure 一致。"},
            ]
        )
        cleaned_retry = extract_json_object(raw_retry if isinstance(raw_retry, str) else "")
        try:
            data_retry = json.loads(cleaned_retry)
            maybe_tj = data_retry.get("template_json")
            if isinstance(maybe_tj, dict):
                template_json = maybe_tj
                template_guide = str(data_retry.get("template_guide") or template_guide).strip()
                pace = data_retry.get("pace", pace)
                tone = data_retry.get("tone", tone)
                structure = data_retry.get("structure", structure)
                template_json.setdefault("replica_type", selected_replica_type)
                template_json.setdefault("style_profile", sp)
                template_json.setdefault("quality_mode", qm)
                template_json.setdefault("chapter_plan", [])
                template_json.setdefault("slots", [])
                template_json.setdefault("hook_templates", [])
                template_json.setdefault("shot_rhythm", {})
                template_json.setdefault("emotion_curve", [])
                template_json["slots"] = _sanitize_slots(template_json.get("slots"))
                template_json["quality_signals"] = _calc_quality_signals(
                    template_json,
                    summary_count=len(stage_a),
                    expected_chapters=max(5, stage_a_target // 2),
                )
        except Exception:
            logger.warning("replica quality retry parse failed video_id=%s", video_id)

    # 入库
    db = await get_db_conn()
    try:
        # 生成一个可用的默认模板名（用户可在确认时再改）
        cur = await db.execute("SELECT name FROM videos WHERE id = ?", (video_id,))
        vrow = await cur.fetchone()
        vname = (str(vrow["name"]) if vrow and vrow["name"] else "").strip()
        default_name = vname or f"复刻模板_{template_id[:8]}"
        await db.execute(
            """
            INSERT INTO replica_templates
              (id, name, source_video_id, source_url, template_json, template_guide, pace, tone, structure_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                template_id,
                default_name,
                video_id,
                source_url,
                json.dumps(template_json, ensure_ascii=False),
                template_guide,
                pace,
                tone,
                json.dumps(structure, ensure_ascii=False),
                auto_status,
                _utc_now_iso(),
                _utc_now_iso(),
            ),
        )
        await db.commit()
    finally:
        await db.close()

    stage_log("复刻模板", f"模板已生成 template_id={template_id[:8]}…", status="done")
    # confirmed 状态的模板立即注册为动态 preset，供 auto_edit 消费（draft 等用户确认后再注册）
    if auto_status == "confirmed":
        try:
            _register_replica_template_in_memory(
                template_id, template_json if isinstance(template_json, dict) else {},
                label=default_name,
            )
        except Exception:
            logger.warning("复刻模板动态注册失败（不影响入库）template_id=%s", template_id)
    return {
        "template_id": template_id,
        "template_json": template_json if isinstance(template_json, dict) else {"raw": template_json},
        "template_guide": template_guide,
        "pace": pace,
        "tone": tone,
        "structure": structure,
        "status": auto_status,
    }


@router.post("/{video_id}/generate-template", response_model=ReplicaTemplateDraft)
async def generate_replica_template(
    video_id: str,
    req: ReplicaGenerateTemplateRequest,
) -> ReplicaTemplateDraft:
    """
    基于参考视频已处理的 clips（多模态：ASR+VLM+enrich）生成复刻模板草案（draft）。
    """
    try:
        result = await _generate_replica_template_core(
            video_id,
            replica_type=req.replica_type,
            style_profile=req.style_profile or "",
            quality_mode=req.quality_mode,
            max_clips=req.max_clips,
            auto_status="draft",
        )
    except ReplicaGenerateError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return ReplicaTemplateDraft(
        template_id=result["template_id"],
        template_json=result["template_json"],
        template_guide=result["template_guide"],
        status="draft",
    )


@router.post("/template/{template_id}/confirm", response_model=ReplicaTemplateConfirmed)
async def confirm_replica_template(
    template_id: str,
    req: ReplicaConfirmTemplateRequest,
) -> ReplicaTemplateConfirmed:
    """
    用户确认模板（把 draft 置为 confirmed，并允许覆盖 template_guide / template_json）。
    """
    db = await get_db_conn()
    try:
        cursor = await db.execute("SELECT * FROM replica_templates WHERE id = ?", (template_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="模板不存在")

        template_json = row["template_json"]
        try:
            template_json_dict = json.loads(template_json) if isinstance(template_json, str) else template_json
        except Exception:
            template_json_dict = {}

        if req.template_json is not None:
            template_json_dict = req.template_json

        new_template_json_str = json.dumps(template_json_dict, ensure_ascii=False)
        new_guide = req.template_guide.strip()
        if not new_guide:
            raise HTTPException(status_code=400, detail="template_guide 不能为空")

        new_name = (req.name or "").strip() or (str(row["name"] or "").strip() or None)

        await db.execute(
            """
            UPDATE replica_templates
            SET name = COALESCE(?, name),
                template_json = ?,
                template_guide = ?,
                status = 'confirmed',
                updated_at = ?
            WHERE id = ?
            """,
            (new_name, new_template_json_str, new_guide, _utc_now_iso(), template_id),
        )
        await db.commit()
    finally:
        await db.close()

    # 确认后立即注册为动态 preset，供 auto_edit 消费
    try:
        tj_for_reg = template_json_dict if isinstance(template_json_dict, dict) else {}
        label = (new_name or f"复刻模板_{template_id[:8]}") or "复刻模板"
        _register_replica_template_in_memory(template_id, tj_for_reg, label=label)
    except Exception:
        logger.warning("复刻模板确认后动态注册失败（不影响确认）template_id=%s", template_id)

    return ReplicaTemplateConfirmed(
        template_id=template_id,
        template_json=template_json_dict if isinstance(template_json_dict, dict) else {"raw": template_json_dict},
        template_guide=new_guide,
        status="confirmed",
    )


@router.get("/template/{template_id}", response_model=ReplicaTemplateGetResponse)
async def get_replica_template(template_id: str) -> ReplicaTemplateGetResponse:
    db = await get_db_conn()
    try:
        cursor = await db.execute("SELECT * FROM replica_templates WHERE id = ?", (template_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="模板不存在")

        try:
            template_json = json.loads(row["template_json"]) if isinstance(row["template_json"], str) else row["template_json"]
        except Exception:
            template_json = {}

        try:
            structure_json = json.loads(row["structure_json"]) if isinstance(row["structure_json"], str) else row["structure_json"]
        except Exception:
            structure_json = None

        tj_dict = template_json if isinstance(template_json, dict) else {}
        slots_count = len(_sanitize_slots(tj_dict.get("slots")))
        is_confirmed = str(row["status"]) == "confirmed"

        return ReplicaTemplateGetResponse(
            template_id=row["id"],
            name=(str(row["name"]) if row["name"] else None),
            source_video_id=row["source_video_id"],
            source_url=row["source_url"],
            template_json=template_json if isinstance(template_json, dict) else {"raw": template_json},
            template_guide=row["template_guide"],
            pace=row["pace"],
            tone=row["tone"],
            structure=structure_json,
            status=row["status"],
            template_preset_id=_replica_template_id_dynamic(str(row["id"])) if is_confirmed else None,
            has_slots=slots_count > 0,
        )
    finally:
        await db.close()


@router.get("/templates", response_model=ReplicaTemplateListResponse)
async def list_replica_templates(
    q: str | None = Query(None, description="搜索关键词（匹配 source_url / template_guide）"),
    status: str | None = Query(None, description="过滤状态：draft/confirmed（可选）"),
    replica_type: str | None = Query(None, description="过滤类型：short_video/film_commentary/scene_story"),
    style_profile: str | None = Query(None, description="过滤风格标签（可选）"),
    sort: str | None = Query("updated_desc", description="排序：updated_desc/created_desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=48),
) -> ReplicaTemplateListResponse:
    """
    模板库列表：支持搜索、分页、删除前的可视化浏览。
    """
    qq = (q or "").strip()
    st = (status or "").strip().lower()
    type_filter = (replica_type or "").strip().lower()
    style_filter = (style_profile or "").strip().lower()
    order_by = "updated_at DESC"
    if (sort or "").strip().lower() == "created_desc":
        order_by = "created_at DESC"

    where: list[str] = []
    params: list[object] = []
    if st in ("draft", "confirmed"):
        where.append("status = ?")
        params.append(st)
    if qq:
        where.append("(COALESCE(name,'') LIKE ? OR COALESCE(source_url,'') LIKE ? OR COALESCE(template_guide,'') LIKE ?)")
        like = f"%{qq}%"
        params.extend([like, like, like])

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    offset = (page - 1) * page_size

    db = await get_db_conn()
    try:
        cur2 = await db.execute(
            f"""
            SELECT id, name, source_video_id, source_url, pace, tone, status, created_at, updated_at, template_guide, template_json
            FROM replica_templates
            {where_sql}
            ORDER BY {order_by}
            """,
            [*params],
        )
        rows = await cur2.fetchall()

        filtered_rows: list[aiosqlite.Row] = []  # type: ignore[name-defined]
        for r in rows:
            rt, sp, _qs = _parse_template_meta(r["template_json"])
            if type_filter and (rt or "").lower() != type_filter:
                continue
            if style_filter and style_filter not in (sp or "").lower():
                continue
            filtered_rows.append(r)

        total = len(filtered_rows)
        total_pages = max(1, (total + page_size - 1) // page_size) if page_size else 1
        if page > total_pages and total_pages > 0:
            page = total_pages
        offset = (page - 1) * page_size
        page_rows = filtered_rows[offset: offset + page_size]

        items: list[ReplicaTemplateListItem] = []
        for r in page_rows:
            guide = str(r["template_guide"] or "")
            rt, sp, qs = _parse_template_meta(r["template_json"])
            tj_for_meta = r["template_json"]
            if isinstance(tj_for_meta, str):
                try:
                    tj_for_meta = json.loads(tj_for_meta)
                except Exception:
                    tj_for_meta = {}
            tj_dict = tj_for_meta if isinstance(tj_for_meta, dict) else {}
            slots_count = len(_sanitize_slots(tj_dict.get("slots")))
            items.append(
                ReplicaTemplateListItem(
                    template_id=str(r["id"]),
                    name=(str(r["name"]) if r["name"] else None),
                    source_video_id=str(r["source_video_id"]),
                    source_url=(str(r["source_url"]) if r["source_url"] else None),
                    pace=(str(r["pace"]) if r["pace"] else None),
                    tone=(str(r["tone"]) if r["tone"] else None),
                    status=("confirmed" if str(r["status"]) == "confirmed" else "draft"),
                    created_at=str(r["created_at"] or ""),
                    updated_at=str(r["updated_at"] or ""),
                    guide_preview=_safe_preview(guide),
                    replica_type=rt,
                    style_profile=sp,
                    quality_signals=qs,
                    template_preset_id=_replica_template_id_dynamic(str(r["id"])) if str(r["status"]) == "confirmed" else None,
                    has_slots=slots_count > 0,
                )
            )

        return ReplicaTemplateListResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )
    finally:
        await db.close()


@router.delete("/template/{template_id}")
async def delete_replica_template(template_id: str):
    db = await get_db_conn()
    try:
        cur = await db.execute("SELECT id FROM replica_templates WHERE id = ?", (template_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="模板不存在")
        await db.execute("DELETE FROM replica_templates WHERE id = ?", (template_id,))
        await db.commit()
        return {"ok": True, "template_id": template_id}
    finally:
        await db.close()


@router.patch("/template/{template_id}")
async def rename_replica_template(template_id: str, payload: dict):
    """
    模板重命名：{"name": "..."}。
    """
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 不能为空")
    db = await get_db_conn()
    try:
        cur = await db.execute("SELECT id FROM replica_templates WHERE id = ?", (template_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="模板不存在")
        await db.execute(
            "UPDATE replica_templates SET name = ?, updated_at = ? WHERE id = ?",
            (name, _utc_now_iso(), template_id),
        )
        await db.commit()
        return {"ok": True, "template_id": template_id, "name": name}
    finally:
        await db.close()

