"""关键词采集编排：文案/关键词 → 平台搜索 → 下载入库 → 自动进预处理队列。

作为 async_job（kind=external_ingest）后台协程运行，全程 JobReporter 汇报；
单个目标下载失败不阻断整体，结束时汇总 result_json。
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import aiosqlite

from app.core.blocking_pool import run_in_blocking_executor
from app.db.database import get_db_conn
from app.jobs import JobReporter, check_cancel, update_job_status
from app.utils.paths import ensure_storage_subpath, to_stored_path
from app.utils.video_link_downloader import VideoLinkDownloadError, download_video_from_link

from .douyin import search_douyin
from .types import (
    IngestFailure,
    PLATFORM_DOUYIN,
    PLATFORM_LABELS,
    PLATFORM_YOUTUBE,
    ExternalSearchResult,
)
from .youtube import search_youtube

logger = logging.getLogger(__name__)

# 自动模式全局上限（关键词 × 平台 × 每词条数 可能膨胀，兜底保护）
_MAX_AUTO_TARGETS = 40

# LLM 关键词提取的默认条数区间
_KEYWORD_MIN, _KEYWORD_MAX = 3, 8


@dataclass
class IngestParams:
    """一次采集任务的输入（API 层由 Pydantic 模型转换而来）。"""

    keywords: list[str] = field(default_factory=list)   # 显式关键词（每行一个）
    copy_text: str = ""                                  # 整段文案 → LLM 提取关键词
    platforms: list[str] = field(default_factory=lambda: [PLATFORM_DOUYIN])
    limit_per_keyword: int = 3
    duration_min_sec: float | None = None
    duration_max_sec: float | None = None
    resolution: str = "720p"
    auto_process: bool = True
    # 预览勾选模式：直接给下载目标（跳过搜索）
    selected_items: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _IngestConfig:
    proxy: str = ""
    youtube_cookie_file: str = ""
    limit_per_keyword: int = 3
    min_duration_sec: float = 5.0
    max_duration_sec: float = 600.0
    resolution: str = "720p"


async def read_ingest_config() -> _IngestConfig:
    """读 config 表的采集相关默认值。"""
    cfg = _IngestConfig()
    try:
        db = await get_db_conn()
        try:
            async with db.execute(
                "SELECT key, value FROM config WHERE key IN "
                "('external_search_proxy','external_search_youtube_cookie_file',"
                "'external_search_limit_per_keyword',"
                "'external_search_min_duration_sec','external_search_max_duration_sec',"
                "'external_search_resolution')"
            ) as cur:
                rows = await cur.fetchall()
        finally:
            await db.close()
    except Exception:
        return cfg
    kv = {r["key"]: (r["value"] or "") for r in rows} if rows else {}
    try:
        cfg.proxy = str(kv.get("external_search_proxy") or "").strip()
        cfg.youtube_cookie_file = str(kv.get("external_search_youtube_cookie_file") or "").strip()
        cfg.limit_per_keyword = max(1, int(float(kv.get("external_search_limit_per_keyword") or 3)))
        cfg.min_duration_sec = float(kv.get("external_search_min_duration_sec") or 5)
        cfg.max_duration_sec = float(kv.get("external_search_max_duration_sec") or 600)
        res = str(kv.get("external_search_resolution") or "720p").strip()
        cfg.resolution = res if res in ("best", "1080p", "720p", "480p", "360p") else "720p"
    except (TypeError, ValueError):
        pass
    return cfg


# ── LLM 关键词提取 ──────────────────────────────────────────────────────

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def _parse_keywords_json(content: str | None) -> list[str]:
    if not content:
        return []
    text = content.strip()
    m = _JSON_ARRAY_RE.search(text)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(arr, list):
        return []
    out: list[str] = []
    for x in arr:
        s = str(x or "").strip().strip('"').strip()
        if 1 <= len(s) <= 40 and s not in out:
            out.append(s)
    return out


def _fallback_keywords(copy_text: str) -> list[str]:
    """LLM 不可用时的降级：按标点/换行切句，截取前几段做搜索词。"""
    parts = [p.strip() for p in re.split(r"[。！？\n；;.!?]", copy_text or "") if p.strip()]
    kws: list[str] = []
    for p in parts:
        kw = p[:16]
        if kw and kw not in kws:
            kws.append(kw)
        if len(kws) >= 5:
            break
    return kws or ([copy_text.strip()[:16]] if copy_text.strip() else [])


async def extract_keywords_from_copy(
    copy_text: str, max_keywords: int = 5
) -> tuple[list[str], str, str]:
    """LLM 从整段文案/标题提取搜索关键词。

    返回 (keywords, method, reason)：
    - method: "llm"（AI 提取）| "fallback"（降级文本切分）
    - reason: 降级原因（LLM 调用失败/未配置 Key 等），method=llm 时为空串
    """
    copy_text = (copy_text or "").strip()
    if not copy_text:
        return [], "fallback", "文案为空"
    max_keywords = max(_KEYWORD_MIN, min(int(max_keywords or 5), _KEYWORD_MAX))
    try:
        from app.core.llm import LLMClient, LLMConfig

        async with aiosqlite.connect(_db_path()) as db:
            cfg = await LLMConfig.get_llm_params_with_defaults(db)
        if not cfg.get("api_key"):
            return _fallback_keywords(copy_text), "fallback", "未配置 LLM API Key（llm_api_key）"
        llm = LLMClient(
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            model=cfg["model"],
            temperature=0.3,
            max_tokens=1024,
            timeout=60.0,
        )
        sys_msg = (
            "你是素材检索助手。给定一段中文短视频文案或标题，提取适合在短视频平台"
            "（抖音 / YouTube）搜索相关素材视频的关键词短语。要求："
            "覆盖文案的核心主题与关键画面元素；每个关键词 2~8 个字/词；"
            f"输出 {max_keywords} 个左右，必须是 JSON 字符串数组（如 [\"城市夜景\",\"航拍天际线\"]），"
            "不要输出任何解释文字。"
        )
        content = await llm.chat(
            [
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": f"文案/标题：\n{copy_text[:4000]}"},
            ],
            temperature=0.2,
            max_tokens=512,
        )
        kws = _parse_keywords_json(content)[:max_keywords]
        if kws:
            return kws, "llm", ""
        logger.warning("关键词提取返回不可解析：%r", (content or "")[:200])
        return _fallback_keywords(copy_text), "fallback", "LLM 返回内容不可解析"
    except Exception as exc:
        logger.warning("关键词提取 LLM 失败，降级文本切分：%s", exc)
        return _fallback_keywords(copy_text), "fallback", f"LLM 调用失败：{str(exc).strip()[:120]}"


def _db_path() -> str:
    from app.db.database import DB_PATH

    return DB_PATH


# ── 搜索聚合 ────────────────────────────────────────────────────────────

async def search_platforms(
    keywords: list[str],
    platforms: list[str],
    limit_per_keyword: int,
    cfg: _IngestConfig,
) -> tuple[list[ExternalSearchResult], list[str]]:
    """逐关键词 × 平台搜索，合并去重并按时长过滤。返回 (结果, 每步日志)。"""
    from .types import DouyinSearchError, YoutubeSearchError

    notes: list[str] = []
    merged: dict[tuple[str, str], ExternalSearchResult] = {}
    proxy = cfg.proxy or None
    cookiefile = cfg.youtube_cookie_file or None

    for kw in keywords:
        for platform in platforms:
            label = PLATFORM_LABELS.get(platform, platform)
            # 超额抓取：时长过滤/去重在限额之后执行，多抓一倍保证过滤后仍够数
            fetch_limit = max(limit_per_keyword * 2, limit_per_keyword + 4)
            try:
                if platform == PLATFORM_DOUYIN:
                    items = await search_douyin(kw, limit=fetch_limit)
                elif platform == PLATFORM_YOUTUBE:
                    if not proxy:
                        note = f"[{label}] 未配置代理（external_search_proxy），跳过 YouTube 搜索"
                        if note not in notes:
                            notes.append(note)
                        continue
                    items = await search_youtube(
                        kw, limit=fetch_limit, proxy=proxy, cookiefile=cookiefile
                    )
                else:
                    continue
            except (DouyinSearchError, YoutubeSearchError) as exc:
                notes.append(f"[{label}] 「{kw}」搜索失败：{exc}")
                continue
            raw_n = len(items)
            kept: list[ExternalSearchResult] = []
            filtered_out = 0
            for it in items:
                if it.dedupe_key() in merged:
                    continue
                if it.duration_sec is not None and (
                    it.duration_sec < cfg.min_duration_sec or it.duration_sec > cfg.max_duration_sec
                ):
                    filtered_out += 1
                    continue
                kept.append(it)
            for it in kept[:limit_per_keyword]:
                merged[it.dedupe_key()] = it
            added = min(len(kept), limit_per_keyword)
            note = f"[{label}] 「{kw}」命中 {raw_n} 条，采集 {added} 条"
            if filtered_out:
                note += (
                    f"（{filtered_out} 条时长超出 {int(cfg.min_duration_sec)}~{int(cfg.max_duration_sec)}s 被过滤）"
                )
            notes.append(note)

    # 排序：抖音优先（用户主阵地），其余按命中顺序
    ordered = sorted(merged.values(), key=lambda r: 0 if r.platform == PLATFORM_DOUYIN else 1)
    return ordered, notes


async def _filter_existing(
    results: list[ExternalSearchResult],
) -> tuple[list[ExternalSearchResult], list[str]]:
    """按 source_url 排除已入库素材（重复采集幂等）。

    返回 (待下载结果, 已入库的 video_id 列表)——已入库的素材对调用方仍有价值
    （工作流重跑时可继续复用，无需重复下载），因此一并带出。
    """
    if not results:
        return [], []
    urls = [r.url for r in results]
    existing_urls: set[str] = set()
    existing_ids: list[str] = []
    try:
        db = await get_db_conn()
        try:
            placeholders = ",".join("?" for _ in urls)
            async with db.execute(
                f"SELECT id, source_url FROM videos WHERE source_url IN ({placeholders})",
                urls,
            ) as cur:
                rows = await cur.fetchall()
            for r in rows:
                if r["source_url"]:
                    existing_urls.add(str(r["source_url"]))
                    existing_ids.append(str(r["id"]))
        finally:
            await db.close()
    except Exception:
        logger.exception("查询已入库来源失败（跳过去重）")
        return results, []
    return [r for r in results if r.url not in existing_urls], existing_ids


# ── 下载入库 ────────────────────────────────────────────────────────────

async def _download_and_register(
    item: ExternalSearchResult,
    resolution: str,
    *,
    proxy: str | None = None,
    cookiefile: str | None = None,
) -> dict:
    """下载单个素材并写入 videos 表（status=pending）。返回 {video_id, name}。"""
    from app.utils.video_thumbnail import generate_thumbnail

    video_id = str(uuid.uuid4())
    save_path, _ = await run_in_blocking_executor(
        download_video_from_link,
        url=item.url,
        output_dir=ensure_storage_subpath(video_id, "videos"),
        file_stem="source",
        resolution=resolution,
        proxy=proxy,
        cookiefile=cookiefile,
    )

    upload_at = datetime.utcnow().isoformat()
    thumbnail_path = await run_in_blocking_executor(generate_thumbnail, save_path, video_id)

    db = await get_db_conn()
    try:
        await db.execute(
            """
            INSERT INTO videos (id, name, file_path, thumbnail_path, duration, total_clips,
                                split_mode, status, upload_at, source_url, source_platform)
            VALUES (?, ?, ?, ?, NULL, 0, 'scene', 'pending', ?, ?, ?)
            """,
            (
                video_id,
                (item.title or "")[:200] or f"{PLATFORM_LABELS.get(item.platform, item.platform)}_{item.video_id[:12]}",
                to_stored_path(save_path),
                to_stored_path(thumbnail_path) if thumbnail_path else None,
                upload_at,
                item.url,
                item.platform,
            ),
        )
        await db.commit()
    finally:
        await db.close()
    return {"video_id": video_id, "name": item.title}


# ── 主编排协程 ──────────────────────────────────────────────────────────

async def run_ingest_job(job_id: str, params: IngestParams) -> None:
    """async_job 工作协程：keywords → search → download → process。"""
    reporter = JobReporter(job_id)
    cfg = await read_ingest_config()

    # 请求值优先，未给时回落 config 默认
    limit_per_keyword = params.limit_per_keyword or cfg.limit_per_keyword
    resolution = params.resolution or cfg.resolution

    failures: list[IngestFailure] = []
    downloaded: list[dict] = []
    process_jobs: list[dict] = []
    keywords: list[str] = []
    existing_video_ids: list[str] = []   # 搜索命中但已入库的素材（复用，不重复下载）

    try:
        # ── Step 1: 关键词 ─────────────────────────────────────────────
        await check_cancel(job_id)
        if params.selected_items:
            keywords = ["（预览勾选）"]
            targets: list[ExternalSearchResult] = []
            for it in params.selected_items:
                platform = str(it.get("platform") or "").strip()
                url = str(it.get("url") or "").strip()
                if not url:
                    continue
                targets.append(
                    ExternalSearchResult(
                        platform=platform,
                        video_id=str(it.get("video_id") or url),
                        title=str(it.get("title") or "")[:200],
                        url=url,
                    )
                )
            await reporter.send(
                "keywords", "done", f"预览勾选模式：共 {len(targets)} 个目标", {}
            )
            search_notes: list[str] = []
        else:
            await reporter.send("keywords", "running", "正在确定搜索关键词…", {})
            extract_method, extract_reason = "", ""
            if params.copy_text and not params.keywords:
                keywords, extract_method, extract_reason = await extract_keywords_from_copy(params.copy_text)
            else:
                keywords = [k.strip() for k in params.keywords if k.strip()]
            if not keywords:
                raise ValueError("未提供关键词，且文案提取关键词失败")
            if extract_method == "fallback" and extract_reason:
                await reporter.send(
                    "keywords",
                    "done",
                    f"AI 提取不可用（{extract_reason}），已降级文本切分。关键词：" + "、".join(keywords),
                    {"method": "fallback", "reason": extract_reason},
                )
            else:
                await reporter.send(
                    "keywords",
                    "done",
                    ("AI 提取" if extract_method == "llm" else "使用给定") + "关键词：" + "、".join(keywords),
                    {"method": extract_method or "manual"},
                )

            # ── Step 2: 搜索 ───────────────────────────────────────────
            await check_cancel(job_id)
            await reporter.send("search", "running", "正在搜索外部平台…", {})
            results, search_notes = await search_platforms(
                keywords, params.platforms, limit_per_keyword, cfg
            )
            results, existing_video_ids = await _filter_existing(results)
            if not results:
                if existing_video_ids:
                    # 命中的素材均已入库：直接复用，无需重复下载（工作流重跑幂等）
                    await reporter.send(
                        "search",
                        "done",
                        f"搜索命中 {len(existing_video_ids)} 条均已入库，直接复用（不重复下载）",
                        {"reused": len(existing_video_ids)},
                    )
                    result = {
                        "keywords": keywords,
                        "searched": 0,
                        "downloaded": [],
                        "failed": [],
                        "existing_video_ids": existing_video_ids,
                        "process_job_ids": [],
                        "notes": search_notes,
                    }
                    await reporter.send("done", "done", f"采集完成：复用已入库素材 {len(existing_video_ids)} 个", {})
                    await update_job_status(job_id, "done", result=result)
                    return
                msg = "搜索完成但无可用结果" + (
                    "（" + "；".join(search_notes[:3]) + "）" if search_notes else ""
                )
                await reporter.send("search", "done", msg, {"notes": search_notes})
                await reporter.send("done", "done", msg, {})
                await update_job_status(job_id, "done", result={"keywords": keywords, "video_ids": []})
                return
            targets = results[:_MAX_AUTO_TARGETS]
            await reporter.send(
                "search",
                "done",
                f"搜索完成：去重后 {len(results)} 条，本次采集 {len(targets)} 条"
                + (f"，另有 {len(existing_video_ids)} 条已入库可复用" if existing_video_ids else ""),
                {"notes": search_notes, "count": len(targets), "reused": len(existing_video_ids)},
            )

        # ── Step 3: 下载入库 ──────────────────────────────────────────
        total = len(targets)
        for idx, item in enumerate(targets, start=1):
            await check_cancel(job_id)
            await reporter.send(
                "download",
                "running",
                f"下载 {idx}/{total}：{item.title[:60]}",
                {"index": idx, "total": total, "percent": int((idx - 1) * 100 / total)},
            )
            try:
                info = await _download_and_register(
                    item,
                    resolution,
                    proxy=cfg.proxy or None,
                    cookiefile=cfg.youtube_cookie_file or None,
                )
                downloaded.append(info)
            except VideoLinkDownloadError as exc:
                failures.append(IngestFailure(title=item.title, url=item.url, platform=item.platform, error=str(exc)))
                logger.warning("采集下载失败 %s: %s", item.url, exc)
            except Exception as exc:
                failures.append(IngestFailure(title=item.title, url=item.url, platform=item.platform, error=str(exc)))
                logger.exception("采集下载异常 %s", item.url)
        await reporter.send(
            "download",
            "done",
            f"下载完成：成功 {len(downloaded)} / 失败 {len(failures)}",
            {"percent": 100, "success": len(downloaded), "failed": len(failures)},
        )

        # ── Step 4: 自动进预处理队列 ──────────────────────────────────
        if params.auto_process and downloaded:
            await check_cancel(job_id)
            from app.api.process import enqueue_process_job

            await reporter.send("process", "running", f"正在将 {len(downloaded)} 个素材加入预处理队列…", {})
            for info in downloaded:
                try:
                    summary = await enqueue_process_job(info["video_id"], video_name=info["name"])
                    process_jobs.append(
                        {"video_id": info["video_id"], "job_id": summary.get("job_id")}
                    )
                except Exception as exc:
                    logger.exception("预处理入队失败 video_id=%s", info["video_id"])
                    failures.append(
                        IngestFailure(
                            title=info["name"], url="", platform="",
                            error=f"预处理入队失败：{exc}",
                        )
                    )
            await reporter.send(
                "process", "done", f"已入预处理队列 {len(process_jobs)} 个", {}
            )

        result = {
            "keywords": keywords,
            "searched": len(targets),
            "downloaded": downloaded,
            "failed": [f.to_payload() for f in failures],
            "existing_video_ids": existing_video_ids,
            "process_job_ids": [p["job_id"] for p in process_jobs if p.get("job_id")],
            "notes": search_notes,
        }
        summary_msg = (
            f"采集完成：入库 {len(downloaded)} 个素材"
            + (f"，已进入预处理队列 {len(process_jobs)} 个" if process_jobs else "")
            + (f"，失败 {len(failures)} 个" if failures else "")
        )
        await reporter.send("done", "done", summary_msg, {"metrics": {"downloaded": len(downloaded)}})
        await update_job_status(job_id, "done", result=result)
    except Exception as exc:
        # 部分成功的成果也保留在 result 里，便于排查
        partial = {
            "keywords": keywords,
            "downloaded": downloaded,
            "failed": [f.to_payload() for f in failures],
        }
        await update_job_status(job_id, "error", error_message=str(exc), result=partial)
        raise
