import argparse
import os
import logging
import socket
import sys
from pathlib import Path


def _repo_backend_root() -> Path:
    # This file lives in backend/; ensure imports like "app.main" work no matter where we run from.
    return Path(__file__).resolve().parent


def find_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(s.getsockname()[1])


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Start LX SmartClip backend on a free port.")
    p.add_argument("--host", default=os.environ.get("LX_BACKEND_HOST", "127.0.0.1"))
    p.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("LX_BACKEND_PORT", "0")),
        help="Preferred port. Use 0 to auto-select a free port (default).",
    )
    p.add_argument(
        "--reload",
        action="store_true",
        default=os.environ.get("LX_BACKEND_RELOAD", "").lower() in {"1", "true", "yes"},
    )
    p.add_argument(
        "--write-url",
        default=os.environ.get("LX_BACKEND_URL_FILE", ""),
        help="Optional file path to write the chosen base URL into.",
    )
    return p.parse_args()

def main() -> None:
    args = parse_args()

    backend_root = _repo_backend_root()
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    # 打包内置 FFmpeg：在导入 MoviePy / imageio 之前设置 IMAGEIO_FFMPEG_EXE 等
    from app.utils.bin_paths import apply_default_ffmpeg_environment

    apply_default_ffmpeg_environment()

    host = args.host
    port = args.port if args.port != 0 else find_free_port(host)

    base_url = f"http://{host}:{port}"
    print(base_url, flush=True)

    if args.write_url:
        Path(args.write_url).parent.mkdir(parents=True, exist_ok=True)
        Path(args.write_url).write_text(base_url, encoding="utf-8")

    # Ensure app logs are colored too (before importing `app.main`).
    from app.utils.logging_utils import build_uvicorn_log_config, setup_logging

    setup_logging(level=logging.INFO)

    # 自动打开浏览器
    import webbrowser
    webbrowser.open(base_url)

    import uvicorn
    # Import app directly so Nuitka can see the dependency graph.
    from app.main import app as asgi_app

    uvicorn.run(
        asgi_app,
        host=host,
        port=port,
        reload=bool(args.reload),
        log_level="info",
        log_config=build_uvicorn_log_config(level="INFO"),
    )


if __name__ == "__main__":
    # PyInstaller + Windows spawn：子进程会带 --multiprocessing-fork 重启本 exe，
    # 须在此处理后再 parse_args，否则会 argparse 报错且抽帧/ASR 等子进程 exit=2。
    import multiprocessing

    multiprocessing.freeze_support()
    main()

