import logging

from app.utils.logging_utils import setup_logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from contextlib import asynccontextmanager
import os
import sys
from app.db.init_db import init_db
from app.utils.paths import get_storage_root, iter_storage_static_mount_candidates
from app.core.blocking_pool import init_blocking_pool, shutdown_blocking_pool
from app.api.config import router as config_router
from app.api.videos import router as videos_router
from app.api.clips import router as clips_router
from app.api.asr import router as asr_router
from app.api.voice_input import router as voice_input_router
from app.api.audio_match import router as audio_match_router
from app.api.vlm import router as vlm_router
from app.api.embed import router as embed_router
from app.api.process import router as process_router, jobs_router as process_jobs_router
from app.api.match import router as match_router
from app.api.search import router as search_router
from app.api.tts import router as tts_router
from app.api.export import router as export_router
from app.api.chat import router as chat_router
from app.api.copy_gen import router as copy_gen_router
from app.api.subtitle import router as subtitle_router
from app.api.auto_edit import router as auto_edit_router
from app.api.bgm import router as bgm_router
from app.api.replica import router as replica_router
from app.api.summary import router as summary_router
from app.api.script_stock import router as script_stock_router
from app.api.film_commentary import router as film_commentary_router
from app.api.agent import router as agent_router
from app.api.license import router as license_router
from app.api.logs import router as logs_router
from app.middleware.license_middleware import LicenseMiddleware


setup_logging(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await init_blocking_pool()
    try:
        yield
    finally:
        shutdown_blocking_pool()


app = FastAPI(title="LX SmartClip API", version="0.1.0", lifespan=lifespan)

app.add_middleware(LicenseMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(license_router)
app.include_router(config_router)
app.include_router(videos_router)
app.include_router(clips_router)
app.include_router(asr_router)
app.include_router(voice_input_router)
app.include_router(audio_match_router)
app.include_router(vlm_router)
app.include_router(embed_router)
app.include_router(process_router)
app.include_router(process_jobs_router)
app.include_router(match_router)
app.include_router(search_router)
app.include_router(tts_router)
app.include_router(export_router)
app.include_router(chat_router)
app.include_router(copy_gen_router)
app.include_router(subtitle_router)
app.include_router(auto_edit_router)
app.include_router(bgm_router)
app.include_router(logs_router)
app.include_router(replica_router)
app.include_router(summary_router)
app.include_router(script_stock_router)
app.include_router(film_commentary_router)
app.include_router(agent_router)


# 挂载 storage 目录，供前端直接下载烧录视频等静态文件
def _runtime_base_dir() -> str:
    # PyInstaller 环境下，资源文件会被解压到 sys._MEIPASS
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS  # type: ignore[attr-defined]
    return os.path.dirname(__file__)


_base_dir = _runtime_base_dir()

# 与业务写入目录一致：优先可写 storage，其次包内只读副本（见 app.utils.paths）
_storage_path = next((p for p in iter_storage_static_mount_candidates() if os.path.isdir(p)), None)
if not _storage_path:
    _sr = get_storage_root()
    _sr.mkdir(parents=True, exist_ok=True)
    _storage_path = str(_sr)
if _storage_path and os.path.isdir(_storage_path):
    print(f"挂载路径:{_storage_path}")
    app.mount("/storage", StaticFiles(directory=_storage_path), name="storage")

@app.get("/health")
async def health():
    return {"status": "ok"}


def _try_resolve_exported_html(path: str) -> str | None:
    """
    Next.js static export 默认会生成 `process.html` 这类文件，但用户直达时往往访问 `/process`。
    由于 StaticFiles 被 mount 到 `/` 后，这类 404 会发生在子应用里，主应用的 404 handler 接不到，
    所以这里显式把无扩展名路径映射到同名 `.html` 文件。
    """
    if not _frontend_dist_path:
        return None
    # 仅处理形如 "/process" 的页面路由；跳过 API/静态资源/带扩展名路径
    if path.startswith("/api") or path.startswith("/storage"):
        return None
    if "." in os.path.basename(path):
        return None
    name = path.strip("/").strip()
    if not name:
        return None
    candidate = os.path.join(_frontend_dist_path, f"{name}.html")
    return candidate if os.path.isfile(candidate) else None


@app.get("/{page_name}")
async def exported_page_alias(page_name: str):
    html = _try_resolve_exported_html("/" + page_name)
    if html:
        return FileResponse(html)
    raise StarletteHTTPException(status_code=404)


# 挂载前端静态导出目录（scripts/build_release.* 会将 frontend/out 拷贝到此处）
# 注意：必须放在路由定义之后挂载，避免 mount("/", ...) 抢占诸如 "/health" 这类 API 路由。
_frontend_dist_path_candidates = (
    os.path.abspath(os.path.join(os.path.dirname(__file__), "static", "frontend")),  # 源码：backend/app/static/frontend
    os.path.abspath(os.path.join(_base_dir, "app", "static", "frontend")),  # 打包：_MEIPASS/app/static/frontend
)
_frontend_dist_path = next(
    (p for p in _frontend_dist_path_candidates if os.path.isfile(os.path.join(p, "index.html"))),
    None,
)
if _frontend_dist_path:
    print(f"挂载前端静态资源: {_frontend_dist_path}")
    app.mount("/", StaticFiles(directory=_frontend_dist_path, html=True), name="frontend")


@app.exception_handler(StarletteHTTPException)
async def spa_fallback_on_404(request, exc: StarletteHTTPException):
    # 前端路由（如 /license）在静态导出时可能不存在同名文件路径，
    # 对非 API 的 404 做兜底返回 index.html，避免刷新/直达路由 404。
    if exc.status_code == 404 and request.method == "GET":
        path = request.url.path
        accept = (request.headers.get("accept") or "").lower()
        wants_html = "text/html" in accept or "*/*" in accept
        if (
            wants_html
            and _frontend_dist_path
            and (not path.startswith("/api"))
            and (not path.startswith("/storage"))
        ):
            index_path = os.path.join(_frontend_dist_path, "index.html")
            if os.path.isfile(index_path):
                return FileResponse(index_path)
    detail = getattr(exc, "detail", None)
    if detail is None:
        detail = "Not Found" if exc.status_code == 404 else "HTTP Error"
    headers = getattr(exc, "headers", None) or {}
    return JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=headers)
