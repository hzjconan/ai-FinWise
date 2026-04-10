from pydantic import BaseModel


class FavoriteCreate(BaseModel):
    product_code: str


class CustomerProductOut(BaseModel):
    product_code: str
    name: str
    type: str
    expected_return: float | None = None
    risk_level: str | None = None

    model_config = {"from_attributes": True}
