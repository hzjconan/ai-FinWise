from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class ReturnHistoryCreate(BaseModel):
    period_label: str
    return_rate: Decimal
    recorded_at: date


class ReturnHistoryOut(BaseModel):
    id: int
    period_label: str
    return_rate: Decimal
    recorded_at: date

    model_config = {"from_attributes": True}


class ProductCreate(BaseModel):
    product_code: str
    name: str
    type: str
    investment_direction: str | None = None
    min_investment: Decimal = Decimal("0")
    investment_period: int | None = None
    description: str | None = None


class ProductUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    investment_direction: str | None = None
    min_investment: Decimal | None = None
    investment_period: int | None = None
    description: str | None = None


class StatusUpdate(BaseModel):
    status: str


class ProductOut(BaseModel):
    product_code: str
    name: str
    type: str
    investment_direction: str | None = None
    min_investment: Decimal
    investment_period: int | None = None
    description: str | None = None
    status: str
    expected_return: Decimal | None = None
    return_stddev: Decimal | None = None
    risk_level: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ProductDetail(ProductOut):
    updated_at: datetime
    return_histories: list[ReturnHistoryOut] = []


class ProductMetrics(BaseModel):
    expected_return: Decimal | None
    return_stddev: Decimal | None
    risk_level: str | None


class ReturnCreateResponse(BaseModel):
    return_history: ReturnHistoryOut
    product_metrics: ProductMetrics


class PaginatedProducts(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ProductOut]
