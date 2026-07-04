"""发布任务 runner（主进程侧）：拉起 worker 子进程并监控。

职责：
1. 收到发布请求 → 生成 task.json → subprocess 拉起 worker
2. 异步读 stdout 每行，解析 PROGRESS 行更新 DB（log + 进度）
3. 子进程结束按 returncode + result.json 判定最终状态
4. 提供取消能力（kill 子进程）

实现说明：用标准库 subprocess.Popen + 后台线程读 stdout（而非 asyncio.create_subprocess_exec）。
原因：uvicorn --reload 模式在 Windows 用 SelectorEventLoop，不支持子进程传输（NotImplementedError）。
subprocess.Popen 不依赖事件循环的子进程支持，在任何事件循环类型下都能工作。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.core.publisher.types import PublishTaskPayload
from app.utils.paths import get_writable_backend_root

logger = logging.getLogger("publisher.runner")

# 运行中的子进程注册表：task_id -> ProcessHandle（用于取消）
_running: dict[str, "ProcessHandle"] = {}


@dataclass
class ProcessHandle:
    task_id: str
    proc: subprocess.Popen
    log_lines: list[str] = field(default_factory=list)
    cancelled: bool = False
    # 后台读 stdout 的线程 + 队列
    _out_queue: "queue.Queue[Optional[str]]" = field(default_factory=queue.Queue)
    _reader_thread: Optional[threading.Thread] = None

    def start_reader(self) -> None:
        """启动后台线程逐行读 stdout，放入队列（None 作为结束哨兵）。"""
        def _read():
            try:
                for raw in self.proc.stdout:
                    self._out_queue.put(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
            except Exception as exc:
                logger.warning("读 worker stdout 异常 task_id=%s: %s", self.task_id, exc)
            finally:
                self._out_queue.put(None)  # 结束哨兵

        self._reader_thread = threading.Thread(target=_read, daemon=True, name=f"pub-{self.task_id[:8]}")
        self._reader_thread.start()


def _worker_cmd(extra_args: list[str]) -> list[str]:
    """构造 worker 子进程命令。

    frozen 下 sys.executable 是打包 exe 本身，直接接 --publisher-* 参数；
    开发环境下 sys.executable 是 python.exe，需要 python.exe start_backend.py --publisher-*。
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, *extra_args]
    # 开发环境：start_backend.py 与本文件（runner.py）相对位置 = backend/start_backend.py
    entry = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "start_backend.py")
    return [sys.executable, entry, *extra_args]


def _launch_subprocess(cmd: list[str], *, detached: bool = False) -> subprocess.Popen:
    """启动子进程（同步，不依赖事件循环）。

    Windows 下默认 CREATE_NO_WINDOW 隐藏控制台。
    detached=True 时额外加 CREATE_NEW_PROCESS_GROUP（不加 DETACHED_PROCESS，
    后者在无控制台子进程上会新建一个 cmd 窗口），让子进程独立于父进程生命周期。
    """
    creationflags = 0
    if os.name == "nt":
        creationflags = 0x08000000  # CREATE_NO_WINDOW
        if detached:
            # CREATE_NEW_PROCESS_GROUP (0x00000200)：脱离父进程控制台组，
            # 父进程如 uvicorn --reload 重启时不会连带向子进程发 Ctrl-Break。
            # 不用 DETACHED_PROCESS（会导致无控制台进程新建 cmd 窗口）。
            creationflags |= 0x00000200
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
        # binary 模式读 bytes（reader 线程自己 decode）；不设 bufsize=1（行缓冲仅文本模式有效）
    )


def _queue_get_timeout(q: "queue.Queue[Optional[str]]", timeout: float) -> Optional[str]:
    """阻塞读队列，超时抛 queue.Empty。供 run_in_executor 调用。"""
    return q.get(block=True, timeout=timeout)


