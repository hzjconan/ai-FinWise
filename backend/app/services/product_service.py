from sqlalchemy.orm import Session

from app.models.product import Product, ReturnHistory
from app.services.risk_calculator import calculate_product_risk


def recalculate_risk(db: Session, product: Product) -> None:
    """Recalculate product risk metrics based on return histories."""
    rates = [rh.return_rate for rh in product.return_histories]
    expected, stddev, level = calculate_product_risk(rates)
    product.expected_return = expected
    product.return_stddev = stddev
    product.risk_level = level
    db.flush()
