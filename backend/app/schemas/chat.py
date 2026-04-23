from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChatStartRequest(BaseModel):
    customer_code: str


class ChatMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role: str
    content: str
    created_at: datetime


class ChatStartResponse(BaseModel):
    session_code: str
    resumed: bool
    messages: list[ChatMessageOut]
