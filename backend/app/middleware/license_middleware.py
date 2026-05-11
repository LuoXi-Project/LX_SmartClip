import logging
from typing import Callable, Awaitable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.license import ensure_license_valid, has_card_server_config, is_license_enforced

logger = logging.getLogger(__name__)

# 公共路径 不需要进行授权检查就可访问
PUBLIC_PREFIXES = (
    "/api/license",
    "/api/config",
    "/library",
)


def _is_public_path(path: str) -> bool:
    if path in ("/", "/favicon.ico"):
        return True

    # 只对后端 API 做卡密限制；前端页面与静态资源必须始终可访问，
    # 否则会出现构建后页面资源（如 *.txt / _next）被 401 拦截导致前端崩溃。
    if not path.startswith("/api"):
        return True

    # /api 下仅允许白名单 API 不做授权检查
    for prefix in PUBLIC_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


class LicenseMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not is_license_enforced():
            return await call_next(request)
        path = request.url.path
        if _is_public_path(path):
            return await call_next(request)

        # 未配置卡密服务器地址时，所有业务接口不可用（不能通过删配置文件绕过）
        if not has_card_server_config():
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "缺少卡密服务器配置：请在 backend/config.json 中配置 卡密服务器.API地址",
                    "code": "CARD_SERVER_CONFIG_MISSING",
                },
            )
        ok = await ensure_license_valid()
        if not ok:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "未授权：请先完成卡密激活或卡密已失效",
                    "code": "LICENSE_REQUIRED",
                },
            )
        return await call_next(request)
