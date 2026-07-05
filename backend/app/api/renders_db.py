"""成片（renders）数据访问层。

双轨追踪：
- 渲染成功时主动调用 record_render_from_path（5 个产出点）
- 首次启动时 scan_and_record 扫描历史文件入库

仿 publish_db.py 范式：get_db_conn + 手写 SQL。
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.db.database import get_db_conn
from app.utils.paths import get_storage_root, storage_public_url_for_file

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return f"rend_{uuid.uuid4().hex[:12]}"


# 后处理变体后缀正则：_bgm_xxx / _master_xxx / _anti_detect_xxx / _mix_anti_detect_xxx
_VARIANT_SUFFIX_RE = re.compile(
    r"_(?:bgm|master|anti_detect|mix_anti_detect)_[0-9a-fA-F]{3,12}$"
)


def derive_title(filename: str) -> str:
    """从文件名去掉扩展名 + 后处理变体后缀，得到基干标题。

    例：autoedit_xxx_20260701_143000_a1b2c3d4_bgm_afb366.mp4 → autoedit_xxx_20260701_143000_a1b2c3d4
    """
    stem = Path(filename).stem
    return _VARIANT_SUFFIX_RE.sub("", stem)


def extract_plan_snapshot(plan_like) -> dict | None:
    """从 plan / job / 类似对象安全提取「方案/方案内容」关键字段，供发布文案生成时回看。

    对智剪 plan（含 mode/style/user_prompt/target_duration/video_id）、影视解说 job
    （mode/style/target_duration）、文案素材脚本（脚本片段）等异构对象统一容错提取。
    """
    if plan_like is None:
        return None
    snap: dict = {}
    # 字符串/标量字段
    for key in ("mode", "style", "user_prompt", "target_duration", "target_duration_sec",
                "duration", "script_text", "title", "tone", "voice", "video_id", "audio_mode"):
        try:
            val = getattr(plan_like, key, None)
        except Exception:
            val = None
        if val is None and isinstance(plan_like, dict):
            val = plan_like.get(key)
        if val in (None, ""):
            continue
        # 标量/字符串直接存；其他类型转 str
        if isinstance(val, (str, int, float, bool)):
            snap[key] = val
        else:
            snap[key] = str(val)
    # plan 内可能还藏着脚本/文案列表（sentences/storyline/script_segments）
    for key in ("sentences", "storyline", "script_segments", "script_lines"):
        try:
            val = getattr(plan_like, key, None)
        except Exception:
            val = None
        if val is None and isinstance(plan_like, dict):
            val = plan_like.get(key)
        if not val:
            continue
        try:
            if isinstance(val, (list, tuple)):
                snap[key] = [str(x)[:300] for x in val][:30]
            else:
                snap[key] = str(val)[:1000]
        except Exception:
            pass
    return snap or None


def _abs_to_storage_rel(abs_path: str) -> str:
    """绝对路径转 storage 相对路径（storage/xxx/burned_videos/a.mp4）。"""
    try:
        root = os.path.normpath(str(get_storage_root().resolve()))
        ap = os.path.normpath(os.path.abspath(abs_path))
        rel = os.path.relpath(ap, root).replace("\\", "/")
        return "storage/" + rel
    except Exception:
        return abs_path.replace("\\", "/")


async def record_render_from_path(
    *,
    abs_path: str,
    source: str,
    material_id: str | None = None,
    title: str | None = None,
    duration: float | None = None,
    material_title: str | None = None,
    plan_json: str | None = None,
) -> str | None:
    """从成片绝对路径记录一条 render（幂等：同 file_path 已存在则跳过）。

    被 5 个渲染产出点和扫描器共用。取时长用 probe_duration（包 run_heavy）。
    material_title / plan_json：携带原素材标题与方案/方案内容快照，
        供后续「一键发布」AI 文案生成时无需回查原任务即可拿到上下文。
    返回 render id；若文件不存在或入库失败返回 None。
    """
    if not abs_path or not os.path.isfile(abs_path):
        logger.debug("record_render: 文件不存在 %s", abs_path)
        return None

    file_path = _abs_to_storage_rel(abs_path)
    public_url = storage_public_url_for_file(abs_path)
    filename = os.path.basename(abs_path)
    if title is None:
        title = derive_title(filename)

    # 取时长（若调用方未提供）
    # 用默认线程池跑 probe_duration（不依赖 blocking_pool，扫描场景 lifespan 外也能用）
    if duration is None:
        try:
            import asyncio
            from app.utils.ffprobe_utils import probe_duration
            loop = asyncio.get_running_loop()
            duration = await loop.run_in_executor(None, probe_duration, abs_path)
        except Exception as exc:
            logger.warning("record_render: 取时长失败 %s: %s", filename, exc)
            duration = 0.0

    try:
        file_size = os.path.getsize(abs_path)
    except OSError:
        file_size = 0

    # mtime 作为创建时间（渲染时间）
    try:
        mtime = os.path.getmtime(abs_path)
        created_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except OSError:
        created_at = _now_iso()

    render_id = _new_id()
    db = await get_db_conn()
    try:
        await db.execute(
            """INSERT OR IGNORE INTO renders
               (id, file_path, public_url, filename, title, source, material_id,
                duration, file_size, created_at, recorded_at,
                material_title, plan_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (render_id, file_path, public_url, filename, title, source, material_id,
             float(duration or 0), file_size, created_at, _now_iso(),
             material_title, plan_json),
        )
        await db.commit()
        # 若是 IGNORE 命中（已存在），查一下真实 id 返回
        cur = await db.execute("SELECT id FROM renders WHERE file_path = ?", (file_path,))
        row = await cur.fetchone()
        return row["id"] if row else render_id
    except Exception as exc:
        logger.warning("record_render: 入库失败 %s: %s", filename, exc)
        return None
    finally:
        await db.close()


