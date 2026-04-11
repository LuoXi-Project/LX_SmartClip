"""replica.py — 复刻模板生成（链接下载 + ASR 驱动）"""
from __future__ import annotations

import json
import logging
import os
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
from app.utils.paths import ensure_storage_subpath
from app.utils.video_thumbnail import generate_thumbnail
from app.utils.yt_dlp_downloader import YtDlpDownloadError, download_video_with_yt_dlp

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/replica", tags=["replica"])

_STORAGE_VIDEOS_DIR = ensure_storage_subpath("videos")

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


def _build_stage_a_system_prompt(replica_type: str, style_profile: str) -> str:
    cfg = _REPLICA_TYPE_RULES.get(replica_type, _REPLICA_TYPE_RULES[_REPLICA_TYPE_DEFAULT])
    return f"""
你是“{cfg['label']}”复刻分析助手，当前风格标签是“{style_profile}”。
你将收到单个时间窗的 ASR 文本，请先做局部结构化摘要。

只输出 JSON，不要解释，结构严格为：
{{
  "window_role": "该时间窗在整体叙事中的作用",
  "summary": "该时间窗关键内容（仅基于ASR）",
  "tone": "calm|neutral|energetic",
  "pace": "slow|medium|fast",
  "signals": {{
    "emotion_curve": "情绪变化",
    "transition_pattern": "衔接方式",
    "information_density": "low|medium|high"
  }}
}}
"""


def _build_stage_b_system_prompt(replica_type: str, style_profile: str) -> str:
    cfg = _REPLICA_TYPE_RULES.get(replica_type, _REPLICA_TYPE_RULES[_REPLICA_TYPE_DEFAULT])
    role_csv = ", ".join(cfg["roles"])
    return f"""
你是“{cfg['label']}复刻模板”的高级分析助手，风格标签“{style_profile}”。
你会收到多个时间窗摘要，请合并成最终复刻模板。

任务：
1) 输出 pace/tone/structure，structure 长度要求：{cfg['structure_len']}，并优先使用角色集合：{role_csv}
2) 生成 template_json（用于长期复用）
3) 生成 template_guide（可直接粘贴到后续文案/成片规划提示词）
4) 补充 narrative_arc/chapter_plan/transition_patterns/cta_style/quality_signals

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
  "template_guide": "复刻执行说明"
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
    用 yt-dlp 下载参考视频到 storage/videos，返回最终落盘文件路径。
    """
    try:
        return download_video_with_yt_dlp(url=req.url, output_dir=_STORAGE_VIDEOS_DIR, file_stem=video_id)
    except YtDlpDownloadError as exc:
        detail = str(exc)
        status = 501 if "未检测到 yt-dlp" in detail else 502
        raise HTTPException(status_code=status, detail=detail) from exc


async def _insert_video_row(*, video_id: str, name: str, file_path: str) -> None:
    db = await get_db_conn()
    try:
        await db.execute(
            """
            INSERT INTO videos (id, name, file_path, thumbnail_path, duration, total_clips, split_mode, status, upload_at)
            VALUES (?, ?, ?, ?, NULL, 0, 'scene', 'pending', ?)
            """,
            (video_id, name, file_path, None, _utc_now_iso()),
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
        SELECT id, start_time, end_time, asr_text
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
        clip_id = str(r["id"])
        t0 = float(r["start_time"] or 0.0)
        t1 = float(r["end_time"] or 0.0)
        asr = (r["asr_text"] or "").strip()
        if not asr:
            continue

        header = f"\n[clip_id={clip_id}] [{_fmt_time(t0)}→{_fmt_time(t1)}]"
        body = f"台词：{asr}"
        block = header + "\n" + body
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
        SELECT id, start_time, end_time, asr_text
        FROM clips
        WHERE video_id = ?
          AND TRIM(COALESCE(asr_text, '')) <> ''
        ORDER BY start_time
        LIMIT ?
        """,
        (video_id, max_clips),
    ) as cur:
        return await cur.fetchall()


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
        clip_id = str(r["id"])
        t0 = float(r["start_time"] or 0.0)
        t1 = float(r["end_time"] or 0.0)
        asr = (r["asr_text"] or "").strip()
        if not asr:
            continue
        block = f"\n[clip_id={clip_id}] [{_fmt_time(t0)}→{_fmt_time(t1)}]\n台词：{asr}"
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
    for i, win in enumerate(windows, start=1):
        context = _rows_to_context(win, context_max_chars=5000)
        if not context:
            continue
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
            INSERT INTO videos (id, name, file_path, thumbnail_path, duration, total_clips, split_mode, status, upload_at)
            VALUES (?, ?, ?, ?, ?, 0, 'scene', 'pending', ?)
            """,
            (video_id, name, file_path, thumbnail_path, duration, _utc_now_iso()),
        )
        await db.commit()
    finally:
        await db.close()

    return ReplicaIngestResponse(video_id=video_id, name=name, status="pending")


