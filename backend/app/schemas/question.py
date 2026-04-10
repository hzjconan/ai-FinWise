from datetime import datetime

from pydantic import BaseModel


class OptionCreate(BaseModel):
    content: str
    score: int


class OptionOut(BaseModel):
    id: int
    content: str
    score: int

    model_config = {"from_attributes": True}


class QuestionCreate(BaseModel):
    content: str
    sort_order: int = 0
    options: list[OptionCreate]


class QuestionUpdate(BaseModel):
    content: str
    sort_order: int = 0
    options: list[OptionCreate]


class QuestionOut(BaseModel):
    id: int
    content: str
    sort_order: int
    is_active: bool
    options: list[OptionOut] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class SortOrderItem(BaseModel):
    id: int
    sort_order: int


class SortOrderRequest(BaseModel):
    orders: list[SortOrderItem]
