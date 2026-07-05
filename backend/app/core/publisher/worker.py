"""发布任务 worker 子进程入口。

被 start_backend.py 的 --publisher-worker 分流调用：
    sys.executable --publisher-worker <task.json 绝对路径>

职责：
1. 读 task.json（PublishTaskPayload）
2. 校验视频文件与各账号 cookie
3. 串行执行各平台 publish()
4. 每步通过 _progress.emit_progress 向 stdout 输出进度
5. 全部完成写 result.json（含每平台结果）
6. 进程退出码：0=全部成功，1=部分失败，2=全部失败，3=参数/校验错误

崩溃隔离：本进程崩溃不影响主服务。主进程通过 stdout/returncode 感知。
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

# 确保能 import app.*（frozen 下 start_backend 已把 backend 根加入 sys.path）
from app.core.publisher._progress import emit_error, emit_log, emit_progress
from app.core.publisher.douyin import publish as douyin_publish, douyin_login as _douyin_login
from app.core.publisher import generic as generic_publisher
from app.core.publisher.types import (
    PublishResult,
    PublishTaskPayload,
    TaskItemResult,
    is_implemented_platform,
)


def _run_login(platform: str, account: str) -> int:
    """登录子模式：sys.executable --publisher-login <platform> <account>。"""
    try:
        if platform == "douyin":
            ok = asyncio_run(_douyin_login(account))
        else:
            # 其余平台走通用登录流程
            ok = asyncio_run(generic_publisher.login(platform, account))
        return 0 if ok else 1
    except Exception:
        emit_error(f"登录异常:\n{traceback.format_exc()}")
        return 2


def asyncio_run(coro):
    """兼容 Python 3.10+ 的 asyncio.run 包装。"""
    import asyncio
    return asyncio.run(coro)


def main(task_json_path: str) -> int:
    """发布任务主入口。读 task.json → 执行 → 写 result.json。"""
    # 延迟 import，避免登录模式不需要时也加载
    result_dir = Path(task_json_path).parent

    try:
        payload = PublishTaskPayload.from_dict(
            json.loads(Path(task_json_path).read_text(encoding="utf-8"))
        )
    except Exception as exc:
        emit_error(f"读取 task.json 失败: {exc}")
        return 3

    emit_log(f"=== 发布任务开始 task_id={payload.task_id} ===")
    emit_log(f"视频: {payload.video_path}")
    emit_log(f"目标平台: {[it.platform for it in payload.items]}")
    emit_log(f"浏览器模式: {'无头（后台）' if payload.headless else '有头（显示窗口，便于排查）'}")

    # 把 headless 写入环境变量，供 generic.py / douyin.py 读取（两者用不同变量名，统一设置）
    headless_env = "true" if payload.headless else "false"
    os.environ["PUBLISH_HEADLESS"] = headless_env
    os.environ["DOUYIN_PUBLISH_HEADLESS"] = headless_env

    # 视频文件校验
    if not Path(payload.video_path).is_file():
        emit_error(f"视频文件不存在: {payload.video_path}")
        _write_result(result_dir, payload.task_id, "failed", [
            TaskItemResult(platform="all", status="failed", message=f"视频文件不存在: {payload.video_path}")
        ])
        return 2

    results: list[TaskItemResult] = []
    total = len(payload.items)
    for idx, item in enumerate(payload.items):
        platform = item.platform
        emit_log(f"\n--- [{idx + 1}/{total}] 平台: {platform} 账号: {item.account} ---")

        if not is_implemented_platform(platform):
            emit_progress(platform=platform, account=item.account, step="", status="skipped", pct=0,
                          message=f"平台 {platform} 暂未实现，跳过")
            results.append(TaskItemResult(
                platform=platform, account=item.account, status="skipped",
                message=f"平台 {platform} 暂未实现",
            ))
            continue

        # 账号任务边界进度：让前端知道"现在在发哪个账号（第几个/共几个）"
        emit_progress(platform=platform, account=item.account, step="start", status="running", pct=0,
                      message=f"[{idx + 1}/{total}] 开始发布")

        try:
            if platform == "douyin":
                # 抖音用独立模块（DOM 适配最完整，已深度联调）
                r = asyncio_run(douyin_publish(item, payload.video_path))
            else:
                # 其余平台走通用流程（generic.py + platform_registry 配置）
                r = asyncio_run(generic_publisher.publish(item, payload.video_path))
            results.append(r)
        except Exception as exc:
            emit_error(f"平台 {platform} 执行异常:\n{traceback.format_exc()}")
            results.append(TaskItemResult(
                platform=platform, account=item.account, status="failed",
                message=f"执行异常: {exc}",
            ))

    # 汇总状态
    n_success = sum(1 for r in results if r.status == "success")
    n_failed = sum(1 for r in results if r.status == "failed")
    if n_success == len(results):
        overall = "succeeded"
        exit_code = 0
    elif n_failed == len(results):
        overall = "failed"
        exit_code = 2
    else:
        overall = "partial"
        exit_code = 1

    emit_log(f"\n=== 任务结束 overall={overall} 成功 {n_success} 失败 {n_failed} ===")
    _write_result(result_dir, payload.task_id, overall, results)
    return exit_code


def _write_result(result_dir: Path, task_id: str, status: str, items: list[TaskItemResult]) -> None:
    """写 result.json 到 task.json 同目录。"""
    result = PublishResult(task_id=task_id, status=status, items=items)
    result_path = result_dir / f"result_{task_id}.json"
    try:
        result_path.write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        emit_log(f"结果已写入: {result_path}")
    except Exception as exc:
        emit_error(f"写 result.json 失败: {exc}")


def entry() -> int:
    """统一入口：根据 argv[1] 分发 login / publish 模式。

    调用约定（见 start_backend.py 入口分流）：
        --publisher-login  <platform> <account>     登录子模式
        --publisher-worker <task.json>              发布子模式
    """
    if len(sys.argv) < 3:
        emit_error(f"参数不足: {sys.argv}")
        return 3

    mode = sys.argv[1]
    if mode == "--publisher-login":
        if len(sys.argv) < 4:
            emit_error("登录模式需要 platform 和 account 参数")
            return 3
        return _run_login(sys.argv[2], sys.argv[3])
    elif mode == "--publisher-worker":
        return main(sys.argv[2])
    else:
        emit_error(f"未知子进程模式: {mode}")
        return 3


if __name__ == "__main__":
    sys.exit(entry())
