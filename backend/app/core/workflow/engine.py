"""工作流执行引擎：按定义快照顺序执行步骤，全程 JobReporter 汇报。

生命周期：API 侧创建 workflow_runs + async_jobs(kind=workflow) 后 launch 本协程。
- 每步：check_cancel → when 判断 → 模板解析 → 动作执行（重试/超时）→ 上下文快照落库
- 取消/失败：级联取消全部子 job（采集/预处理/渲染），run 状态落库
"""

from __future__ import annotations

import asyncio
import logging

from app.jobs import JobCancelled, JobReporter, check_cancel, update_job_status

from .actions import WorkflowActionError, run_action
from .context import WorkflowContext
from .schema import WorkflowDef, WorkflowDefError

logger = logging.getLogger(__name__)


class _StepFailure(Exception):
    """步骤执行失败（引擎内部语义，str 为用户可读信息）。"""


async def run_workflow_job(job_id: str, run_id: str) -> None:
    """async_job 工作协程：执行 run_id 对应的工作流运行记录。"""
    from .store import get_run, update_run   # 延迟导入避免循环依赖

    run = await get_run(run_id)
    if not run:
        raise RuntimeError(f"工作流运行记录不存在: {run_id}")
    defn = WorkflowDef.from_json(run.get("def_snapshot") or {})
    inputs = run.get("inputs") or {}

    reporter = JobReporter(job_id)
    ctx = WorkflowContext(
        job_id=job_id, run_id=run_id, workflow=defn,
        inputs=inputs, reporter=reporter,
    )
    await update_run(run_id, status="running")

    async def persist() -> None:
        try:
            await update_run(run_id, context=ctx.snapshot())
        except Exception:
            logger.exception("持久化工作流上下文失败 run_id=%s", run_id)

    try:
        for step in defn.steps:
            await check_cancel(job_id)
            ctx.current_step = step.name

            # when 条件不满足 → 跳过
            if step.when:
                try:
                    condition_ok = ctx.eval_when(step.when)
                except (WorkflowDefError, WorkflowActionError) as exc:
                    raise _StepFailure(f"when 条件求值失败：{exc}") from exc
                if not condition_ok:
                    ctx.steps[step.name] = {"status": "skip", "output": None, "error": None}
                    await reporter.send(step.name, "skip", f"{step.title}：条件不满足，已跳过", {})
                    await persist()
                    continue

            try:
                params = ctx.resolve(step.params)
            except WorkflowActionError as exc:
                raise _StepFailure(str(exc)) from exc

            await reporter.send(step.name, "running", f"{step.title}：执行中…", {})
            try:
                output = await _execute_with_retry(ctx, step, params)
            except _StepFailure as exc:
                ctx.steps[step.name] = {"status": "error", "output": None, "error": str(exc)}
                if step.continue_on_error:
                    await reporter.send(
                        step.name, "error",
                        f"{step.title}：失败（继续后续步骤）— {exc}", {},
                    )
                    await persist()
                    continue
                await reporter.send(step.name, "error", f"{step.title}：失败 — {exc}", {})
                raise

            ctx.steps[step.name] = {"status": "done", "output": output, "error": None}
            await persist()
            await reporter.send(
                step.name, "done",
                f"{step.title}：{_output_summary(output)}",
                {"output": _slim(output)},
            )

        result = _build_result(ctx, defn)
        await update_run(run_id, status="done", context=ctx.snapshot())
        await update_job_status(job_id, "done", result=result)
        await reporter.send("done", "done", f"工作流「{defn.name}」执行完成", {"result": _slim(result)})
    except (asyncio.CancelledError, JobCancelled):
        await ctx.cancel_children()
        await update_run(run_id, status="cancelled", context=ctx.snapshot())
        raise
    except _StepFailure as exc:
        await ctx.cancel_children()
        await update_run(run_id, status="error", error=str(exc), context=ctx.snapshot())
        raise
    except Exception as exc:
        await ctx.cancel_children()
        await update_run(run_id, status="error", error=str(exc), context=ctx.snapshot())
        raise


async def _execute_with_retry(ctx: WorkflowContext, step, params: dict) -> dict:
    """执行单个动作：retries 次重试 + timeout_sec 超时；失败抛 _StepFailure。"""
    attempts = max(1, step.retries + 1)
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            if step.timeout_sec > 0:
                return await asyncio.wait_for(
                    run_action(ctx, step.action, params), timeout=step.timeout_sec
                )
            return await run_action(ctx, step.action, params)
        except (asyncio.CancelledError, JobCancelled):
            raise
        except asyncio.TimeoutError:
            last_error = f"步骤超时（>{step.timeout_sec}s）"
        except WorkflowActionError as exc:
            last_error = str(exc)
        except Exception as exc:
            logger.exception("工作流步骤异常 step=%s attempt=%s", step.name, attempt)
            last_error = str(exc) or exc.__class__.__name__
        if attempt < attempts:
            await ctx.reporter.send(
                step.name, "running",
                f"{step.title}：第 {attempt} 次失败（{last_error[:120]}），重试…",
                {"attempt": attempt, "retries": step.retries},
            )
    raise _StepFailure(last_error)


def _build_result(ctx: WorkflowContext, defn: WorkflowDef) -> dict:
    """汇总运行结果：步骤状态、子任务清单、成片地址（取最后一个带 url 的步骤输出）。"""
    render_url, render_filename = "", ""
    for info in ctx.steps.values():
        output = info.get("output") or {}
        if isinstance(output, dict) and output.get("url"):
            render_url = str(output["url"])
            render_filename = str(output.get("filename") or "")
    return {
        "workflow_id": defn.id,
        "workflow_name": defn.name,
        "steps": {name: info.get("status") for name, info in ctx.steps.items()},
        "child_job_ids": list(ctx.child_job_ids),
        "render_url": render_url,
        "render_filename": render_filename,
    }


def _slim(value, *, depth: int = 0):
    """SSE/detail 用的输出瘦身（避免大 plan 全量刷库/刷流）。"""
    if isinstance(value, dict):
        if depth >= 3:
            return "…"
        return {str(k)[:40]: _slim(v, depth=depth + 1) for k, v in list(value.items())[:16]}
    if isinstance(value, list):
        if not value:
            return "[]"
        head = ", ".join(str(x)[:24] for x in value[:3])
        suffix = "…" if len(value) > 3 else ""
        return f"[{head}{suffix}（共 {len(value)}）]"
    if isinstance(value, str):
        return value[:160]
    return value


def _output_summary(output) -> str:
    if not isinstance(output, dict) or not output:
        return "完成"
    bits: list[str] = []
    for key in ("video_count", "processed_count", "estimated_duration_sec", "filename", "url"):
        val = output.get(key)
        if val is not None and str(val).strip():
            bits.append(f"{key}={str(val)[:60]}")
    return "完成（" + "，".join(bits[:3]) + "）" if bits else "完成"