async def list_renders(
    *,
    search: str | None = None,
    source: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """分页列出成片，按创建时间倒序。支持 filename/title 搜索 + source 过滤。"""
    where_parts: list[str] = []
    params: list = []
    if search:
        where_parts.append("(filename LIKE ? OR title LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    if source:
        where_parts.append("source = ?")
        params.append(source)
    where_clause = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    db = await get_db_conn()
    try:
        cur = await db.execute(
            f"SELECT * FROM renders{where_clause} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def count_renders(*, search: str | None = None, source: str | None = None) -> int:
    """成片总数（同 list_renders 的过滤条件）。"""
    where_parts: list[str] = []
    params: list = []
    if search:
        where_parts.append("(filename LIKE ? OR title LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    if source:
        where_parts.append("source = ?")
        params.append(source)
    where_clause = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    db = await get_db_conn()
    try:
        cur = await db.execute(f"SELECT COUNT(*) AS c FROM renders{where_clause}", params)
        row = await cur.fetchone()
        return int(row["c"]) if row else 0
    finally:
        await db.close()


async def get_render(render_id: str) -> dict | None:
    db = await get_db_conn()
    try:
        cur = await db.execute("SELECT * FROM renders WHERE id = ?", (render_id,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def delete_render(render_id: str) -> dict | None:
    """删除成片：DB 记录 + 物理文件 + 缩略图。返回被删记录（含路径供日志）。"""
    rec = await get_render(render_id)
    if not rec:
        return None

    db = await get_db_conn()
    try:
        await db.execute("DELETE FROM renders WHERE id = ?", (render_id,))
        await db.commit()
    finally:
        await db.close()

    # 删物理文件 + 缩略图
    from app.utils.paths import resolve_stored_path
    try:
        abs_path = resolve_stored_path(rec["file_path"])
        if os.path.isfile(abs_path):
            os.remove(abs_path)
    except Exception as exc:
        logger.warning("删除成片文件失败 %s: %s", rec.get("filename"), exc)

    if rec.get("thumbnail_path"):
        try:
            thumb_abs = resolve_stored_path(rec["thumbnail_path"])
            if os.path.isfile(thumb_abs):
                os.remove(thumb_abs)
        except Exception:
            pass

    return rec


async def mark_thumbnail(render_id: str, thumbnail_path: str) -> None:
    """标记缩略图已生成。"""
    db = await get_db_conn()
    try:
        await db.execute(
            "UPDATE renders SET thumbnail_path = ? WHERE id = ?",
            (thumbnail_path, render_id),
        )
        await db.commit()
    finally:
        await db.close()


async def find_existing_by_path(file_path: str) -> dict | None:
    """按 file_path 查是否已入库（扫描器去重用）。"""
    db = await get_db_conn()
    try:
        cur = await db.execute("SELECT * FROM renders WHERE file_path = ?", (file_path,))
        row = await cur.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def update_ai_context(
    render_id: str,
    *,
    asr_text: str | None = None,
    vlm_summary: str | None = None,
) -> None:
    """更新成片的 AI 文案生成缓存（asr_text / vlm_summary / ai_context_at）。

    仅更新非 None 字段。供「一键发布」文案生成模块缓存 ASR/VLM 结果用，
    避免重复抽音频/抽帧/调模型。
    """
    sets: list[str] = []
    params: list = []
    if asr_text is not None:
        sets.append("asr_text = ?")
        params.append(asr_text)
    if vlm_summary is not None:
        sets.append("vlm_summary = ?")
        params.append(vlm_summary)
    if not sets:
        return
    sets.append("ai_context_at = ?")
    params.append(_now_iso())
    params.append(render_id)
    db = await get_db_conn()
    try:
        await db.execute(
            f"UPDATE renders SET {', '.join(sets)} WHERE id = ?", params
        )
        await db.commit()
    finally:
        await db.close()
