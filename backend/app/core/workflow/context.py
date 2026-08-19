"""工作流执行上下文：参数模板解析 + 子 job 接力（spawn/wait）+ 级联取消。

模板语法：${inputs.xxx} / ${steps.<步骤名>.<输出字段>}（支持嵌套字段与数组下标）。
子 job 走 app/jobs 通用体系（async_jobs + launch_job），TaskHub 天然可见；
等待时把子任务进度折叠上报到当前工作流步骤（仿 agent.plan_runner 轮询折算）。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Callable, Awaitable

from app.jobs import JobCancelled, JobReporter, check_cancel
from app.jobs.store import get_job, row_to_payload

from .actions import WorkflowActionError
from .schema import REF_RE, WorkflowDef, normalize_json_literals, safe_eval_when

logger = logging.getLogger(__name__)

# 子任务轮询间隔 / 单个子任务最长等待（与 process_pipeline 总超时 6h 对齐）
CHILD_POLL_INTERVAL_SEC = 2.0
CHILD_MAX_WAIT_SEC = 6 * 3600

_INDEX_RE = re.compile(r"^-?\d+$")


class WorkflowContext:
    """一次工作流运行期内共享的上下文（引擎创建，动作消费）。"""

    def __init__(
        self,
        *,
        job_id: str,
        run_id: str,
        workflow: WorkflowDef,
        inputs: dict,
        reporter: JobReporter,
    ):
        self.job_id = job_id
        self.run_id = run_id
        self.workflow = workflow
        self.inputs = inputs
        self.reporter = reporter
        # 引擎在执行每步前设置，动作上报进度时使用
        self.current_step: str = ""
        # 步骤名 -> {"status": running|done|skip|error, "output": dict|None, "error": str|None}
        self.steps: dict[str, dict] = {}
        # 本次运行派生出的全部子 job（级联取消用）
        self.child_job_ids: list[str] = []

    # ── 模板解析 ──────────────────────────────────────────────────────────

    def resolve(self, value: Any) -> Any:
        """递归解析 params 中的 ${...} 模板（整串引用保留原始类型）。"""
        if isinstance(value, str):
            return self._resolve_str(value)
        if isinstance(value, list):
            return [self.resolve(v) for v in value]
        if isinstance(value, dict):
            return {k: self.resolve(v) for k, v in value.items()}
        return value

    def _resolve_str(self, s: str) -> Any:
        stripped = s.strip()
        full = REF_RE.fullmatch(stripped)
        if full:
            return self._lookup(full.group(1))
        return REF_RE.sub(lambda m: str(self._lookup(m.group(1))), s)

    def _lookup(self, path: str) -> Any:
        parts = path.split(".")
        root = parts[0]
        if root == "inputs":
            cur: Any = self.inputs
        elif root == "steps":
            cur = {name: (info.get("output") or {}) for name, info in self.steps.items()}
        else:
            raise WorkflowActionError(
                f"模板 ${{{path}}} 根必须是 inputs 或 steps"
            )
        for seg in parts[1:]:
            cur = self._index(cur, seg, path)
        return cur

    @staticmethod
    def _index(cur: Any, key: str, path: str) -> Any:
        if isinstance(cur, dict):
            if key not in cur:
                raise WorkflowActionError(
                    f"模板 ${{{path}}} 无法解析：缺少字段 {key!r}"
                    f"（可用字段: {sorted(map(str, cur.keys()))[:12]}）"
                )
            return cur[key]
        if isinstance(cur, list) and _INDEX_RE.match(key):
            idx = int(key)
            if -len(cur) <= idx < len(cur):
                return cur[idx]
            raise WorkflowActionError(f"模板 ${{{path}}} 数组下标越界: {key}")
        raise WorkflowActionError(
            f"模板 ${{{path}}} 无法在 {type(cur).__name__} 上取字段 {key!r}"
        )

    def eval_when(self, when: str) -> bool:
        """求值步骤跳过条件：模板替换为 repr 字面量后走安全求值器。"""
        substituted = REF_RE.sub(lambda m: repr(self._lookup(m.group(1))), when)
        substituted = normalize_json_literals(substituted)
        return safe_eval_when(substituted)

    def step_output(self, name: str) -> dict:
        return (self.steps.get(name) or {}).get("output") or {}

    # ── 子 job 接力 ───────────────────────────────────────────────────────

    async def spawn_job(
        self,
        kind: str,
        run_fn: Callable[[str], Awaitable[None]],
        *,
        ref_name: str | None = None,
        ref_id: str | None = None,
        initial_step: str | None = None,
    ) -> str:
        """创建子 async_job 并后台启动（登记到 child_job_ids 供级联取消）。"""
        from app.jobs import create_job, launch_job

        job = await create_job(
            kind=kind,
            ref_type="workflow",
            ref_id=ref_id,
            ref_name=ref_name,
            initial_step=initial_step,
        )
        job_id = job["id"]
        self.child_job_ids.append(job_id)
        launch_job(job_id, run_fn(job_id))
        return job_id

    async def wait_job(
        self,
        job_id: str,
        *,
        title: str = "",
        step: str | None = None,
        max_wait_sec: float = CHILD_MAX_WAIT_SEC,
        poll_sec: float = CHILD_POLL_INTERVAL_SEC,
    ) -> dict:
        """轮询子 job 至终态：done 返回 result_json；失败/取消上抛；进度折叠到当前步骤。"""
        step = step or self.current_step or "progress"
        start = time.monotonic()
        last_key: str | None = None
        prefix = f"{title}：" if title else ""
        while True:
            await check_cancel(self.job_id)
            row = await get_job(job_id)
            if not row:
                raise WorkflowActionError(f"子任务不存在或已清理: {job_id}")
            payload = row_to_payload(row)
            status = str(payload.get("status") or "")
            if status == "done":
                return payload.get("result") or {}
            if status == "cancelled":
                raise JobCancelled()
            if status == "error":
                raise WorkflowActionError(
                    f"{prefix}子任务失败：{payload.get('error_message') or '未知错误'}"
                )
            if time.monotonic() - start > max_wait_sec:
                raise WorkflowActionError(f"{prefix}子任务等待超时（{int(max_wait_sec)}s）")
            # pending/running：进度折叠（消息变化时上报，避免刷库/刷流）
            message = self._child_progress_message(payload)
            key = f"{payload.get('current_step')}|{message}"
            if message and key != last_key:
                await self.reporter.send(
                    step, "running", prefix + message,
                    {"child_job_id": job_id, "child_kind": payload.get("kind")},
                )
                last_key = key
            await asyncio.sleep(poll_sec)

    @staticmethod
    def _child_progress_message(payload: dict) -> str:
        steps = payload.get("steps") or {}
        if isinstance(steps, dict) and steps:
            cur = str(payload.get("current_step") or "")
            if cur in steps and isinstance(steps[cur], dict):
                msg = str(steps[cur].get("message") or "").strip()
                if msg:
                    return msg[:120]
        return str(payload.get("status") or "")

    # ── 级联取消 ──────────────────────────────────────────────────────────

    async def cancel_children(self) -> None:
        """取消所有仍在执行的子 job（幂等；process 类走视频级取消路径）。"""
        from app.jobs.routes import _do_cancel_job

        for job_id in list(self.child_job_ids):
            try:
                row = await get_job(job_id)
                if row is None:
                    continue
                if str(row["status"]) in ("pending", "running"):
                    await _do_cancel_job(row)
            except Exception:
                logger.exception("级联取消子任务失败 job_id=%s", job_id)

    def snapshot(self) -> dict:
        """持久化用上下文快照（步骤状态 + 输出 + 子任务清单）。"""
        return {
            "steps": self.steps,
            "child_job_ids": list(self.child_job_ids),
        }
