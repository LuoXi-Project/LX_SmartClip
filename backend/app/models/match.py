from typing import List, Optional
from pydantic import BaseModel, Field


class MatchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="用户文案")
    top_k: Optional[int] = Field(None, ge=1, le=50, description="向量初筛数量（可选）")
    top_n: Optional[int] = Field(None, ge=1, le=20, description="最终推荐数量（可选）")
    video_ids: Optional[List[str]] = Field(None, description="限定视频 ID 列表")
    match_mode: Optional[str] = Field(
        None,
        description="单次匹配模式覆盖（auto/vector/text/llm_only）；不传则用全局 match_mode 配置",
    )


class ClipResult(BaseModel):
    clip_id: str
    video_id: str
    clip_path: str
    start_time: float
    end_time: float
    duration: float
    asr_text: Optional[str] = None
    vlm_description: Optional[str] = None
    abstract_summary: Optional[str] = None
    keywords: Optional[List[str]] = None
    emotion_tags: Optional[List[str]] = None
    thumbnail_url: Optional[str] = None
    preview_url: Optional[str] = None
    score: float
    reason: str


class MatchResponse(BaseModel):
    query: str
    top_n: int
    recommended: List[ClipResult]
    candidates: List[ClipResult]


class MatchPipelineError(Exception):
    """在线程池中执行匹配 pipeline 时使用的 HTTP 语义错误（避免在 worker 内抛 HTTPException）。"""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail

