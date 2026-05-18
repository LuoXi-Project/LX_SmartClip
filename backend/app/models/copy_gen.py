from typing import List, Optional
from pydantic import BaseModel, Field

class CopyGenRequest(BaseModel):
    video_ids: List[str] = Field(..., description="选中视频 ID 列表")
    user_prompt: str = Field(..., min_length=1, description="用户诉求 / 模板指令")
    style: Optional[str] = Field(None, description="风格提示，如 '活泼' '专业' '悬疮'")
    max_segments: int = Field(5, ge=1, le=1000, description="期望拆分段落数")
    stream: bool = Field(True, description="是否流式输出")

