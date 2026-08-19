"""动作：外部素材采集（关键词 → 平台搜索 → 下载入库）。

包装 core.external_search.ingest.run_ingest_job 为子 job 并等待完成；
默认不自动进预处理队列（auto_process=False），与 wait_process 动作正交组合。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import WorkflowActionError, action

if TYPE_CHECKING:
    from ..context import WorkflowContext


@action(
    "external_ingest",
    title="外部素材采集",
    description=(
        "根据文案或关键词在抖音 / YouTube 搜索并下载素材入库。"
        "文案会经 LLM 提取搜索关键词（不可用时降级文本切分）。"
        "默认下载后不自动预处理，配合 wait_process 动作使用。"
    ),
    input_schema={
        "copy_text": {"type": "string", "required": False, "description": "整段文案，LLM 提取采集关键词"},
        "keywords": {"type": "string[]", "required": False, "description": "显式关键词列表（优先于 copy_text）"},
        "platforms": {"type": "string[]", "required": False, "description": "平台列表：douyin / youtube", "enum": ["douyin", "youtube"]},
        "limit_per_keyword": {"type": "number", "required": False, "description": "每个关键词采集条数，默认 3"},
        "resolution": {"type": "string", "required": False, "description": "下载清晰度：best/1080p/720p/480p，默认 720p"},
        "auto_process": {"type": "boolean", "required": False, "description": "下载后立即进预处理队列（默认 false，交给 wait_process）"},
    },
    output_schema={
        "video_ids": "入库的素材视频 ID 列表",
        "video_count": "成功入库数量",
        "failed_count": "下载失败数量",
        "keywords": "实际使用的搜索关键词",
    },
    example={
        "copy_text": "${inputs.copy_text}",
        "platforms": "${inputs.platforms}",
        "limit_per_keyword": 3,
    },
)
async def run_external_ingest(ctx: "WorkflowContext", params: dict) -> dict:
    from app.core.external_search.ingest import IngestParams, run_ingest_job

    copy_text = str(params.get("copy_text") or "").strip()
    raw_keywords = params.get("keywords")
    if isinstance(raw_keywords, str):
        # LLM 生成的定义可能给逗号分隔字符串，统一归一为列表
        raw_keywords = [k for k in (x.strip() for x in raw_keywords.replace("，", ",").split(",")) if k]
    keywords = [str(k).strip() for k in (raw_keywords or []) if str(k).strip()]
    if not copy_text and not keywords and not params.get("selected_items"):
        raise WorkflowActionError("external_ingest 需要 copy_text 或 keywords 至少一项")

    platforms = [str(p) for p in (params.get("platforms") or ["douyin"]) if str(p)]
    ingest = IngestParams(
        copy_text=copy_text,
        keywords=keywords,
        platforms=platforms,
        limit_per_keyword=max(1, int(params.get("limit_per_keyword") or 3)),
        resolution=str(params.get("resolution") or "720p"),
        auto_process=bool(params.get("auto_process") or False),
        selected_items=list(params.get("selected_items") or []),
    )

    job_id = await ctx.spawn_job(
        "external_ingest",
        lambda jid: run_ingest_job(jid, ingest),
        ref_name=f"工作流采集：{ctx.workflow.name}",
    )
    result = await ctx.wait_job(job_id, title="素材采集")

    downloaded = result.get("downloaded") or []
    failed = result.get("failed") or []
    new_ids = [str(d.get("video_id")) for d in downloaded if d.get("video_id")]
    # 搜索命中但已入库的素材：直接复用（重跑幂等，不重复下载）
    reused_ids = [str(v) for v in (result.get("existing_video_ids") or []) if v]
    video_ids = new_ids + [v for v in reused_ids if v not in new_ids]
    if not video_ids:
        reason = ""
        if failed:
            reason = f"；失败 {len(failed)} 个（首个原因：{str(failed[0].get('error'))[:80]}）"
        raise WorkflowActionError(f"采集未获得任何可用素材{reason}")

    return {
        "video_ids": video_ids,
        "video_count": len(new_ids),
        "reused_count": len(video_ids) - len(new_ids),
        "failed_count": len(failed),
        "keywords": result.get("keywords") or [],
        "job_id": job_id,
    }
