"""文案驱动的素材匹配 API（聚合路由）。"""
from app.api.script_stock_shared import router

import app.api.script_stock_script  # noqa: F401,E402
import app.api.script_stock_pexels  # noqa: F401,E402
import app.api.script_stock_providers  # noqa: F401,E402
import app.api.script_stock_compose  # noqa: F401,E402

__all__ = ["router"]