def _tasks_dir() -> Path:
    """task.json / result.json 临时目录：<home>/data/publish_tasks/。"""
    d = get_writable_backend_root() / "data" / "publish_tasks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_task_json(payload: PublishTaskPayload) -> Path:
    """把任务载荷写到 task.json，返回路径。"""
    d = _tasks_dir()
    path = d / f"task_{payload.task_id}.json"
    path.write_text(
        json.dumps(payload.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def read_result_json(task_id: str) -> Optional[dict]:
    """读 result.json（worker 结束后写）。"""
    path = _tasks_dir() / f"result_{task_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def is_running(task_id: str) -> bool:
    h = _running.get(task_id)
    return h is not None and h.proc.returncode is None


def cancel(task_id: str) -> bool:
    """取消任务：kill 子进程。返回是否成功发出 kill。"""
    h = _running.get(task_id)
    if h is None or h.proc.returncode is not None:
        return False
    h.cancelled = True
    try:
        h.proc.kill()
        return True
    except ProcessLookupError:
        return False
    except Exception as exc:
        logger.warning("kill 子进程失败 task_id=%s: %s", task_id, exc)
        return False


async def start_worker(
    payload: PublishTaskPayload,
    on_progress=None,
    on_complete=None,
) -> None:
    """拉起 worker 子进程并监控到结束。

    用 subprocess.Popen（同步）+ 后台线程读 stdout + asyncio 协程轮询队列。
    不依赖事件循环的子进程支持（兼容 uvicorn --reload 的 SelectorEventLoop）。

    Args:
        payload: 任务载荷（会先写 task.json）
        on_progress: async 回调 (task_id, progress_dict) -> None，每收到一行进度调用
        on_complete: async 回调 (task_id, status, result_dict_or_none) -> None
    """
    task_id = payload.task_id
    task_json = write_task_json(payload)

    # 构造子进程命令：复用当前 python 解释器（frozen 下是 exe 本身）
    cmd = _worker_cmd(["--publisher-worker", str(task_json)])

    try:
        proc = await asyncio.to_thread(_launch_subprocess, cmd)
    except Exception as exc:
        logger.exception("启动 worker 失败 task_id=%s", task_id)
        if on_complete:
            await _maybe_await(on_complete, task_id, "failed", {"error": f"启动子进程失败: {exc}"})
        return

    handle = ProcessHandle(task_id=task_id, proc=proc)
    handle.start_reader()  # 启动后台读线程
    _running[task_id] = handle
    logger.info("worker 已启动 task_id=%s pid=%s", task_id, proc.pid)

    loop = asyncio.get_running_loop()
    final_status = "failed"
    try:
        # 轮询队列（用 run_in_executor 避免 sleep 阻塞事件循环）
        while True:
            try:
                # 非阻塞取，0.2s 超时让出事件循环
                line = await loop.run_in_executor(None, _queue_get_timeout, handle._out_queue, 0.2)
            except queue.Empty:
                continue

            if line is None:
                # 读线程结束（子进程 stdout 关闭）
                break
            if not line:
                continue
            handle.log_lines.append(line)

            # 解析 PROGRESS 行
            if line.startswith("PROGRESS "):
                try:
                    prog = json.loads(line[len("PROGRESS "):])
                    if on_progress:
                        await _maybe_await(on_progress, task_id, prog)
                except json.JSONDecodeError:
                    logger.debug("无法解析进度行: %s", line)
            elif on_progress:
                await _maybe_await(on_progress, task_id, {"log": line})

        # 等子进程真正结束（stdout 关闭后通常已退出，但保险 wait）
        await loop.run_in_executor(None, proc.wait)

        if handle.cancelled:
            final_status = "cancelled"
        else:
            result = read_result_json(task_id)
            if result:
                final_status = result.get("status", "failed")
            else:
                final_status = "failed"
    except Exception:
        logger.exception("监控 worker 异常 task_id=%s", task_id)
        final_status = "failed"
    finally:
        _running.pop(task_id, None)
        result = read_result_json(task_id) if not handle.cancelled else None
        if on_complete:
            await _maybe_await(on_complete, task_id, final_status, result)


async def _maybe_await(fn, *args):
    """回调可能是 sync 或 async，统一处理。"""
    if fn is None:
        return
    r = fn(*args)
    if asyncio.iscoroutine(r):
        await r


# ── 登录子进程 ─────────────────────────────────────────────────────────────
async def start_login_worker(platform: str, account: str, on_complete=None) -> None:
    """拉起登录子进程（--publisher-login）。

    登录流程会弹出可见浏览器窗口供用户扫码，结束后回调。
    同样用 subprocess.Popen（兼容 SelectorEventLoop）。
    """
    cmd = _worker_cmd(["--publisher-login", platform, account])

    try:
        # detached=True：让登录浏览器进程独立于 uvicorn 主进程生命周期
        # （--reload 模式下主进程重启不会连带杀死登录 worker）
        proc = await asyncio.to_thread(_launch_subprocess, cmd, detached=True)
    except Exception as exc:
        logger.exception("启动登录 worker 失败 platform=%s", platform)
        if on_complete:
            await _maybe_await(on_complete, platform, account, False, str(exc))
        return

    logger.info("登录 worker 已启动 platform=%s account=%s pid=%s", platform, account, proc.pid)

    # 用临时 handle 复用读线程机制
    handle = ProcessHandle(task_id=f"login-{platform}", proc=proc)
    handle.start_reader()
    loop = asyncio.get_running_loop()

    # 收集日志（登录 worker 也走 emit_progress/emit_log 协议）
    log_buf: list[str] = []
    try:
        while True:
            try:
                line = await loop.run_in_executor(None, _queue_get_timeout, handle._out_queue, 0.5)
            except queue.Empty:
                continue
            if line is None:
                break
            if line:
                log_buf.append(line)
        await loop.run_in_executor(None, proc.wait)
        success = proc.returncode == 0
        if on_complete:
            await _maybe_await(on_complete, platform, account, success, "\n".join(log_buf[-20:]))
    except Exception as exc:
        logger.exception("监控登录 worker 异常 platform=%s", platform)
        if on_complete:
            await _maybe_await(on_complete, platform, account, False, str(exc))