@router.post("/{video_id}/generate-template", response_model=ReplicaTemplateDraft)
async def generate_replica_template(
    video_id: str,
    req: ReplicaGenerateTemplateRequest,
) -> ReplicaTemplateDraft:
    """
    基于参考视频已处理的 clips(asr_text) 生成复刻模板草案（draft）。
    """
    db = await get_db_conn()
    source_url: str | None = None
    raw_rows: list[aiosqlite.Row] = []  # type: ignore[name-defined]
    try:
        selected_replica_type = req.replica_type if req.replica_type in _REPLICA_TYPE_RULES else _REPLICA_TYPE_DEFAULT
        style_profile = (req.style_profile or "").strip() or _STYLE_PROFILE_FALLBACK
        quality_mode = req.quality_mode if req.quality_mode in ("balanced", "high_quality") else _QUALITY_DEFAULT
        cfg_by_type = _REPLICA_TYPE_RULES[selected_replica_type]

        raw_rows = await _fetch_reference_asr_rows(db, video_id, max_clips=req.max_clips)
        sampled_rows = _select_rows_by_ratio(raw_rows, cfg_by_type["sampling"], req.max_clips)
        context = _rows_to_context(sampled_rows, context_max_chars=int(cfg_by_type["context_chars"]))
        if not sampled_rows or not context:
            raise HTTPException(
                status_code=400,
                detail="未找到参考视频的 ASR 内容。请先触发 /api/videos/{video_id}/process（至少完成 asr）。",
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
            default_max_tokens=40960,
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

    stage_a_target = int(cfg_by_type["chunk_target"])
    if quality_mode == "balanced":
        stage_a_target = max(3, stage_a_target - 2)
    stage_a = await _run_stage_a_summaries(
        llm,
        replica_type=selected_replica_type,
        style_profile=style_profile,
        rows=sampled_rows,
        target_windows=stage_a_target,
    )
    if not stage_a:
        raise HTTPException(status_code=502, detail="分段摘要失败，无法生成模板")

    stage_b_prompt = _build_stage_b_system_prompt(selected_replica_type, style_profile)
    stage_b_user = (
        f"【复刻类型】\n{selected_replica_type}\n\n"
        f"【风格标签】\n{style_profile}\n\n"
        "【参考视频 ASR（采样上下文）】\n"
        f"{context}\n\n"
        "【分段摘要（StageA）】\n"
        f"{json.dumps(stage_a, ensure_ascii=False)}\n\n"
        "请输出最终 JSON 模板。"
    )
    raw = await llm.chat(messages=[{"role": "system", "content": stage_b_prompt}, {"role": "user", "content": stage_b_user}])
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=502, detail="LLM 返回模板为空")

    cleaned = extract_json_object(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="LLM 返回的模板 JSON 无法解析")

    if not isinstance(data, dict) or "template_guide" not in data or "template_json" not in data:
        raise HTTPException(status_code=502, detail="LLM 返回的模板 JSON 缺少必要字段")

    template_id = str(uuid.uuid4())
    pace = data.get("pace")
    tone = data.get("tone")
    structure = data.get("structure")
    template_json = data.get("template_json") or {}
    template_guide = str(data.get("template_guide") or "").strip()
    if not template_guide:
        raise HTTPException(status_code=502, detail="LLM 未生成 template_guide")
    if not isinstance(template_json, dict):
        template_json = {"raw": template_json}

    template_json.setdefault("replica_type", selected_replica_type)
    template_json.setdefault("style_profile", style_profile)
    template_json.setdefault("quality_mode", quality_mode)
    template_json.setdefault("structure", structure if isinstance(structure, list) else [])
    template_json.setdefault("narrative_arc", "")
    template_json.setdefault("chapter_plan", [])
    template_json.setdefault("transition_patterns", [])
    template_json.setdefault("cta_style", "")
    template_json["quality_signals"] = _calc_quality_signals(
        template_json,
        summary_count=len(stage_a),
        expected_chapters=max(5, stage_a_target // 2),
    )

    if not _is_template_quality_ok(template_json, expected_min_chapters=3) and quality_mode == "high_quality":
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
                template_json.setdefault("style_profile", style_profile)
                template_json.setdefault("quality_mode", quality_mode)
                template_json.setdefault("chapter_plan", [])
                template_json["quality_signals"] = _calc_quality_signals(
                    template_json,
                    summary_count=len(stage_a),
                    expected_chapters=max(5, stage_a_target // 2),
                )
        except Exception:
            logger.warning("replica quality retry parse failed video_id=%s", video_id)

    # 入库 draft
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)
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
                _utc_now_iso(),
                _utc_now_iso(),
            ),
        )
        await db.commit()
    finally:
        await db.close()

    return ReplicaTemplateDraft(
        template_id=template_id,
        template_json=template_json if isinstance(template_json, dict) else {"raw": template_json},
        template_guide=template_guide,
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

