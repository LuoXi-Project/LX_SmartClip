from __future__ import annotations

import logging
import sys
from typing import Any


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
    if root.handlers and not force:
        return

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
    root.addHandler(handler)


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

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": formatters,
        "handlers": {
            "default": {"class": "logging.StreamHandler", "formatter": "default", "stream": "ext://sys.stderr"},
            "access": {"class": "logging.StreamHandler", "formatter": "access", "stream": "ext://sys.stdout"},
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": level, "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": level, "propagate": False},
            "uvicorn.access": {"handlers": ["access"], "level": level, "propagate": False},
        },
    }

