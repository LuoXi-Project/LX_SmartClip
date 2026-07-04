"""多平台视频一键发布模块（social-auto-upload 源码内联 + 桌面化改造）。

设计要点：
- 浏览器引擎：优先用户本地 Chrome/Edge（指纹真实、版本自更新、风控更友好），包内 Chromium 兜底。
- 执行模型：每个发布任务由独立子进程执行（复用打包 exe + --publisher-worker argv 分流），崩溃隔离。
- 数据持久化：cookie/storage_state 落 <home>/data/cookies/，任务记录落 smartclip.db。
- 反检测：使用 patchright（Playwright 反检测分支）+ stealth.min.js 注入。

仅抖音（douyin）在阶段 1 实现；其余平台预留接口。
"""
from app.core.publisher._browser import (  # noqa: F401
    BrowserKind,
    resolve_browser,
)
from app.core.publisher.types import (  # noqa: F401
    PLATFORMS,
    PublishItem,
    PublishResult,
    PublishTaskPayload,
    TaskItemResult,
    is_supported_platform,
)

__all__ = [
    "BrowserKind",
    "PLATFORMS",
    "PublishItem",
    "PublishResult",
    "PublishTaskPayload",
    "TaskItemResult",
    "is_supported_platform",
    "resolve_browser",
]
