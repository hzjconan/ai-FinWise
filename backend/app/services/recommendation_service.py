from sqlalchemy.orm import Session

from app.models.assessment import Assessment
from app.models.customer import Customer
from app.models.product import Product
from app.schemas.recommendation import RecommendationResponse, RecommendedProduct
from app.services.risk_calculator import MATCH_RULES, PREFERENCE_LABELS


def get_recommendations(db: Session, customer_code: str) -> RecommendationResponse:
    customer = db.query(Customer).filter(Customer.code == customer_code).first()
    if customer is None:
        raise ValueError("客户不存在")

    latest = (
        db.query(Assessment)
        .filter(Assessment.customer_id == customer.id)
        .order_by(Assessment.created_at.desc())
        .first()
    )
    if latest is None:
        raise ValueError("客户未完成风险评估")

    pref = latest.risk_preference
    rules = MATCH_RULES.get(pref, MATCH_RULES["C3"])

    exact_levels = rules["exact"]
    conservative_levels = rules["conservative"]
    aggressive_levels = rules["aggressive"]

    exact_products = (
        db.query(Product)
        .filter(Product.status == "active", Product.risk_level.in_(exact_levels))
        .order_by(Product.expected_return.desc())
        .all()
    )
    conservative_products = (
        db.query(Product)
        .filter(Product.status == "active", Product.risk_level.in_(conservative_levels))
        .order_by(Product.expected_return.desc())
        .all()
    ) if conservative_levels else []
    aggressive_products = (
        db.query(Product)
        .filter(Product.status == "active", Product.risk_level.in_(aggressive_levels))
        .order_by(Product.expected_return.desc())
        .all()
    ) if aggressive_levels else []

    def to_rec(p: Product, match_type: str) -> RecommendedProduct:
        return RecommendedProduct(
            product_code=p.product_code,
            name=p.name,
            type=p.type,
            expected_return=p.expected_return,
            risk_level=p.risk_level,
            match_type=match_type,
        )

    return RecommendationResponse(
        risk_preference=pref,
        risk_label=PREFERENCE_LABELS.get(pref, "未知"),
        exact_matches=[to_rec(p, "exact") for p in exact_products],
        adjacent_matches=(
            [to_rec(p, "conservative") for p in conservative_products]
            + [to_rec(p, "aggressive") for p in aggressive_products]
        ),
    )
