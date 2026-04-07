"""replica.py — 复刻模板生成（链接下载 + ASR 驱动）"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone

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
from app.utils.video_thumbnail import generate_thumbnail
from app.utils.yt_dlp_downloader import YtDlpDownloadError, download_video_with_yt_dlp

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/replica", tags=["replica"])

_STORAGE_VIDEOS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "storage", "videos")
)

_TEMPLATE_SYS_PROMPT = """
你是“短视频复刻模板”的分析助手。
你将收到：参考视频的 ASR 片段（带 clip_id 与时间窗）文本。

任务：
1) 归纳该参考视频的“复刻写作方式”，包括：
   - pace（节奏快慢）：slow/medium/fast
   - tone（情绪基调）：calm/neutral/energetic
   - structure（结构角色顺序）：从以下集合中生成 5 段，且按出现顺序输出
     可选 role 集合：hook, context, highlight, proof, cta
2) 生成 template_json（结构化模板）用于长期复用。
3) 生成 template_guide（中文字符串），用于后续把“用户自己的素材/台词”套入同一写作节奏与句式。

硬约束：
- 只输出 JSON，不要包含任何 Markdown、不做解释。
- JSON 结构严格为：
{
  "pace": "slow|medium|fast",
  "tone": "calm|neutral|energetic",
  "structure": ["hook","context","highlight","proof","cta"],
  "template_json": {
    "pace": "...",
    "tone": "...",
    "structure": ["...","...","...","...","..."],
    "slot_guidelines": {
      "hook": "一句话风格+长度+禁忌",
      "context": "...",
      "highlight": "...",
      "proof": "...",
      "cta": "..."
    }
  },
  "template_guide": "后续写作时的复刻约束说明（必须可直接粘贴到文案/成片规划提示词中）"
}

补充说明：
- 参考输入是台词 ASR，不要“臆造”参考视频中没有出现的画面细节。
- 复刻目标是“解说风格/节奏/话术结构”，而不是逐字复述。
- template_guide 中需要包含：句长/停顿节奏、角色分配（hook/context/highlight/proof/cta 的信息密度倾向）、CTA 方式倾向（例如提问/强行动/领券/私信等，用同一模式复刻）。
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_preview(text: str, max_len: int = 160) -> str:
    s = (text or "").strip().replace("\r", "").replace("\t", " ")
    s = " ".join(s.split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


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
    try:
        # 先确认 clips(asr_text) 是否存在
        context = await _build_reference_asr_context(db, video_id, max_clips=req.max_clips)
        if not context:
            raise HTTPException(
                status_code=400,
                detail="未找到参考视频的 ASR 内容。请先触发 /api/videos/{video_id}/process（至少完成 asr）。",
            )

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

    user = (
        "【参考视频 ASR】\n"
        f"{context}\n\n"
        "请根据这些片段推断其复刻写作方式，并输出符合要求的 JSON。"
    )
    raw = await llm.chat(messages=[{"role": "system", "content": _TEMPLATE_SYS_PROMPT}, {"role": "user", "content": user}])
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

    # 入库 draft
    db = await get_db_conn()
    try:
        # 生成一个可用的默认模板名（用户可在确认时再改）
        cur = await db.execute("SELECT name FROM videos WHERE id = ?", (video_id,))
        vrow = await cur.fetchone()
        vname = (str(vrow["name"]) if vrow and vrow["name"] else "").strip()
        default_name = vname or f"复刻模板_{template_id[:8]}"
        source_url = req.url
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
    sort: str | None = Query("updated_desc", description="排序：updated_desc/created_desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(12, ge=1, le=48),
) -> ReplicaTemplateListResponse:
    """
    模板库列表：支持搜索、分页、删除前的可视化浏览。
    """
    qq = (q or "").strip()
    st = (status or "").strip().lower()
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
        cur = await db.execute(f"SELECT COUNT(1) AS c FROM replica_templates {where_sql}", params)
        row = await cur.fetchone()
        total = int(row["c"] or 0) if row else 0
        total_pages = max(1, (total + page_size - 1) // page_size) if page_size else 1
        if page > total_pages and total_pages > 0:
            page = total_pages
            offset = (page - 1) * page_size

        cur2 = await db.execute(
            f"""
            SELECT id, name, source_video_id, source_url, pace, tone, status, created_at, updated_at, template_guide
            FROM replica_templates
            {where_sql}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        )
        rows = await cur2.fetchall()

        items: list[ReplicaTemplateListItem] = []
        for r in rows:
            guide = str(r["template_guide"] or "")
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

