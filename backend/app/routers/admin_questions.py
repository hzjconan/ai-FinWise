from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admin import Admin
from app.models.question import Question, QuestionOption
from app.schemas.question import QuestionCreate, QuestionOut, QuestionUpdate, SortOrderRequest
from app.utils.auth import get_current_admin

router = APIRouter()


@router.get("", response_model=list[QuestionOut])
def list_questions(
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    questions = db.query(Question).order_by(Question.sort_order).all()
    return [QuestionOut.model_validate(q) for q in questions]


@router.post("", response_model=QuestionOut, status_code=201)
def create_question(
    data: QuestionCreate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    question = Question(content=data.content, sort_order=data.sort_order)
    db.add(question)
    db.flush()
    for opt in data.options:
        db.add(QuestionOption(question_id=question.id, content=opt.content, score=opt.score))
    db.commit()
    db.refresh(question)
    return QuestionOut.model_validate(question)


@router.put("/{question_id}", response_model=QuestionOut)
def update_question(
    question_id: int,
    data: QuestionUpdate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    question = db.query(Question).filter(Question.id == question_id).first()
    if question is None:
        raise HTTPException(status_code=404, detail="题目不存在")

    question.content = data.content
    question.sort_order = data.sort_order

    # Replace options
    db.query(QuestionOption).filter(QuestionOption.question_id == question.id).delete()
    for opt in data.options:
        db.add(QuestionOption(question_id=question.id, content=opt.content, score=opt.score))

    db.commit()
    db.refresh(question)
    return QuestionOut.model_validate(question)


@router.delete("/{question_id}", status_code=204)
def delete_question(
    question_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    question = db.query(Question).filter(Question.id == question_id).first()
    if question is None:
        raise HTTPException(status_code=404, detail="题目不存在")
    db.delete(question)
    db.commit()


@router.put("/sort", status_code=200)
def update_sort_order(
    data: SortOrderRequest,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    for item in data.orders:
        q = db.query(Question).filter(Question.id == item.id).first()
        if q:
            q.sort_order = item.sort_order
    db.commit()
    return {"ok": True}
