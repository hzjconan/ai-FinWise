from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.assessment import Assessment
from app.models.customer import Customer
from app.models.favorite import Favorite
from app.models.product import Product
from app.schemas.assessment import AssessmentHistoryItem
from app.schemas.customer import CustomerProductOut, FavoriteCreate
from app.services.risk_calculator import PREFERENCE_LABELS

router = APIRouter()


def _get_customer(db: Session, customer_code: str) -> Customer:
    customer = db.query(Customer).filter(Customer.code == customer_code).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="客户不存在")
    return customer


@router.get("/{customer_code}/favorites", response_model=list[CustomerProductOut])
def list_favorites(customer_code: str, db: Session = Depends(get_db)):
    customer = _get_customer(db, customer_code)
    favorites = (
        db.query(Product)
        .join(Favorite, Favorite.product_id == Product.id)
        .filter(Favorite.customer_id == customer.id)
        .all()
    )
    return [CustomerProductOut.model_validate(p) for p in favorites]


@router.post("/{customer_code}/favorites", status_code=201)
def add_favorite(customer_code: str, data: FavoriteCreate, db: Session = Depends(get_db)):
    customer = _get_customer(db, customer_code)
    product = db.query(Product).filter(Product.product_code == data.product_code).first()
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在")

    existing = db.query(Favorite).filter(
        Favorite.customer_id == customer.id, Favorite.product_id == product.id
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="已收藏")

    db.add(Favorite(customer_id=customer.id, product_id=product.id))
    db.commit()
    return {"ok": True}


@router.delete("/{customer_code}/favorites/{product_code}", status_code=204)
def remove_favorite(customer_code: str, product_code: str, db: Session = Depends(get_db)):
    customer = _get_customer(db, customer_code)
    product = db.query(Product).filter(Product.product_code == product_code).first()
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在")

    fav = db.query(Favorite).filter(
        Favorite.customer_id == customer.id, Favorite.product_id == product.id
    ).first()
    if fav is None:
        raise HTTPException(status_code=404, detail="未收藏")
    db.delete(fav)
    db.commit()


@router.get("/{customer_code}/assessments", response_model=list[AssessmentHistoryItem])
def list_assessments(customer_code: str, db: Session = Depends(get_db)):
    customer = _get_customer(db, customer_code)
    assessments = (
        db.query(Assessment)
        .filter(Assessment.customer_id == customer.id)
        .order_by(Assessment.created_at.desc())
        .all()
    )
    result = []
    for a in assessments:
        result.append(AssessmentHistoryItem(
            code=a.code,
            source=a.source,
            risk_preference=a.risk_preference,
            risk_label=PREFERENCE_LABELS.get(a.risk_preference, "未知"),
            ai_summary=a.ai_summary,
            created_at=a.created_at,
        ))
    return result
