"""反检测脚本注入（替代上游 utils/base_social_media.set_init_script）。

去掉对上游 conf.BASE_DIR 的依赖，改用 __file__ 定位同目录的 stealth.min.js。
stealth.min.js 来自 puppeteer-extra-plugin-stealth，给 Chromium 注入反自动化检测的初始化脚本。
用本地 Chrome/Edge 时本脚本作用有限（本地浏览器本身指纹真实），但仍注入以双保险。
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("publisher")

_STEALTH_JS_PATH = Path(__file__).resolve().parent / "stealth.min.js"


async def set_init_script(context):
    """给浏览器上下文注入 stealth.min.js。"""
    if not _STEALTH_JS_PATH.is_file():
        logger.warning("stealth.min.js 未找到: %s，跳过反检测注入", _STEALTH_JS_PATH)
        return context
    try:
        await context.add_init_script(path=str(_STEALTH_JS_PATH))
    except Exception as exc:
        logger.warning("注入 stealth.min.js 失败（忽略，继续运行）: %s", exc)
    return context
