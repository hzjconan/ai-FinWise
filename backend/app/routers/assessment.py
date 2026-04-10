from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.question import Question
from app.schemas.assessment import AssessmentResult, AssessmentSubmit
from app.schemas.question import QuestionOut
from app.services.assessment_service import submit_questionnaire
from app.services.risk_calculator import PREFERENCE_DESCRIPTIONS, PREFERENCE_LABELS

router = APIRouter()


@router.get("/questions", response_model=list[QuestionOut])
def get_active_questions(db: Session = Depends(get_db)):
    questions = (
        db.query(Question)
        .filter(Question.is_active == True)
        .order_by(Question.sort_order)
        .all()
    )
    return [QuestionOut.model_validate(q) for q in questions]


@router.post("/submit", response_model=AssessmentResult)
def submit_assessment(data: AssessmentSubmit, db: Session = Depends(get_db)):
    try:
        assessment = submit_questionnaire(db, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return AssessmentResult(
        assessment_code=assessment.code,
        source=assessment.source,
        total_score=assessment.total_score,
        normalized_score=assessment.normalized_score,
        risk_preference=assessment.risk_preference,
        risk_label=PREFERENCE_LABELS.get(assessment.risk_preference, "未知"),
        description=PREFERENCE_DESCRIPTIONS.get(assessment.risk_preference, ""),
    )
