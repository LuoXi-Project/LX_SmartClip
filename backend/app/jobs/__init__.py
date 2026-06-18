"""
通用后台任务进度系统 —— 独立模块，镜像已验证的 process_job 机制（process_db / process_shared / process）。

用法（Phase 4 各接口）:
  1. await create_job(kind='reencode', ...)            # → {id, stream_url}
  2. reporter = JobReporter(job_id)
  3. launch_job(job_id, _run_work(job_id, reporter, ...))  # 后台执行
  4. 工作协程中：await reporter.send(step, 'running', '...', {detail})
  5. 完成时：reporter.send(step, 'done', '...') + await update_job_status('done', result=...)
"""

from .store import (
    create_job,
    delete_job,
    get_job,
    list_jobs,
    reconcile_process_jobs_on_startup,
    row_to_payload,
    update_job_progress,
    update_job_status,
    CREATE_ASYNC_JOBS,
)
from .runtime import JobReporter, launch_job, check_cancel, JobCancelled
from .routes import router as jobs_router
from .sse import sse_event
