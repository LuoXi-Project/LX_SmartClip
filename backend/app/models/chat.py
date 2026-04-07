from typing import Optional
from pydantic import BaseModel, Field, validator

class ChatMessage(BaseModel):
    role: str = Field(..., description="消息角色: user | assistant | system")
    content: str = Field(..., description="消息内容")


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., description="消息列表")
    stream: Optional[bool] = Field(default=True, description="是否流式输出")

    @validator('messages')
    def validate_messages(cls, v):
        if not isinstance(v, list):
            raise ValueError("消息列表必须为列表")
        if len(v) == 0:
            raise ValueError("消息列表不能为空")
        return v

