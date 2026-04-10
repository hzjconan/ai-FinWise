from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    investment_direction: Mapped[str | None] = mapped_column(Text)
    min_investment: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    investment_period: Mapped[int | None] = mapped_column()
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft")
    expected_return: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    return_stddev: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    risk_level: Mapped[str | None] = mapped_column(String(2))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("admins.id"))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    return_histories: Mapped[list["ReturnHistory"]] = relationship(
        back_populates="product", cascade="all, delete-orphan", order_by="ReturnHistory.recorded_at"
    )


class ReturnHistory(Base):
    __tablename__ = "return_histories"
    __table_args__ = (UniqueConstraint("product_id", "recorded_at", name="uq_product_recorded"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    period_label: Mapped[str] = mapped_column(String(20), nullable=False)
    return_rate: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    recorded_at: Mapped[date] = mapped_column(nullable=False)

    product: Mapped["Product"] = relationship(back_populates="return_histories")
