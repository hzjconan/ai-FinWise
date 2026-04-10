from sqlalchemy.orm import Session

from app.models.assessment import Assessment, AssessmentAnswer
from app.models.customer import Customer
from app.models.question import Question, QuestionOption
from app.schemas.assessment import AssessmentSubmit
from app.services.risk_calculator import calculate_risk_preference
from app.utils.code_generator import generate_code


def submit_questionnaire(db: Session, data: AssessmentSubmit) -> Assessment:
    customer = db.query(Customer).filter(Customer.code == data.customer_code).first()
    if customer is None:
        raise ValueError("客户不存在")

    # Calculate total score and max possible score
    total_score = 0
    max_possible = 0
    for answer in data.answers:
        option = db.query(QuestionOption).filter(QuestionOption.id == answer.option_id).first()
        if option is None:
            raise ValueError(f"选项 {answer.option_id} 不存在")
        total_score += option.score

        # Get max score for this question
        question = db.query(Question).filter(Question.id == answer.question_id).first()
        if question is None:
            raise ValueError(f"题目 {answer.question_id} 不存在")
        max_score = max(o.score for o in question.options)
        max_possible += max_score

    if max_possible == 0:
        raise ValueError("问卷无有效题目")

    normalized, preference, label, description = calculate_risk_preference(total_score, max_possible)

    code = generate_code(db, Assessment, "ASM")
    assessment = Assessment(
        code=code,
        customer_id=customer.id,
        source="questionnaire",
        total_score=total_score,
        normalized_score=normalized,
        risk_preference=preference,
    )
    db.add(assessment)
    db.flush()

    for answer in data.answers:
        db.add(AssessmentAnswer(
            assessment_id=assessment.id,
            question_id=answer.question_id,
            option_id=answer.option_id,
        ))

    db.commit()
    db.refresh(assessment)
    return assessment
