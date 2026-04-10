from decimal import Decimal

from pydantic import BaseModel


class RecommendedProduct(BaseModel):
    product_code: str
    name: str
    type: str
    expected_return: Decimal | None = None
    risk_level: str | None = None
    match_type: str  # exact / conservative / aggressive


class RecommendationResponse(BaseModel):
    risk_preference: str
    risk_label: str
    exact_matches: list[RecommendedProduct] = []
    adjacent_matches: list[RecommendedProduct] = []
