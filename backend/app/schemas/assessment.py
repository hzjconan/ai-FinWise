from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class AnswerItem(BaseModel):
    question_id: int
    option_id: int


class AssessmentSubmit(BaseModel):
    customer_code: str
    answers: list[AnswerItem]


class AssessmentResult(BaseModel):
    assessment_code: str
    source: str
    total_score: int | None = None
    normalized_score: Decimal | None = None
    risk_preference: str
    risk_label: str
    description: str


class AssessmentHistoryItem(BaseModel):
    code: str
    source: str
    risk_preference: str
    risk_label: str
    ai_summary: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
