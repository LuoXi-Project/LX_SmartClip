from typing import List, Optional
from pydantic import BaseModel, Field

# 向量检索可指定的子空间（与 IVectorDB.SUBSPACES 对齐）
# asr=台词+关键词 / vlm=画面 / abstract=摘要+情绪 / legacy=旧混合向量
VALID_SUBSPACES = frozenset({"asr", "vlm", "abstract", "legacy"})


class MatchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="用户文案")
    top_k: Optional[int] = Field(None, ge=1, le=50, description="向量初筛数量（可选）")
    top_n: Optional[int] = Field(None, ge=1, le=20, description="最终推荐数量（可选）")
    video_ids: Optional[List[str]] = Field(None, description="限定视频 ID 列表")
    match_mode: Optional[str] = Field(
        None,
        description="单次匹配模式覆盖（auto/vector/text/llm_only）；不传则用全局 match_mode 配置",
    )
    refine: Optional[bool] = Field(
        None,
        description="LLM 精排控制：True=强制启用 LLM 精排；False=跳过 LLM 精排（仅用初筛排序）；None=沿用默认行为",
    )
    subspaces: Optional[List[str]] = Field(
        None,
        description="向量检索限定的子空间（仅 vector 模式生效）；不传=自动选择所有有数据的子空间。",
    )
    visual_intent: Optional[bool] = Field(
        None,
        description="检索前把文案改写为画面意图（None=跟随全局配置 match_visual_intent，默认开）",
    )
    visual_verify: Optional[bool] = Field(
        None,
        description="匹配后用 VLM 看候选帧打相关度分并重排（None=跟随全局配置 match_visual_verify，默认关）",
    )
    vlm_verify_top_n: Optional[int] = Field(
        None, ge=1, le=5, description="参与 VLM 画面校验的推荐候选数（默认 3）"
    )
    penalize_clip_ids: Optional[List[str]] = Field(
        None,
        description="需降权的片段 ID（如整篇文案中前文已选用的片段），用于跨段去重",
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
    vlm_score: Optional[float] = Field(None, description="VLM 画面相关度 0~10（未校验时为空）")
    vlm_reason: Optional[str] = Field(None, description="VLM 画面相关度理由")


class MatchResponse(BaseModel):
    query: str
    top_n: int
    recommended: List[ClipResult]
    candidates: List[ClipResult]
    visual_intent_query: Optional[str] = Field(
        None, description="实际用于检索的画面意图改写（未启用/失败时为空）"
    )
    visual_verify_applied: bool = Field(False, description="本次是否实际执行了 VLM 画面校验")


class MatchBatchRequest(BaseModel):
    """整篇多段文案一次性匹配：跨段共享画面意图改写与已选用片段降权。"""

    segments: List[str] = Field(..., min_length=1, max_length=200, description="旁白分段列表")
    top_k: Optional[int] = Field(None, ge=1, le=50)
    top_n: Optional[int] = Field(None, ge=1, le=20)
    video_ids: Optional[List[str]] = None
    match_mode: Optional[str] = None
    refine: Optional[bool] = None
    subspaces: Optional[List[str]] = None
    visual_intent: Optional[bool] = None
    visual_verify: Optional[bool] = None
    vlm_verify_top_n: Optional[int] = Field(None, ge=1, le=5)


class MatchBatchItem(BaseModel):
    query: str
    visual_intent_query: Optional[str] = None
    recommended: List[ClipResult]
    candidates: List[ClipResult]


class MatchBatchResponse(BaseModel):
    items: List[MatchBatchItem]


class MatchPipelineError(Exception):
    """在线程池中执行匹配 pipeline 时使用的 HTTP 语义错误（避免在 worker 内抛 HTTPException）。"""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail

