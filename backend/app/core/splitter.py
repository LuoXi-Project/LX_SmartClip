"""视频切分器 - 支持镜头识别、固定时长与混合切分。"""
from app.core.splitter_base import SplitterBaseMixin
from app.core.splitter_cut import SplitterCutMixin
from app.core.splitter_detect import SplitterDetectMixin
from app.core.splitter_hybrid import SplitterHybridMixin
from app.core.splitter_modes import SplitterModesMixin
from app.core.splitter_types import ClipInfo, SplitProgressFn, StopRequested

class VideoSplitter(
    SplitterBaseMixin,
    SplitterCutMixin,
    SplitterDetectMixin,
    SplitterModesMixin,
    SplitterHybridMixin,
):
    """视频切分器 - 支持镜头识别、固定时长与混合（镜头 + 超长强制切段）切分"""

__all__ = ["VideoSplitter", "ClipInfo", "StopRequested", "SplitProgressFn"]
