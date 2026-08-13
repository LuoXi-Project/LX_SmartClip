"""音频库任务 runner（主进程侧）：拉起 worker 子进程并监控。

仿 publisher/runner.py，职责：
1. 收到请求 → 生成 task.json → subprocess 拉起 worker
2. 异步读 stdout 每行，解析 PROGRESS 行更新 DB
3. 子进程结束按 returncode + result.json 判定最终状态
4. 提供取消能力（kill 子进程）

用 subprocess.Popen + 后台线程读 stdout（兼容 uvicorn --reload 的 SelectorEventLoop）。
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

from app.core.audio_library.types import AudioTaskPayload
from app.utils.paths import get_writable_backend_root

logger = logging.getLogger("audio_library.runner")

# 运行中的子进程注册表：task_id -> ProcessHandle
_running: dict[str, "ProcessHandle"] = {}


@dataclass
class ProcessHandle:
    task_id: str
    proc: subprocess.Popen
    log_lines: list[str] = field(default_factory=list)
    cancelled: bool = False
    _out_queue: "queue.Queue[Optional[str]]" = field(default_factory=queue.Queue)
    _reader_thread: Optional[threading.Thread] = None

    def start_reader(self) -> None:
        def _read():
            try:
                for raw in self.proc.stdout:
                    self._out_queue.put(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
            except Exception as exc:
                logger.warning("读 worker stdout 异常 task_id=%s: %s", self.task_id, exc)
            finally:
                self._out_queue.put(None)

        self._reader_thread = threading.Thread(target=_read, daemon=True, name=f"audio-{self.task_id[:8]}")
        self._reader_thread.start()


def _worker_cmd(extra_args: list[str]) -> list[str]:
    """构造 worker 子进程命令（仿 publisher/runner._worker_cmd）。"""
    if getattr(sys, "frozen", False):
        return [sys.executable, *extra_args]
    # 本文件位于 backend/app/core/audio_library/runner.py，上溯 4 层到 backend/
    entry = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "start_backend.py",
    )
    return [sys.executable, entry, *extra_args]


def _launch_subprocess(cmd: list[str], *, detached: bool = False) -> subprocess.Popen:
    creationflags = 0
    if os.name == "nt":
        creationflags = 0x08000000  # CREATE_NO_WINDOW
        if detached:
            creationflags |= 0x00000200  # CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )


def _queue_get_timeout(q: "queue.Queue[Optional[str]]", timeout: float) -> Optional[str]:
    return q.get(block=True, timeout=timeout)


def _tasks_dir() -> Path:
    d = get_writable_backend_root() / "data" / "audio_tasks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_task_json(payload: AudioTaskPayload) -> Path:
    d = _tasks_dir()
    path = d / f"task_{payload.task_id}.json"
    path.write_text(json.dumps(payload.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_result_json(task_id: str) -> Optional[dict]:
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


async def _maybe_await(fn, *args):
    if fn is None:
        return
    r = fn(*args)
    if asyncio.iscoroutine(r):
        await r


async def start_worker(
    payload: AudioTaskPayload,
    on_progress=None,
    on_complete=None,
) -> None:
    """拉起 worker 子进程并监控到结束。

    Args:
        payload: 任务载荷（先写 task.json）
        on_progress: async 回调 (task_id, progress_dict) -> None
        on_complete: async 回调 (task_id, status, result_dict_or_none) -> None
    """
    task_id = payload.task_id
    task_json = write_task_json(payload)
    cmd = _worker_cmd(["--audio-worker", str(task_json)])

    try:
        proc = await asyncio.to_thread(_launch_subprocess, cmd)
    except Exception as exc:
        logger.exception("启动 worker 失败 task_id=%s", task_id)
        if on_complete:
            await _maybe_await(on_complete, task_id, "failed", {"error": f"启动子进程失败: {exc}"})
        return

    handle = ProcessHandle(task_id=task_id, proc=proc)
    handle.start_reader()
    _running[task_id] = handle
    logger.info("audio worker 已启动 task_id=%s pid=%s", task_id, proc.pid)

    loop = asyncio.get_running_loop()
    final_status = "failed"
    try:
        while True:
            try:
                line = await loop.run_in_executor(None, _queue_get_timeout, handle._out_queue, 0.2)
            except queue.Empty:
                continue

            if line is None:
                break
            if not line:
                continue
            handle.log_lines.append(line)

            if line.startswith("PROGRESS "):
                try:
                    prog = json.loads(line[len("PROGRESS "):])
                    if on_progress:
                        await _maybe_await(on_progress, task_id, prog)
                except json.JSONDecodeError:
                    logger.debug("无法解析进度行: %s", line)
            elif on_progress:
                await _maybe_await(on_progress, task_id, {"log": line})

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


async def start_login_worker(source: str, account: str, on_complete=None) -> None:
    """拉起登录子进程（--audio-login）。"""
    cmd = _worker_cmd(["--audio-login", source, account])

    try:
        proc = await asyncio.to_thread(_launch_subprocess, cmd, detached=True)
    except Exception as exc:
        logger.exception("启动登录 worker 失败 source=%s", source)
        if on_complete:
            await _maybe_await(on_complete, source, account, False, str(exc))
        return

    logger.info("audio 登录 worker 已启动 source=%s account=%s pid=%s", source, account, proc.pid)
    handle = ProcessHandle(task_id=f"audio-login-{source}", proc=proc)
    handle.start_reader()
    loop = asyncio.get_running_loop()

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
            await _maybe_await(on_complete, source, account, success, "\n".join(log_buf[-20:]))
    except Exception as exc:
        logger.exception("监控登录 worker 异常 source=%s", source)
        if on_complete:
            await _maybe_await(on_complete, source, account, False, str(exc))
