import logging
import os
import sqlite3
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.match import MatchRequest, _match_clips_sync, MatchPipelineError  # type: ignore
from app.db.database import DB_PATH

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api", tags=["search"])


class SemanticSearchFilters(BaseModel):
    video_ids: Optional[List[str]] = Field(
        default=None, description="限定在指定视频（素材）集合内检索"
    )


class SemanticSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="用户自然语言描述")
    top_k: Optional[int] = Field(
        default=None, ge=1, le=100, description="向量初筛候选数量（默认沿用 match_top_k）"
    )
    top_n: Optional[int] = Field(
        default=None, ge=1, le=50, description="返回候选片段数量上限（默认沿用 match_top_n）"
    )
    highlight_only: bool = Field(
        default=False, description="仅返回推测为高光的片段"
    )
    filters: Optional[SemanticSearchFilters] = None


class SemanticSearchSegment(BaseModel):
    clip_id: str
    start_time: float
    end_time: float
    duration: float
    score: float
    summary_text: Optional[str] = None
    is_highlight: bool
    highlight_score: float
    thumbnail_url: Optional[str] = None
    preview_url: Optional[str] = None


class SemanticSearchAssetResult(BaseModel):
    asset_id: str
    asset_title: str
    duration: Optional[float] = None
    cover_url: Optional[str] = None
    asset_score: float
    segments: List[SemanticSearchSegment]


class SemanticSearchResponse(BaseModel):
    query: str
    results: List[SemanticSearchAssetResult]


class HighlightBrowseFilters(BaseModel):
    video_ids: Optional[List[str]] = Field(default=None, description="限定视频（素材）ID 列表；为空表示全部")


class HighlightBrowseRequest(BaseModel):
    """
    高光浏览（无需语义检索/向量/LLM）。
    直接读取 clips.vlm_description 并推断高光得分，然后按视频聚合返回。
    """

    limit_assets: int = Field(default=20, ge=1, le=200, description="最多返回多少个素材")
    limit_segments_per_asset: int = Field(default=10, ge=1, le=200, description="每个素材最多返回多少段高光")
    min_score: float = Field(default=0.3, ge=0.0, le=1.0, description="高光最低得分阈值")
    filters: Optional[HighlightBrowseFilters] = None


class HighlightBrowseSegment(BaseModel):
    clip_id: str
    start_time: float
    end_time: float
    duration: float
    highlight_score: float
    summary_text: Optional[str] = None


class HighlightBrowseAssetResult(BaseModel):
    asset_id: str
    asset_title: str
    duration: Optional[float] = None
    cover_url: Optional[str] = None
    asset_score: float
    segments: List[HighlightBrowseSegment]


class HighlightBrowseResponse(BaseModel):
    results: List[HighlightBrowseAssetResult]


def _infer_highlight_score(text: Optional[str]) -> float:
    """
    从 VLM 描述中粗略推断高光得分。

    说明：
        - 当前不改动数据库 schema，仅在读取时解析文案。
        - 若后续增加结构化高光字段，可替换为直接读取字段。
    """
    if not text:
        return 0.0

    t = text.strip()
    if not t:
        return 0.0

    # 优先解析“高光评级：xxx”模式
    # 约定模板中常见的三档：高光 / 一般 / 非高光
    try:
        import re

        m = re.search(r"高光评级[:：]\s*(高光|一般|非高光)", t)
        if m:
            lvl = m.group(1)
            if "高光" == lvl:
                return 1.0
            if "一般" in lvl:
                return 0.6
            if "非高光" in lvl:
                return 0.2
    except Exception:
        pass

    # 兜底：只要文案中多次提到“高光”、“精彩”、“亮点”等关键词，适当给高分
    keywords = ("高光", "精彩", "亮点", "高潮", "最有价值", "推荐保留")
    hit = sum(1 for k in keywords if k in t)
    if hit >= 2:
        return 0.8
    if hit == 1:
        return 0.6

    return 0.0


