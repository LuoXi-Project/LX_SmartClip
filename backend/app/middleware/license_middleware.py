import logging
from typing import Callable, Awaitable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.license import ensure_license_valid, is_license_enforced

logger = logging.getLogger(__name__)

PUBLIC_PREFIXES = (
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/api/license",
)


def _is_public_path(path: str) -> bool:
    if path in ("/", "/favicon.ico"):
        return True
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
