"""worker 子进程的进度上报协议。

worker 把每步进度以单行 JSON 写到 stdout，主进程的 runner 逐行读取解析。
格式（每行一条，前缀 PROGRESS）：
    PROGRESS {"platform":"douyin","step":"login_check","status":"running","pct":10,"message":"..."}

主进程据此更新 publish_tasks.log 和 result 字段。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime


def emit_progress(
    *,
    platform: str,
    step: str = "",
    status: str = "running",   # running | success | failed | skipped
    pct: int = 0,              # 0-100
    message: str = "",
) -> None:
    """向 stdout 输出一行进度（立即 flush）。

    step 取值约定（各平台尽量统一）：
      login_check / login_qrcode / login_wait / upload_start / uploading /
      fill_meta / set_cover / publishing / publish_done / publish_failed
    """
    payload = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "platform": platform,
        "step": step,
        "status": status,
        "pct": max(0, min(100, int(pct))),
        "message": message,
    }
    line = "PROGRESS " + json.dumps(payload, ensure_ascii=False)
    print(line, flush=True)


def emit_log(message: str) -> None:
    """普通日志行（不带 PROGRESS 前缀），runner 也收集但仅落 log 不驱动进度条。"""
    print(message, flush=True)


def emit_error(message: str) -> None:
    """错误行，写到 stderr。"""
    print(message, file=sys.stderr, flush=True)
