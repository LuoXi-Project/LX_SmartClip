from __future__ import annotations

import datetime as _dt
import logging
import logging.handlers
import os
import sys
import threading
from collections import deque
from typing import Any


class MemoryLogHandler(logging.Handler):
    """
    进程内日志环形缓冲（用于前端排障查看）。

    - 不落盘：避免写权限/路径差异带来的问题
    - 有上限：避免内存无限增长
    """

    def __init__(self, capacity: int = 5000) -> None:
        super().__init__()
        self.capacity = int(capacity) if int(capacity) > 0 else 5000
        self._lock = threading.Lock()
        self._items: deque[dict[str, Any]] = deque(maxlen=self.capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            created = _dt.datetime.fromtimestamp(record.created, tz=_dt.timezone.utc).isoformat()
            item = {
                "ts": created,
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            with self._lock:
                self._items.append(item)
        except Exception:
            # 不能让日志 handler 影响业务
            return

    def query(self, *, q: str | None = None, limit: int = 200, level: str | None = None) -> list[dict[str, Any]]:
        q_norm = (q or "").strip().lower()
        lvl = (level or "").strip().upper()
        try:
            lim = int(limit)
        except Exception:
            lim = 200
        if lim <= 0:
            lim = 200
        if lim > 5000:
            lim = 5000

        with self._lock:
            items = list(self._items)

        # newest first
        items.reverse()

        out: list[dict[str, Any]] = []
        for it in items:
            if lvl and (it.get("level") or "").upper() != lvl:
                continue
            if q_norm:
                hay = f"{it.get('ts','')} {it.get('level','')} {it.get('logger','')} {it.get('message','')}".lower()
                if q_norm not in hay:
                    continue
            out.append(it)
            if len(out) >= lim:
                break
        return out


_MEMORY_HANDLER: MemoryLogHandler | None = None


def get_memory_log_handler() -> MemoryLogHandler:
    global _MEMORY_HANDLER
    if _MEMORY_HANDLER is None:
        _MEMORY_HANDLER = MemoryLogHandler(capacity=5000)
        _MEMORY_HANDLER.setLevel(logging.DEBUG)
    return _MEMORY_HANDLER


def _resolve_log_dir() -> str:
    """
    日志落盘目录：
    - 源码运行：backend/storage/logs
    - 打包运行：优先尝试 _MEIPASS/storage/logs；失败则退回到当前工作目录 ./storage/logs
    """
    candidates: list[str] = []

    # 源码：.../backend/app/utils/logging_utils.py -> .../backend/storage/logs
    try:
        backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        candidates.append(os.path.join(backend_root, "storage", "logs"))
    except Exception:
        pass

    # 打包：_MEIPASS/storage/logs
    try:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            candidates.append(os.path.join(getattr(sys, "_MEIPASS"), "storage", "logs"))  # type: ignore[attr-defined]
    except Exception:
        pass

    # 最后兜底：当前工作目录
    candidates.append(os.path.abspath(os.path.join(os.getcwd(), "storage", "logs")))

    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            return d
        except Exception:
            continue

    # 极端兜底：当前目录
    return os.getcwd()


def _build_file_handler(level: int) -> logging.Handler:
    log_dir = _resolve_log_dir()
    log_path = os.path.join(log_dir, "app.log")

    # 20MB * (1 + 4 backups) ≈ 100MB
    handler = logging.handlers.RotatingFileHandler(
        filename=log_path,
        maxBytes=20 * 1024 * 1024,
        backupCount=4,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    return handler


def _try_build_color_formatter(fmt: str, datefmt: str, *, for_access: bool = False):
    try:
        from colorlog import ColoredFormatter  # type: ignore

        # 主流模式：按 level 着色，同时对字段分段着色（时间/模块名等保持稳定颜色）
        # 例子（root）：灰色时间 + [彩色LEVEL] + 紫色logger + message
        # 例子（access）：灰色时间 + [彩色LEVEL] + 蓝色uvicorn.access + 白色message
        return ColoredFormatter(
            fmt=fmt,
            datefmt=datefmt,
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            },
            secondary_log_colors={
                # 针对 access 日志：让 logger 名称更稳定、更好辨识
                "name": {
                    "DEBUG": "blue",
                    "INFO": "blue",
                    "WARNING": "blue",
                    "ERROR": "blue",
                    "CRITICAL": "blue",
                }
                if for_access
                else {
                    # 业务日志：logger 名称用紫色更醒目
                    "DEBUG": "purple",
                    "INFO": "purple",
                    "WARNING": "purple",
                    "ERROR": "purple",
                    "CRITICAL": "purple",
                }
            },
            reset=True,
        )
    except Exception:
        return None


def setup_logging(level: int = logging.INFO, *, force: bool = False) -> None:
    """
    Initialize root logging once (idempotent).

    - Uses `colorlog` when available for colored output
    - Falls back to plain formatter when unavailable
    - If `force=True`, clears existing root handlers and reconfigures
    """
    root = logging.getLogger()

    if force:
        for h in list(root.handlers):
            root.removeHandler(h)

    datefmt = "%Y-%m-%d %H:%M:%S"
    # 分段上色：时间(灰) / level(按级别) / logger(紫) / message(默认)
    # 无 colorlog 时会自动降级为普通文本格式。
    color_fmt = (
        "%(thin_white)s%(asctime)s%(reset)s "
        "[%(log_color)s%(levelname)s%(reset)s] "
        "%(name_log_color)s%(name)s%(reset)s: "
        "%(message)s"
    )
    plain_fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(level)

    color_formatter = _try_build_color_formatter(fmt=color_fmt, datefmt=datefmt, for_access=False)
    handler.setFormatter(color_formatter or logging.Formatter(fmt=plain_fmt, datefmt=datefmt))

    root.setLevel(level)
    # 避免重复添加相同类型的 handler
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        root.addHandler(handler)

    mem = get_memory_log_handler()
    if not any(isinstance(h, MemoryLogHandler) for h in root.handlers):
        root.addHandler(mem)

    # 按大小循环落盘，便于重启后追溯
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        root.addHandler(_build_file_handler(level))


def build_uvicorn_log_config(level: str = "INFO") -> dict[str, Any]:
    """
    Uvicorn logging config with colorlog (if available) + fallback.
    """
    datefmt = "%Y-%m-%d %H:%M:%S"
    color_default_fmt = (
        "%(thin_white)s%(asctime)s%(reset)s | "
        "%(log_color)s%(levelname)-8s%(reset)s | "
        "%(name_log_color)s%(name)s%(reset)s | "
        "%(message)s"
    )
    color_access_fmt = (
        "%(thin_white)s%(asctime)s%(reset)s | "
        "%(log_color)s%(levelname)-8s%(reset)s | "
        "%(name_log_color)s%(name)s%(reset)s | "
        "%(message)s"
    )
    plain_fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    default_color_formatter = _try_build_color_formatter(fmt=color_default_fmt, datefmt=datefmt, for_access=False)
    access_color_formatter = _try_build_color_formatter(fmt=color_access_fmt, datefmt=datefmt, for_access=True)
    if default_color_formatter is not None and access_color_formatter is not None:
        formatters: dict[str, Any] = {
            "default": {"()": lambda: default_color_formatter},
            "access": {"()": lambda: access_color_formatter},
        }
    else:
        formatters = {
            "default": {"format": plain_fmt, "datefmt": datefmt},
            "access": {"format": plain_fmt, "datefmt": datefmt},
        }

    # 让 uvicorn 的 dictConfig 也能落盘（同样的 20MB 循环策略）
    log_dir = _resolve_log_dir()
    file_path = os.path.join(log_dir, "app.log")

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": formatters,
        "handlers": {
            "default": {"class": "logging.StreamHandler", "formatter": "default", "stream": "ext://sys.stderr"},
            "access": {"class": "logging.StreamHandler", "formatter": "access", "stream": "ext://sys.stdout"},
            # 进程内 ring buffer：供前端读取排障
            "memory": {"class": "app.utils.logging_utils.MemoryLogHandler", "level": "DEBUG"},
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "filename": file_path,
                "maxBytes": 20 * 1024 * 1024,
                "backupCount": 4,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default", "memory", "file"], "level": level, "propagate": False},
            "uvicorn.error": {"handlers": ["default", "memory", "file"], "level": level, "propagate": False},
            "uvicorn.access": {"handlers": ["access", "memory", "file"], "level": level, "propagate": False},
        },
    }

