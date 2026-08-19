"""工作流 API：定义管理（Agent 工具面）+ 一键运行/历史/取消/重跑。

路由分两组：
- 定义管理：GET/POST /definitions、validate、actions 目录、duplicate、DELETE
  —— 后期对话式 Agent 只需把这几个端点注册为工具即可创建/修改工作流
- 运行：POST /{workflow_id}/runs（一键运行）、runs 历史/详情/取消（级联）/重跑
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.core.license import ensure_license_valid, is_license_enforced
from app.core.workflow.actions import catalog as actions_catalog, ensure_actions_loaded
from app.core.workflow.engine import run_workflow_job
from app.core.workflow.schema import (
    WorkflowDef,
    resolve_run_inputs,
    validate_workflow_def,
)
from app.core.workflow.store import (
    create_run,
    delete_definition,
    get_definition,
    get_run,
    list_definitions,
    list_runs,
    save_definition,
    update_run,
)
from app.jobs import create_job, launch_job
from app.jobs.routes import _do_cancel_job
from app.jobs.store import get_job
from app.models.workflow import (
    WorkflowDefinitionRequest,
    WorkflowRunRequest,
    WorkflowValidateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workflow", tags=["workflow"])


async def _ensure_license() -> None:
    if is_license_enforced() and not await ensure_license_valid():
        raise HTTPException(status_code=403, detail="LICENSE_REQUIRED")


def _validate_payload_or_422(data: dict) -> WorkflowDef:
    errors, defn = validate_workflow_def(data)
    if errors or defn is None:
        raise HTTPException(status_code=422, detail={"message": "工作流定义不合法", "errors": errors})
    return defn


# ── 动作目录（LLM / 前端组合工作流的工具说明书）────────────────────────────

@router.get("/actions")
async def list_actions():
    """全部可调度动作的自描述目录（input/output schema + 示例）。"""
    return {"items": actions_catalog(), "total": len(actions_catalog())}


# ── 定义管理 ──────────────────────────────────────────────────────────────

@router.get("/definitions")
async def list_workflow_definitions():
    """工作流定义列表（内置 + 自定义，含 params schema 与步骤链）。"""
    return {"items": await list_definitions()}


@router.post("/definitions/validate")
async def validate_workflow_definition(req: WorkflowValidateRequest):
    """dry-run 校验定义（Agent 自检 / 编辑器即时反馈）。"""
    errors, _defn = validate_workflow_def(req.definition)
    return {"valid": not errors, "errors": errors}


@router.post("/definitions")
async def save_workflow_definition(req: WorkflowDefinitionRequest):
    """新建/更新自定义工作流（内置定义不可改，可复制为自定义后编辑）。"""
    await _ensure_license()
    ensure_actions_loaded()
    data = dict(req.definition)
    data.pop("is_builtin", None)   # 不允许通过 API 声明内置
    defn = _validate_payload_or_422(data)

    existing = await get_definition(defn.id)
    if existing and existing.get("is_builtin"):
        raise HTTPException(
            status_code=409,
            detail=f"内置工作流 {defn.id} 不可修改，可先调用 duplicate 复制为自定义",
        )
    payload = await save_definition(defn, is_builtin=False)
    return {"saved": True, "definition": payload}


@router.post("/definitions/{workflow_id}/duplicate")
async def duplicate_workflow_definition(workflow_id: str):
    """复制定义（内置 → 自定义副本；自定义也可复制）。"""
    await _ensure_license()
    src = await get_definition(workflow_id)
    if not src:
        raise HTTPException(status_code=404, detail=f"工作流 '{workflow_id}' 不存在")
    definition = dict(src.get("definition") or {})
    definition.pop("is_builtin", None)

    # 生成不冲突的新 id / 名称
    base = src["id"]
    if base.endswith("_builtin"):
        base = base[: -len("_builtin")]
    suffix = 2
    while await get_definition(f"{base}_copy{suffix if suffix > 2 else ''}"):
        suffix += 1
    new_id = f"{base}_copy{suffix}" if suffix > 2 else f"{base}_copy"
    definition["id"] = new_id
    definition["name"] = f"{src['name']}（自定义副本）"
    defn = _validate_payload_or_422(definition)
    payload = await save_definition(defn, is_builtin=False)
    return {"saved": True, "definition": payload}


@router.delete("/definitions/{workflow_id}")
async def delete_workflow_definition(workflow_id: str):
    """删除自定义工作流（内置不可删）。"""
    await _ensure_license()
    existing = await get_definition(workflow_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"工作流 '{workflow_id}' 不存在")
    if existing.get("is_builtin"):
        raise HTTPException(status_code=409, detail="内置工作流不可删除")
    deleted = await delete_definition(workflow_id)
    return {"deleted": deleted, "id": workflow_id}


# ── 运行 ──────────────────────────────────────────────────────────────────

async def _start_run(workflow_id: str, inputs_raw: dict) -> dict:
    ensure_actions_loaded()
    definition = await get_definition(workflow_id)
    if not definition:
        raise HTTPException(status_code=404, detail=f"工作流 '{workflow_id}' 不存在")
    defn = WorkflowDef.from_json(definition.get("definition") or {})

    errors, inputs = resolve_run_inputs(defn, inputs_raw)
    if errors:
        raise HTTPException(
            status_code=422, detail={"message": "运行输入不合法", "errors": errors}
        )

    run = await create_run(workflow_id, defn.to_json(), inputs)
    job = await create_job(
        kind="workflow",
        ref_type="workflow_run",
        ref_id=run["id"],
        ref_name=defn.name,
        initial_step=defn.steps[0].name if defn.steps else "prepare",
    )
    await update_run(run["id"], job_id=job["id"])
    launch_job(job["id"], run_workflow_job(job["id"], run["id"]))
    return {
        "run_id": run["id"],
        "job_id": job["id"],
        "status": "running",
        "stream_url": f"/api/jobs/{job['id']}/stream",
        "ws_url": f"/api/jobs/{job['id']}/ws",
    }


@router.post("/{workflow_id}/runs")
async def start_workflow_run(workflow_id: str, req: WorkflowRunRequest):
    """一键运行：校验输入 → 建运行记录 + 后台 job → 返回 SSE 地址。"""
    await _ensure_license()
    return await _start_run(workflow_id, req.inputs)


@router.get("/runs")
async def list_workflow_runs(limit: int = 50, workflow_id: str | None = None):
    """运行历史（新→旧，含步骤状态摘要与成片地址）。"""
    items = await list_runs(limit=limit, workflow_id=workflow_id)
    return {"items": items, "total": len(items)}


@router.get("/runs/{run_id}")
async def get_workflow_run(run_id: str):
    """运行详情（完整步骤上下文 + 定义快照）。"""
    run = await get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"运行记录 '{run_id}' 不存在")
    if run["job_id"]:
        row = await get_job(run["job_id"])
        if row:
            run["job_status"] = row["status"]
            run["job_error"] = row["error_message"]
    return run


@router.post("/runs/{run_id}/cancel")
async def cancel_workflow_run(run_id: str):
    """取消运行：级联取消工作流 job 与仍在执行的子任务。"""
    run = await get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"运行记录 '{run_id}' 不存在")

    cancelled: list[str] = []
    job_id = run.get("job_id")
    if job_id:
        row = await get_job(job_id)
        if row and str(row["status"]) in ("pending", "running"):
            await _do_cancel_job(row)   # 引擎协程捕获取消后会自行级联子任务
            cancelled.append(job_id)
    # 兜底：引擎协程已死（如重启孤儿）时，直接按上下文快照取消活跃子任务
    context = run.get("context") or {}
    for child_id in context.get("child_job_ids") or []:
        try:
            child = await get_job(str(child_id))
            if child and str(child["status"]) in ("pending", "running"):
                await _do_cancel_job(child)
                cancelled.append(str(child_id))
        except Exception:
            logger.exception("兜底取消子任务失败 job_id=%s", child_id)
    await update_run(run_id, status="cancelled")
    return {"ok": True, "cancelled": cancelled}


@router.post("/runs/{run_id}/retry")
async def retry_workflow_run(run_id: str):
    """同参数重跑：以当前定义 + 原输入新建一次运行。"""
    await _ensure_license()
    run = await get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"运行记录 '{run_id}' 不存在")
    result = await _start_run(run["workflow_id"], run.get("inputs") or {})
    return {**result, "retried_from": run_id}