def _browse_highlights_sync(
    req: HighlightBrowseRequest,
) -> HighlightBrowseResponse:
    """
    同步执行：读取 clips + videos 表，推断高光分数并按视频聚合。
    放在线程池中避免阻塞事件循环。
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"数据库连接失败: {e}") from e

    try:
        video_ids = (req.filters.video_ids if req.filters and req.filters.video_ids else None)

        # 拉视频元信息
        video_meta: Dict[str, Dict] = {}
        if video_ids:
            placeholders_v = ",".join("?" * len(video_ids))
            v_rows = conn.execute(
                f"SELECT id, name, duration, thumbnail_path FROM videos WHERE id IN ({placeholders_v})",
                video_ids,
            ).fetchall()
        else:
            v_rows = conn.execute(
                "SELECT id, name, duration, thumbnail_path FROM videos WHERE status = 'done' ORDER BY upload_at DESC"
            ).fetchall()

        for r in v_rows:
            video_meta[r["id"]] = {
                "name": r["name"],
                "duration": r["duration"],
                "thumbnail_path": r["thumbnail_path"],
            }

        # 拉 clip（只读）
        if video_ids:
            placeholders = ",".join("?" * len(video_ids))
            c_rows = conn.execute(
                f"SELECT id, video_id, start_time, end_time, duration, vlm_description "
                f"FROM clips WHERE video_id IN ({placeholders}) ORDER BY video_id, start_time",
                video_ids,
            ).fetchall()
        else:
            c_rows = conn.execute(
                "SELECT id, video_id, start_time, end_time, duration, vlm_description "
                "FROM clips ORDER BY video_id, start_time"
            ).fetchall()

        by_video: Dict[str, List[HighlightBrowseSegment]] = {}
        for row in c_rows:
            vid = row["video_id"]
            if vid not in video_meta:
                # 跳过未完成/不存在的视频
                continue
            hs = _infer_highlight_score(row["vlm_description"])
            if hs < float(req.min_score):
                continue
            seg = HighlightBrowseSegment(
                clip_id=row["id"],
                start_time=float(row["start_time"] or 0.0),
                end_time=float(row["end_time"] or 0.0),
                duration=float(row["duration"] or 0.0),
                highlight_score=float(hs),
                summary_text=row["vlm_description"],
            )
            by_video.setdefault(vid, []).append(seg)

        assets: List[HighlightBrowseAssetResult] = []
        for vid, segs in by_video.items():
            if not segs:
                continue
            segs_sorted = sorted(segs, key=lambda s: s.highlight_score, reverse=True)[
                : int(req.limit_segments_per_asset)
            ]
            best = segs_sorted[0]
            vm = video_meta.get(vid, {})
            assets.append(
                HighlightBrowseAssetResult(
                    asset_id=vid,
                    asset_title=str(vm.get("name") or vid),
                    duration=vm.get("duration"),
                    cover_url=vm.get("thumbnail_path"),
                    asset_score=float(best.highlight_score),
                    segments=segs_sorted,
                )
            )

        assets.sort(key=lambda a: a.asset_score, reverse=True)
        assets = assets[: int(req.limit_assets)]
        return HighlightBrowseResponse(results=assets)
    finally:
        conn.close()


def _group_by_asset(
    match_result: Dict, highlight_only: bool
) -> List[SemanticSearchAssetResult]:
    """
    将 MatchResponse 风格的结果，聚合为按素材（视频）分组的结果。
    """
    from app.models.match import ClipResult  # 为了复用字段定义

    # 只使用 candidates，避免 recommended 被截断后丢信息
    raw_candidates: List[Dict] = match_result.get("candidates") or []
    if not raw_candidates:
        return []

    # 预取所有关联视频元信息
    video_ids = sorted({c.get("video_id") for c in raw_candidates if c.get("video_id")})
    video_meta: Dict[str, Dict] = {}

    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        if video_ids:
            placeholders = ",".join("?" * len(video_ids))
            rows = conn.execute(
                f"SELECT id, name, duration, thumbnail_path FROM videos WHERE id IN ({placeholders})",
                video_ids,
            ).fetchall()
            for r in rows:
                video_meta[r["id"]] = {
                    "name": r["name"],
                    "duration": r["duration"],
                    "thumbnail_path": r["thumbnail_path"],
                }
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # 聚合
    by_asset: Dict[str, List[SemanticSearchSegment]] = {}
    for c in raw_candidates:
        clip = ClipResult(**c)
        h_score = _infer_highlight_score(clip.vlm_description)
        is_highlight = h_score >= 0.6
        if highlight_only and not is_highlight:
            continue

        seg = SemanticSearchSegment(
            clip_id=clip.clip_id,
            start_time=clip.start_time,
            end_time=clip.end_time,
            duration=clip.duration,
            score=clip.score,
            summary_text=clip.vlm_description or clip.asr_text,
            is_highlight=is_highlight,
            highlight_score=h_score,
            thumbnail_url=clip.thumbnail_url,
            preview_url=clip.preview_url,
        )
        by_asset.setdefault(clip.video_id, []).append(seg)

    results: List[SemanticSearchAssetResult] = []
    for asset_id, segs in by_asset.items():
        if not segs:
            continue
        # 按 score 排序，截取前 N（此处不知 top_k_segments_per_asset，交给调用侧裁剪）
        segs_sorted = sorted(segs, key=lambda s: s.score, reverse=True)
        best = segs_sorted[0]
        vm = video_meta.get(asset_id, {})
        results.append(
            SemanticSearchAssetResult(
                asset_id=asset_id,
                asset_title=str(vm.get("name") or asset_id),
                duration=vm.get("duration"),
                cover_url=vm.get("thumbnail_path"),
                asset_score=best.score,
                segments=segs_sorted,
            )
        )

    # 按素材得分排序
    results.sort(key=lambda r: r.asset_score, reverse=True)
    return results


@router.post("/search/assets/semantic", response_model=SemanticSearchResponse)
async def semantic_search_assets(payload: SemanticSearchRequest, request: Request):
    """
    语义检索素材与时间片段。

    实现说明：
    - 复用现有 /api/match 的三级匹配引擎（Embedding + FAISS + LLM 精排）。
    - 在此基础上对结果做「按视频聚合」，并通过 VLM 描述粗略推断高光片段。
    """
    # FastAPI 的 Request.base_url 类似于 http://host:port/，与 /api/match 保持一致传入
    api_base_url = str(request.base_url).rstrip("/")

    # 将 filters.video_ids 透传给 match 引擎
    match_req = MatchRequest(
        query=payload.query,
        top_k=payload.top_k,
        top_n=payload.top_n,
        video_ids=(payload.filters.video_ids if payload.filters and payload.filters.video_ids else None),
    )

    # 由于 _match_clips_sync 是同步阻塞函数，这里沿用 /api/match 的封装方式：
    # 在线程池中执行，避免阻塞事件循环。简单起见直接重用 run_heavy 封装逻辑。
    timeout_raw = (os.environ.get("SMARTCLIP_MATCH_TIMEOUT_SEC") or "").strip()
    timeout_sec = float(timeout_raw) if timeout_raw else 0.0

    from app.core.blocking_pool import run_heavy

    async def _run():
        return await run_heavy(_match_clips_sync, match_req, api_base_url)

    try:
        import asyncio

        if timeout_sec > 0:
            match_res = await asyncio.wait_for(_run(), timeout=timeout_sec)
        else:
            match_res = await _run()
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="素材检索处理超时，请稍后重试或缩小检索范围",
        ) from None
    except MatchPipelineError as e:
        # 将 match pipeline 的错误语义透传给前端
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    grouped = _group_by_asset(match_res.dict(), highlight_only=payload.highlight_only)
    return SemanticSearchResponse(query=payload.query, results=grouped)


@router.post("/search/highlights", response_model=HighlightBrowseResponse)
async def browse_highlights(payload: HighlightBrowseRequest):
    """
    高光浏览（无需检索/无需向量/无需 LLM）。
    直接基于已分析的 VLM 文本推断高光并返回。
    """
    from app.core.blocking_pool import run_heavy

    return await run_heavy(_browse_highlights_sync, payload)
