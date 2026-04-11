from __future__ import annotations

import datetime as _dt
import logging
import logging.handlers
import os
import re
import sys
import threading
from collections import deque
from typing import Any

from app.utils.paths import get_storage_root

# 与 RotatingFileHandler 使用的 Formatter 一致（见 _build_file_handler）
_LOG_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[([^\]]+)\] ([^:]+): (.*)$"
)
# uvicorn dictConfig 里 file 可能共用带 ANSI 的 color formatter，剥离后形如：时间 | LEVEL | logger | message
_UVICORN_FILE_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| *(\w+) *\| *([^|]+?) \| (.*)$"
)
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")

try:
    from zoneinfo import ZoneInfo

    _TZ_BEIJING: _dt.tzinfo = ZoneInfo("Asia/Shanghai")
except Exception:
    # Windows 等环境缺少 IANA 数据时，用固定 UTC+8（中国不实行 DST）
    _TZ_BEIJING = _dt.timezone(_dt.timedelta(hours=8))


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
            created = _dt.datetime.fromtimestamp(record.created, tz=_TZ_BEIJING).isoformat()
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


def memory_handler_for_dictconfig(*_args: Any, **_kwargs: Any) -> MemoryLogHandler:
    """
    供 logging.config.dictConfig 使用。

    uvicorn 的 logger 默认 propagate=False，若在此单独实例化 MemoryLogHandler，
    会与 get_memory_log_handler() 的单例脱节，导致 /api/logs 只能看到少量根 logger 日志。
    """
    return get_memory_log_handler()


def _resolve_log_dir() -> str:
    """
    日志落盘目录：与 `get_storage_root()/logs` 对齐；其次包内副本；最后当前工作目录。
    """
    candidates: list[str] = []

    try:
        candidates.append(str(get_storage_root() / "logs"))
    except Exception:
        pass

    try:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            candidates.append(os.path.join(getattr(sys, "_MEIPASS"), "storage", "logs"))  # type: ignore[attr-defined]
    except Exception:
        pass

    candidates.append(os.path.abspath(os.path.join(os.getcwd(), "storage", "logs")))

    for d in candidates:
        try:
            os.makedirs(d, exist_ok=True)
            return d
        except Exception:
            continue

    # 极端兜底：当前目录
    return os.getcwd()


def _sorted_app_log_paths(log_dir: str) -> list[str]:
    """RotatingFileHandler：.4 最旧 … .1 较新，app.log 为当前写入文件。按时间顺序从旧到新读取。"""
    try:
        names = [
            n
            for n in os.listdir(log_dir)
            if n == "app.log" or (n.startswith("app.log.") and len(n) > 8 and n[8:].isdigit())
        ]
    except OSError:
        return []

    def sort_key(n: str) -> int:
        if n == "app.log":
            return 0
        return int(n[8:])

    names.sort(key=sort_key, reverse=True)
    return [os.path.join(log_dir, n) for n in names]


def _parse_app_log_lines(lines: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for raw in lines:
        line = _ANSI_ESCAPE_RE.sub("", raw).rstrip("\r\n")
        if not line:
            if cur is not None:
                cur["message"] += "\n"
            continue
        m = _LOG_LINE_RE.match(line)
        if not m:
            m = _UVICORN_FILE_LINE_RE.match(line)
        if m:
            ts_raw, level, logger, message = m.group(1), m.group(2), m.group(3), m.group(4)
            try:
                naive = _dt.datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S")
                ts = naive.replace(tzinfo=_TZ_BEIJING).isoformat()
            except ValueError:
                ts = ts_raw
            cur = {"ts": ts, "level": level.strip(), "logger": logger.strip(), "message": message.strip()}
            out.append(cur)
        elif cur is not None:
            cur["message"] += "\n" + line
        else:
            out.append({"ts": "", "level": "INFO", "logger": "", "message": line})
            cur = None
    return out


def query_file_logs(
    *,
    q: str | None = None,
    limit: int = 200,
    level: str | None = None,
    max_scan_lines: int = 80_000,
) -> list[dict[str, Any]]:
    """
    从 storage/logs/app.log（及轮转备份）解析最近若干行，格式与内存日志接口一致。
    文件中的 asctime 按本地写入习惯视为北京时间（与落盘 Formatter 一致）。
    """
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

    try:
        cap = int(max_scan_lines)
    except Exception:
        cap = 80_000
    if cap < 1000:
        cap = 1000
    if cap > 500_000:
        cap = 500_000

    log_dir = _resolve_log_dir()
    paths = _sorted_app_log_paths(log_dir)
    if not paths:
        return []

    buf: deque[str] = deque(maxlen=cap)
    for path in paths:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    buf.append(line.rstrip("\r\n"))
        except OSError:
            continue

    records = _parse_app_log_lines(list(buf))

    # ISO 时间字符串可字典序比较；空 ts 视为最旧，排在末尾
    records.sort(key=lambda it: it.get("ts") or "", reverse=True)

    out: list[dict[str, Any]] = []
    for it in records:
        if lvl and (it.get("level") or "").upper() != lvl:
            continue
        if q_norm:
            hay = f"{it.get('ts','')} {it.get('level','')} {it.get('logger','')} {it.get('message','')}".lower()
            if q_norm not in hay:
                continue
        out.append(dict(it))
        if len(out) >= lim:
            break
    return out


def merge_log_items(a: list[dict[str, Any]], b: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    merged = sorted(a + b, key=lambda x: (x.get("ts") or ""), reverse=True)
    out: list[dict[str, Any]] = []
    for it in merged:
        k = (it.get("ts") or "", it.get("level") or "", it.get("logger") or "", it.get("message") or "")
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
        if len(out) >= limit:
            break
    return out


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
            # 进程内 ring buffer：与 get_memory_log_handler() 同一实例，避免 uvicorn 与业务日志分仓
            "memory": {"()": "app.utils.logging_utils.memory_handler_for_dictconfig", "level": "DEBUG"},
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

