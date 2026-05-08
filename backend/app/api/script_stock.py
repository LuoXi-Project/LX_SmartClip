"""文案驱动的素材匹配：Pexels 搜索/下载（隔离目录）与素材库视频拼接成片。"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import Any, List, Optional, Tuple

import aiosqlite
import httpx
from fastapi import APIRouter, HTTPException

from app.api.tts import TTS_AUDIO_DIR, synthesize
from app.core.blocking_pool import run_heavy
from app.core.llm import LLMClient, LLMConfig
from app.core.script_stock.compose import compose_stock_video_sync, is_under_pexels_download_dir
from app.core.script_stock.jianying_export import build_script_stock_jianying_zip_sync
from app.db.database import DB_PATH
from app.models.tts import SynthesizeRequest
from app.models.subtitle import JianYingDraftExportResponse, SubtitleStyle
from app.models.script_stock import (
    PexelsVideoFile,
    PexelsVideoSummary,
    ScriptStockComposeRequest,
    ScriptStockComposeResponse,
    ScriptStockGenerateScriptRequest,
    ScriptStockGenerateScriptResponse,
    ScriptStockPexelsCacheItem,
    ScriptStockPexelsCacheResponse,
    ScriptStockPexelsClearCacheResponse,
    ScriptStockPexelsDeleteRequest,
    ScriptStockPexelsDeleteResponse,
    ScriptStockPexelsDownloadRequest,
    ScriptStockPexelsDownloadResponse,
    ScriptStockPexelsSearchResponse,
    ScriptStockSplitRequest,
    ScriptStockSplitResponse,
    ScriptStockSuggestQueriesRequest,
    ScriptStockSuggestQueriesResponse,
)
from app.utils.ffprobe_utils import probe_duration
from app.utils.paths import ensure_storage_subpath, resolve_stored_path, storage_public_url_for_file, to_stored_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/script-stock", tags=["script-stock"])

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/videos/search"
_PEXELS_FN_ID = re.compile(r"^pexels_(\d+)_", re.IGNORECASE)
_PEXELS_META_FILENAME = "pexels_cache_meta.json"


def _pexels_meta_path(root: str) -> str:
    return os.path.join(root, _PEXELS_META_FILENAME)


def _read_pexels_meta(root: str) -> dict[str, Any]:
    mp = _pexels_meta_path(root)
    if not os.path.isfile(mp):
        return {}
    try:
        with open(mp, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _write_pexels_meta(root: str, data: dict[str, Any]) -> None:
    mp = _pexels_meta_path(root)
    tmp = mp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, mp)


async def _cfg(db: aiosqlite.Connection, key: str, default: str = "") -> str:
    async with db.execute("SELECT value FROM config WHERE key = ?", (key,)) as cur:
        row = await cur.fetchone()
    if row and row[0] is not None:
        return str(row[0])
    return default


async def _load_export_render_opts(db: aiosqlite.Connection) -> dict:
    keys = [
        "export_vcodec",
        "export_acodec",
        "export_preset",
        "export_crf",
        "export_video_bitrate_kbps",
        "export_audio_bitrate_kbps",
        "export_g",
        "export_keyint_min",
        "export_sc_threshold",
        "export_fps",
        "export_scale_width",
        "export_scale_height",
        "export_pix_fmt",
        "export_container",
        "export_gpu",
    ]
    opts: dict[str, str] = {}
    for key in keys:
        opts[key] = await _cfg(db, key, "")
    return opts


def _split_script_text(script: str, mode: str) -> List[str]:
    raw = (script or "").strip()
    if not raw:
        return []
    if mode == "line":
        parts = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    else:
        parts = [p.strip() for p in re.split(r"\n\s*\n+", raw) if p.strip()]
    return parts[:40]


def _parse_json_array(text: str) -> Any:
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start = t.find("[")
        end = t.rfind("]")
        if start >= 0 and end > start:
            return json.loads(t[start : end + 1])
        raise


@router.post("/split", response_model=ScriptStockSplitResponse)
async def split_script(req: ScriptStockSplitRequest) -> ScriptStockSplitResponse:
    segs = _split_script_text(req.script, req.mode)
    if not segs:
        raise HTTPException(400, "文案为空或无法分段")
    return ScriptStockSplitResponse(segments=segs)


@router.post("/generate-script", response_model=ScriptStockGenerateScriptResponse)
async def generate_script(req: ScriptStockGenerateScriptRequest) -> ScriptStockGenerateScriptResponse:
    topic = (req.topic or "").strip()
    if not topic:
        raise HTTPException(400, "请填写主题或关键词")
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cfg = await LLMConfig.get_llm_params_with_defaults(db)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))

    style = (req.style_hint or "").strip()
    n = int(req.num_paragraphs)
    sys_msg = (
        "你是短视频旁白撰稿人。根据用户给的主题写出中文口播/旁白文案。"
        "要求：分段清晰，每段 1~3 句，段落之间语义连贯；不要编号列表符号；不要 Markdown。"
        f"输出恰好 {n} 个段落，段落之间用一个空行分隔。"
    )
    user_msg = f"主题：{topic}\n"
    if style:
        user_msg += f"风格补充：{style}\n"

    try:
        llm = LLMClient(
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            model=cfg["model"],
            temperature=min(0.9, float(cfg.get("temperature") or 0.7)),
            max_tokens=min(8192, int(cfg.get("max_tokens") or 4096)),
            timeout=120.0,
        )
        content = await llm.chat(
            [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
            temperature=0.75,
            max_tokens=min(8192, int(cfg.get("max_tokens") or 4096)),
        )
    except Exception as e:
        logger.error("generate-script LLM error: %s", e)
        raise HTTPException(502, detail=f"LLM 生成失败: {e}")

    script = (content or "").strip()
    if not script:
        raise HTTPException(502, detail="LLM 返回为空")
    return ScriptStockGenerateScriptResponse(script=script)


@router.post("/suggest-queries", response_model=ScriptStockSuggestQueriesResponse)
async def suggest_queries(req: ScriptStockSuggestQueriesRequest) -> ScriptStockSuggestQueriesResponse:
    if not req.segments:
        raise HTTPException(400, "segments 不能为空")
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cfg = await LLMConfig.get_llm_params_with_defaults(db)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))

    lines = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(req.segments))
    sys_msg = (
        "你是素材检索助手。给定多条中文短视频文案，请为每一条提取一个英文关键词短语，"
        "用于在免费素材站搜索短视频（风景、人物、城市、科技等）。"
        "输出必须是 JSON 数组，长度与输入条数相同，例如："
        '[\"ocean sunset\",\"coffee shop\"] ，不要其它解释文字。'
    )
    user_msg = f"文案段落：\n{lines}"

    try:
        llm = LLMClient(
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            model=cfg["model"],
            temperature=0.3,
            max_tokens=min(4096, int(cfg.get("max_tokens") or 2048)),
            timeout=90.0,
        )
        content = await llm.chat(
            [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
            temperature=0.2,
            max_tokens=min(4096, int(cfg.get("max_tokens") or 2048)),
        )
        arr = _parse_json_array(content)
        if not isinstance(arr, list):
            raise ValueError("not a list")
        queries = [str(x).strip() for x in arr][: len(req.segments)]
        while len(queries) < len(req.segments):
            queries.append(queries[-1] if queries else "nature")
    except Exception as e:
        logger.warning("suggest-queries fallback: %s", e)
        queries = []
        for t in req.segments:
            toks = re.findall(r"[A-Za-z]{3,}", t)
            queries.append(" ".join(toks[:4]) if toks else "lifestyle")

    return ScriptStockSuggestQueriesResponse(queries=queries[: len(req.segments)])


def _map_pexels_video(v: dict) -> PexelsVideoSummary:
    files_raw = v.get("video_files") or []
    files: List[PexelsVideoFile] = []
    for f in files_raw:
        if not isinstance(f, dict):
            continue
        link = (f.get("link") or "").strip()
        if not link:
            continue
        files.append(
            PexelsVideoFile(
                quality=str(f.get("quality") or ""),
                width=int(f.get("width") or 0),
                height=int(f.get("height") or 0),
                link=link,
            )
        )
    user = v.get("user") if isinstance(v.get("user"), dict) else {}
    return PexelsVideoSummary(
        id=int(v.get("id") or 0),
        width=int(v.get("width") or 0),
        height=int(v.get("height") or 0),
        duration=int(v.get("duration") or 0),
        image=str(v.get("image") or ""),
        user_name=str((user or {}).get("name") or ""),
        video_files=files,
    )


@router.get("/pexels/search", response_model=ScriptStockPexelsSearchResponse)
async def pexels_search(query: str, page: int = 1, per_page: int = 12) -> ScriptStockPexelsSearchResponse:
    q = (query or "").strip()
    if not q:
        raise HTTPException(400, "query 不能为空")
    per_page = max(1, min(24, int(per_page)))
    page = max(1, int(page))

    async with aiosqlite.connect(DB_PATH) as db:
        api_key = (await _cfg(db, "pexels_api_key")).strip()
    if not api_key:
        raise HTTPException(
            400,
            "未配置 Pexels API Key，请在「设置 → 视频处理」中填写 pexels_api_key（详见 www.pexels.com/api）",
        )

    headers = {"Authorization": api_key}
    params = {"query": q, "page": page, "per_page": per_page}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(PEXELS_SEARCH_URL, headers=headers, params=params)
    except httpx.RequestError as e:
        raise HTTPException(502, detail=f"Pexels 请求失败: {e}")

    if resp.status_code != 200:
        raise HTTPException(resp.status_code, detail=resp.text[:500])

    data = resp.json()
    videos = [_map_pexels_video(v) for v in (data.get("videos") or []) if isinstance(v, dict)]
    return ScriptStockPexelsSearchResponse(
        page=int(data.get("page") or page),
        per_page=int(data.get("per_page") or per_page),
        total_results=int(data.get("total_results") or 0),
        videos=videos,
    )


def _pick_pexels_file(files: List[PexelsVideoFile], preferred: str) -> PexelsVideoFile | None:
    if not files:
        return None
    pref = (preferred or "hd").lower()
    for q in (pref, "hd", "medium", "sd"):
        for f in files:
            if f.quality.lower() == q and f.link.lower().endswith(".mp4"):
                return f
    for f in files:
        if f.link.lower().endswith(".mp4"):
            return f
    return files[0]


@router.post("/pexels/download", response_model=ScriptStockPexelsDownloadResponse)
async def pexels_download(req: ScriptStockPexelsDownloadRequest) -> ScriptStockPexelsDownloadResponse:
    vid = int(req.pexels_video_id)
    if vid <= 0:
        raise HTTPException(400, "pexels_video_id 无效")

    async with aiosqlite.connect(DB_PATH) as db:
        api_key = (await _cfg(db, "pexels_api_key")).strip()
    if not api_key:
        raise HTTPException(400, "未配置 Pexels API Key")

    headers = {"Authorization": api_key}
    url = f"https://api.pexels.com/v1/videos/videos/{vid}"
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.get(url, headers=headers)
    except httpx.RequestError as e:
        raise HTTPException(502, detail=f"Pexels 请求失败: {e}")

    if resp.status_code != 200:
        raise HTTPException(resp.status_code, detail=resp.text[:500])

    data = resp.json()
    summary = _map_pexels_video(data if isinstance(data, dict) else {})
    picked = _pick_pexels_file(summary.video_files, req.preferred_quality)
    if not picked:
        raise HTTPException(404, "未找到可下载的视频文件")

    dest_dir = ensure_storage_subpath("stock_media", "pexels")
    fname = f"pexels_{vid}_{picked.quality}_{picked.width}x{picked.height}.mp4"
    dest_abs = os.path.join(dest_dir, fname)

    try:
        async with httpx.AsyncClient(timeout=600.0, follow_redirects=True) as client:
            media = await client.get(picked.link)
        if media.status_code != 200:
            raise HTTPException(502, detail="下载视频失败")
        with open(dest_abs, "wb") as f:
            f.write(media.content)
    except httpx.RequestError as e:
        raise HTTPException(502, detail=f"下载失败: {e}")

    rel = to_stored_path(dest_abs)
    try:
        meta = _read_pexels_meta(dest_dir)
        sq = (req.search_query or "").strip()[:500]
        meta[rel] = {
            "search_query": sq,
            "pexels_image": (summary.image or "").strip()[:2000],
            "duration_sec": int(summary.duration or 0),
        }
        _write_pexels_meta(dest_dir, meta)
    except Exception as e:
        logger.warning("pexels meta write skipped: %s", e)

    return ScriptStockPexelsDownloadResponse(
        stored_rel_path=rel,
        public_url=storage_public_url_for_file(dest_abs),
        filename=os.path.basename(dest_abs),
    )


@router.get("/pexels/cache", response_model=ScriptStockPexelsCacheResponse)
async def pexels_cache_list() -> ScriptStockPexelsCacheResponse:
    """列出本地下载目录中的 Pexels 视频（用于前端展示已缓存、避免重复下载）。"""
    root = ensure_storage_subpath("stock_media", "pexels")
    items: List[ScriptStockPexelsCacheItem] = []
    if not os.path.isdir(root):
        return ScriptStockPexelsCacheResponse(items=[])
    meta = _read_pexels_meta(root)
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return ScriptStockPexelsCacheResponse(items=[])
    for name in names:
        if name == _PEXELS_META_FILENAME or name.endswith(".tmp"):
            continue
        low = name.lower()
        if not low.endswith((".mp4", ".mov", ".webm", ".mkv")):
            continue
        full = os.path.join(root, name)
        if not os.path.isfile(full):
            continue
        try:
            st = os.stat(full)
            sz = int(st.st_size)
            mt = float(st.st_mtime)
        except OSError:
            sz, mt = 0, 0.0
        m = _PEXELS_FN_ID.match(name)
        vid = int(m.group(1)) if m else 0
        rel = to_stored_path(full)
        row = meta.get(rel) if isinstance(meta.get(rel), dict) else {}
        if not isinstance(row, dict):
            row = {}
        sq = str(row.get("search_query") or "")[:500]
        img = str(row.get("pexels_image") or "")[:2000]
        try:
            dsec = int(row.get("duration_sec") or row.get("duration") or 0)
        except (TypeError, ValueError):
            dsec = 0
        items.append(
            ScriptStockPexelsCacheItem(
                pexels_video_id=vid,
                stored_rel_path=rel,
                filename=name,
                size_bytes=sz,
                mtime=mt,
                search_query=sq,
                pexels_image=img,
                duration_sec=dsec,
            )
        )
    items.sort(key=lambda x: -x.mtime)
    return ScriptStockPexelsCacheResponse(items=items)


@router.post("/pexels/delete-file", response_model=ScriptStockPexelsDeleteResponse)
async def pexels_delete_file(req: ScriptStockPexelsDeleteRequest) -> ScriptStockPexelsDeleteResponse:
    rel = (req.stored_rel_path or "").strip().replace("\\", "/")
    if not rel:
        raise HTTPException(400, "stored_rel_path 不能为空")
    abs_path = resolve_stored_path(rel)
    if not abs_path or not os.path.isfile(abs_path):
        raise HTTPException(404, "文件不存在或已删除")
    if not is_under_pexels_download_dir(abs_path):
        raise HTTPException(403, "非法路径：仅允许删除 stock_media/pexels 下的文件")
    try:
        os.unlink(abs_path)
    except OSError as e:
        logger.warning("pexels delete failed: %s", e)
        raise HTTPException(500, detail=str(e)) from e
    try:
        root = ensure_storage_subpath("stock_media", "pexels")
        meta = _read_pexels_meta(root)
        if rel in meta:
            del meta[rel]
            _write_pexels_meta(root, meta)
    except Exception as e:
        logger.warning("pexels meta delete skipped: %s", e)
    return ScriptStockPexelsDeleteResponse(ok=True)


@router.post("/pexels/clear-cache", response_model=ScriptStockPexelsClearCacheResponse)
async def pexels_clear_cache() -> ScriptStockPexelsClearCacheResponse:
    """删除 stock_media/pexels 下全部已下载视频及缓存元数据（前端需二次确认）。"""
    root = ensure_storage_subpath("stock_media", "pexels")
    deleted = 0
    if not os.path.isdir(root):
        return ScriptStockPexelsClearCacheResponse(ok=True, deleted_files=0)
    try:
        names = list(os.listdir(root))
    except OSError:
        return ScriptStockPexelsClearCacheResponse(ok=True, deleted_files=0)
    for name in names:
        if name == _PEXELS_META_FILENAME or name.endswith(".tmp"):
            continue
        low = name.lower()
        if not low.endswith((".mp4", ".mov", ".webm", ".mkv")):
            continue
        full = os.path.join(root, name)
        if not os.path.isfile(full):
            continue
        if not is_under_pexels_download_dir(full):
            continue
        try:
            os.unlink(full)
            deleted += 1
        except OSError as e:
            logger.warning("pexels clear unlink %s: %s", full, e)
    mp = _pexels_meta_path(root)
    try:
        if os.path.isfile(mp):
            os.unlink(mp)
    except OSError as e:
        logger.warning("pexels clear meta: %s", e)
    return ScriptStockPexelsClearCacheResponse(ok=True, deleted_files=deleted)


def _default_pair_for_path(abs_path: str) -> Tuple[float, float]:
    d = float(probe_duration(abs_path) or 0.0)
    if d <= 0.02:
        d = 60.0
    return (0.0, d)


async def _resolve_compose_rows(
    db: aiosqlite.Connection, req: ScriptStockComposeRequest
) -> List[Tuple[List[str], str, List[Tuple[float, float]]]]:
    """返回 ([素材绝对路径…], kind, [(in_sec,out_sec),…])；与 manual 出入点类似，library 可传 library_trims。"""
    out: List[Tuple[List[str], str, List[Tuple[float, float]]]] = []
    for seg in req.segments:
        if seg.kind == "library":
            raw_ids: List[str] = []
            if seg.library_video_ids:
                raw_ids = [str(x).strip() for x in seg.library_video_ids if str(x).strip()]
            if not raw_ids:
                vid = (seg.video_id or "").strip()
                if vid:
                    raw_ids = [vid]
            if not raw_ids:
                raise HTTPException(400, "library 分段缺少 video_id 或 library_video_ids")
            if len(raw_ids) > 12:
                raise HTTPException(400, "单段最多拼接 12 条本地素材")
            paths: List[str] = []
            for vid in raw_ids:
                async with db.execute(
                    "SELECT file_path FROM videos WHERE id = ?",
                    (vid,),
                ) as cur:
                    row = await cur.fetchone()
                if not row or not row[0]:
                    raise HTTPException(400, f"素材库视频不存在: {vid}")
                abs_path = resolve_stored_path(str(row[0]))
                if not abs_path or not os.path.isfile(abs_path):
                    raise HTTPException(400, f"视频文件缺失: {vid}")
                paths.append(abs_path)
            lt = seg.library_trims
            if lt is not None and len(lt) != len(paths):
                raise HTTPException(400, "library_trims 与 library_video_ids 数量须一致")
            trim_pairs: List[Tuple[float, float]] = []
            for j, p in enumerate(paths):
                if lt and j < len(lt):
                    a, b = float(lt[j].in_sec), float(lt[j].out_sec)
                    if b <= a + 0.02:
                        raise HTTPException(400, f"选用区间无效：out_sec 须大于 in_sec（第 {j + 1} 条）")
                    trim_pairs.append((a, b))
                else:
                    trim_pairs.append(_default_pair_for_path(p))
            out.append((paths, "library", trim_pairs))
        elif seg.kind == "pexels":
            rels: List[str] = []
            if seg.pexels_stored_rel_paths:
                rels = [str(x).strip().replace("\\", "/") for x in seg.pexels_stored_rel_paths if str(x).strip()]
            if not rels:
                one = (seg.stored_rel_path or "").strip().replace("\\", "/")
                if one:
                    rels = [one]
            if not rels:
                raise HTTPException(400, "pexels 分段缺少 stored_rel_path 或 pexels_stored_rel_paths")
            if len(rels) > 12:
                raise HTTPException(400, "单段最多拼接 12 条 Pexels 文件")
            paths: List[str] = []
            for rel in rels:
                abs_path = resolve_stored_path(rel)
                if not abs_path or not os.path.isfile(abs_path):
                    raise HTTPException(400, f"Pexels 本地文件不存在: {rel}")
                if not is_under_pexels_download_dir(abs_path):
                    raise HTTPException(403, "非法素材路径：仅允许使用 stock_media/pexels 下的下载文件")
                paths.append(abs_path)
            trim_pairs_px: List[Tuple[float, float]] = [_default_pair_for_path(p) for p in paths]
            out.append((paths, "pexels", trim_pairs_px))
        else:
            raise HTTPException(400, "未知分段类型")
    return out


@router.post("/compose", response_model=ScriptStockComposeResponse)
async def compose_stock(req: ScriptStockComposeRequest) -> ScriptStockComposeResponse:
    if not req.segments:
        raise HTTPException(400, "segments 不能为空")

    if req.audio_mode != "tts_only":
        for seg in req.segments:
            if seg.kind == "library":
                n = len([x for x in (seg.library_video_ids or []) if str(x).strip()])
                if n > 1:
                    raise HTTPException(
                        400,
                        "多段本地素材按顺序拼接仅支持「仅 TTS」模式；使用原声或混合时请每段只选一条素材。",
                    )
            elif seg.kind == "pexels":
                rels = [str(x).strip() for x in (seg.pexels_stored_rel_paths or []) if str(x).strip()]
                n = len(rels) if rels else (1 if (seg.stored_rel_path or "").strip() else 0)
                if n > 1:
                    raise HTTPException(
                        400,
                        "多段 Pexels 素材按顺序拼接仅支持「仅 TTS」模式；使用原声或混合时请每段只选一条文件。",
                    )

    tts_paths: List[Optional[str]] = []
    if req.audio_mode in ("tts_only", "mix"):
        for seg in req.segments:
            txt = (seg.text or "").strip()
            if not txt:
                tts_paths.append(None)
                continue
            try:
                res = await synthesize(
                    SynthesizeRequest(
                        text=txt,
                        voice=req.tts_voice,
                        rate=req.tts_rate,
                        volume=req.tts_volume,
                    )
                )
                tts_paths.append(os.path.join(TTS_AUDIO_DIR, res.filename))
            except HTTPException:
                raise
            except Exception as e:
                logger.exception("script-stock TTS failed")
                raise HTTPException(500, detail=f"TTS 合成失败: {e}") from e
    else:
        tts_paths = [None] * len(req.segments)

    async with aiosqlite.connect(DB_PATH) as db:
        rows = await _resolve_compose_rows(db, req)
        export_opts = await _load_export_render_opts(db)

    base_name = (req.project_name or "stock_clip").replace(" ", "_")[:80]
    unique = f"{base_name}_{uuid.uuid4().hex[:10]}"

    def _sync() -> str:
        texts = [(s.text or "") for s in req.segments]
        return compose_stock_video_sync(
            segment_rows=rows,
            tts_paths=tts_paths,
            audio_mode=req.audio_mode,
            tts_volume_db=float(req.tts_volume_db),
            original_volume_db=float(req.original_volume_db),
            timeline_mode=req.timeline_mode,
            video_extend_policy=req.video_extend_policy,
            material_tts_fill=req.material_tts_fill,
            material_tts_longer=req.material_tts_longer,
            include_subtitle=bool(req.include_subtitle),
            subtitle_style=req.subtitle_style,
            segment_texts=texts,
            export_render_opts=export_opts,
            project_name=unique,
        )

    try:
        final_abs = await run_heavy(_sync)
    except Exception as e:
        logger.exception("compose_stock failed")
        raise HTTPException(500, detail=f"成片失败: {e}") from e

    rel = to_stored_path(final_abs)
    return ScriptStockComposeResponse(
        filename=os.path.basename(final_abs),
        public_url=storage_public_url_for_file(final_abs),
        stored_rel_path=rel,
    )


@router.post("/export-jianying-draft", response_model=JianYingDraftExportResponse)
async def export_jianying_draft_stock(req: ScriptStockComposeRequest) -> JianYingDraftExportResponse:
    """
    仅导出剪映草稿 ZIP（不渲染成片 MP4）。
    请求体与 ``/compose`` 一致；``tts_only`` / ``mix`` 时各段须填写文案以便生成 TTS（与成片侧「静音段」策略不同）。
    ``mix`` 草稿仅保留 TTS 主解说轨，成片中的「混合原声」需在剪映内自行叠加。
    """
    if not req.segments:
        raise HTTPException(400, "segments 不能为空")

    if req.audio_mode in ("tts_only", "mix"):
        for idx, seg in enumerate(req.segments):
            if not (seg.text or "").strip():
                raise HTTPException(
                    400,
                    f"导出剪映草稿（配音轨）时，第 {idx + 1} 段须填写配音文案（与「成片可含静音段」不同）。",
                )

    if req.audio_mode != "tts_only":
        for seg in req.segments:
            if seg.kind == "library":
                n = len([x for x in (seg.library_video_ids or []) if str(x).strip()])
                if n > 1:
                    raise HTTPException(
                        400,
                        "多段本地素材按顺序拼接仅支持「仅 TTS」模式；导出剪映草稿时请改为单条或切换为仅 TTS。",
                    )
            elif seg.kind == "pexels":
                rels = [str(x).strip() for x in (seg.pexels_stored_rel_paths or []) if str(x).strip()]
                n = len(rels) if rels else (1 if (seg.stored_rel_path or "").strip() else 0)
                if n > 1:
                    raise HTTPException(
                        400,
                        "多段 Pexels 素材按顺序拼接仅支持「仅 TTS」模式；导出剪映草稿时请改为单条或切换为仅 TTS。",
                    )

    tts_paths: List[Optional[str]] = []
    if req.audio_mode in ("tts_only", "mix"):
        for seg in req.segments:
            txt = (seg.text or "").strip()
            if not txt:
                tts_paths.append(None)
                continue
            try:
                res = await synthesize(
                    SynthesizeRequest(
                        text=txt,
                        voice=req.tts_voice,
                        rate=req.tts_rate,
                        volume=req.tts_volume,
                    )
                )
                tts_paths.append(os.path.join(TTS_AUDIO_DIR, res.filename))
            except HTTPException:
                raise
            except Exception as e:
                logger.exception("script-stock jianying TTS failed")
                raise HTTPException(500, detail=f"TTS 合成失败: {e}") from e
    else:
        tts_paths = [None] * len(req.segments)

    async with aiosqlite.connect(DB_PATH) as db:
        rows = await _resolve_compose_rows(db, req)

    base_name = (req.project_name or "stock_clip").replace(" ", "_")[:80]
    unique = f"{base_name}_jy_{uuid.uuid4().hex[:10]}"
    jy_dir = ensure_storage_subpath("jianying_drafts")
    jy_zip = os.path.join(jy_dir, f"{unique}_jianying.zip")

    try:
        await run_heavy(
            build_script_stock_jianying_zip_sync,
            segment_rows=rows,
            tts_paths=tts_paths,
            segment_texts=[(s.text or "") for s in req.segments],
            audio_mode=req.audio_mode,
            timeline_mode=req.timeline_mode,
            include_subtitle=bool(req.include_subtitle),
            subtitle_style=req.subtitle_style or SubtitleStyle(),
            project_name=unique,
            tts_audio_dir=TTS_AUDIO_DIR,
            output_zip_path=jy_zip,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("export_jianying_draft_stock failed")
        raise HTTPException(500, detail=f"剪映草稿导出失败: {e}") from e

    return JianYingDraftExportResponse(
        filename=os.path.basename(jy_zip),
        url=storage_public_url_for_file(jy_zip),
    )
