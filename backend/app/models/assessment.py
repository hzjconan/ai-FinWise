from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    total_score: Mapped[int | None] = mapped_column()
    normalized_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    risk_preference: Mapped[str] = mapped_column(String(2), nullable=False)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    ai_dimensions: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))

    answers: Mapped[list["AssessmentAnswer"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )


class AssessmentAnswer(Base):
    __tablename__ = "assessment_answers"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    assessment_id: Mapped[int] = mapped_column(ForeignKey("assessments.id"), nullable=False)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), nullable=False)
    option_id: Mapped[int] = mapped_column(ForeignKey("question_options.id"), nullable=False)

    assessment: Mapped["Assessment"] = relationship(back_populates="answers")
