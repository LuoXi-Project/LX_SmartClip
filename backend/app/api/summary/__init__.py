"""视频总结 API 子包：对外仍通过 `from app.api.summary import router` 挂载。"""

from .routes import router

__all__ = ["router"]
