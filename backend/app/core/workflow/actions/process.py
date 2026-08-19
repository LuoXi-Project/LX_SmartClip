"""动作：素材预处理等待（切分 → 抽帧/ASR → VLM → 富化 → 向量化）。

对传入的 video_ids：已处理完成的跳过，其余进入现有串行预处理队列并逐个等待；
全部完成后返回可参与剪辑的 video_ids。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.jobs import JobCancelled, check_cancel

from . import WorkflowActionError, action
from .match_render import normalize_video_ids

if TYPE_CHECKING:
    from ..context import WorkflowContext


@action(
    "wait_process",
    title="素材预处理",
    description=(
        "把 video_ids 对应素材送入预处理队列（切分/ASR/VLM/向量化）并等待全部完成。"
        "已处理完成的素材自动跳过。输出可直接作为剪辑动作的 video_ids。"
        "allow_partial=true 时允许个别素材失败（剔除后继续，只要还有成功素材）。"
    ),
    input_schema={
        "video_ids": {"type": "string[]", "required": True, "description": "素材视频 ID 列表（可引用采集步骤输出）"},
        "skip_steps": {"type": "string[]", "required": False, "description": "跳过的预处理步骤（split/extract_frames/asr/vlm/enrich/embed）"},
        "allow_partial": {"type": "boolean", "required": False, "description": "允许部分素材失败：剔除失败项继续（默认 false，任一失败则步骤失败）"},
    },
    output_schema={
        "video_ids": "预处理成功的素材 ID 列表",
        "processed_count": "本次实际处理数量",
        "skipped_count": "本来就已完成、直接跳过的数量",
        "failed_count": "失败被剔除的数量（allow_partial 时）",
    },
    example={"video_ids": "${steps.ingest.video_ids}", "allow_partial": True},
)
async def run_wait_process(ctx: "WorkflowContext", params: dict) -> dict:
    from app.api.process import enqueue_process_job
    from app.api.process_db import get_video

    video_ids = normalize_video_ids(params.get("video_ids"))
    if not video_ids:
        raise WorkflowActionError("wait_process 需要 video_ids（非空）")
    skip_steps = [str(s) for s in (params.get("skip_steps") or [])]
    allow_partial = bool(params.get("allow_partial"))

    # 已完成（status=done 且有 clips）的跳过；其余入预处理队列
    to_wait: list[tuple[str, str, str]] = []   # (job_id, video_id, video_name)
    skipped = 0
    for vid in video_ids:
        await check_cancel(ctx.job_id)
        video = await get_video(vid)
        if not video:
            raise WorkflowActionError(f"素材不存在或已删除: {vid}")
        if str(video.get("status")) == "done" and int(video.get("total_clips") or 0) > 0:
            skipped += 1
            continue
        summary = await enqueue_process_job(
            vid, video_name=str(video.get("name") or ""), skip_steps=skip_steps
        )
        job_id = str(summary.get("job_id") or "")
        # 登记为子任务：工作流取消时级联取消（含仍在排队的）
        if job_id:
            ctx.child_job_ids.append(job_id)
        to_wait.append((job_id, vid, str(video.get("name") or vid)))

    total = len(to_wait)
    failed: list[str] = []
    for idx, (job_id, vid, name) in enumerate(to_wait, start=1):
        await check_cancel(ctx.job_id)
        if not job_id:
            raise WorkflowActionError(f"素材 {name} 预处理入队失败（未返回 job_id）")
        await ctx.reporter.send(
            ctx.current_step, "running",
            f"素材预处理 {idx}/{total}：{name[:40]}",
            {"current": idx, "total": total},
        )
        try:
            await ctx.wait_job(job_id, title=f"预处理({idx}/{total})")
        except JobCancelled:
            raise
        except WorkflowActionError as exc:
            msg = f"素材「{name[:40]}」预处理失败：{str(exc)[:200]}"
            if allow_partial:
                failed.append(vid)
                await ctx.reporter.send(
                    ctx.current_step, "running",
                    f"{msg}（允许部分失败，剔除后继续）", {"failed": vid},
                )
                continue
            raise WorkflowActionError(msg) from exc

    # 终态复核：以 videos.status 为准（job done 但 status 未落 done 的也算失败）
    done_ids: list[str] = []
    unfinished: list[str] = []
    for vid in video_ids:
        if vid in failed:
            continue
        video = await get_video(vid)
        if video and str(video.get("status")) == "done":
            done_ids.append(vid)
        else:
            unfinished.append(vid)
    if unfinished:
        if allow_partial and len(done_ids) > 0:
            failed.extend(unfinished)
            await ctx.reporter.send(
                ctx.current_step, "running",
                f"{len(unfinished)} 个素材未完成，已剔除（剩余 {len(done_ids)} 个可用）", {},
            )
        else:
            raise WorkflowActionError(
                f"{len(unfinished)} 个素材预处理未完成，无法继续后续步骤"
            )
    if not done_ids:
        raise WorkflowActionError("预处理后没有可用素材（全部失败）")
    return {
        "video_ids": done_ids,
        "processed_count": len(to_wait),
        "skipped_count": skipped,
        "failed_count": len(failed),
    }
