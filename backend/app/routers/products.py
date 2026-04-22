from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.product import Product
from app.schemas.product import HotProducts, PaginatedProducts, ProductDetail, ProductOut
from app.utils.pagination import paginate

router = APIRouter()


@router.get("", response_model=PaginatedProducts)
def list_active_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    risk_level: str | None = None,
    type: str | None = None,
    sort_by: str = Query("expected_return", pattern="^(expected_return|risk_level)$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    q = db.query(Product).filter(Product.status == "active")
    if risk_level:
        q = q.filter(Product.risk_level == risk_level)
    if type:
        q = q.filter(Product.type == type)

    order_col = getattr(Product, sort_by)
    q = q.order_by(order_col.desc() if sort_order == "desc" else order_col.asc())

    items, total = paginate(q, page, page_size)
    return PaginatedProducts(
        total=total, page=page, page_size=page_size,
        items=[ProductOut.model_validate(p) for p in items],
    )


@router.get("/hot", response_model=HotProducts)
def list_hot_products(db: Session = Depends(get_db)):
    """Return top 2 products per risk_level by expected_return desc, active only."""
    row_number = func.row_number().over(
        partition_by=Product.risk_level,
        order_by=Product.expected_return.desc(),
    ).label("rn")

    subq = (
        db.query(Product, row_number)
        .filter(Product.status == "active", Product.risk_level.isnot(None))
        .subquery()
    )

    product_alias = db.query(Product).join(
        subq, Product.id == subq.c.id
    ).filter(subq.c.rn <= 2).order_by(
        Product.risk_level.asc(), Product.expected_return.desc()
    ).all()

    return HotProducts(items=[ProductOut.model_validate(p) for p in product_alias])


@router.get("/{product_code}", response_model=ProductDetail)
def get_product_detail(product_code: str, db: Session = Depends(get_db)):
    from fastapi import HTTPException

    product = db.query(Product).filter(
        Product.product_code == product_code, Product.status == "active"
    ).first()
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    return ProductDetail.model_validate(product)
