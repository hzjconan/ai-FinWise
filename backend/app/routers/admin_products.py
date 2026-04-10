from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.admin import Admin
from app.models.product import Product, ReturnHistory
from app.schemas.product import (
    PaginatedProducts,
    ProductCreate,
    ProductDetail,
    ProductMetrics,
    ProductOut,
    ProductUpdate,
    ReturnCreateResponse,
    ReturnHistoryCreate,
    ReturnHistoryOut,
    StatusUpdate,
)
from app.services.product_service import recalculate_risk
from app.utils.auth import get_current_admin
from app.utils.pagination import paginate

router = APIRouter()


@router.get("", response_model=PaginatedProducts)
def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    risk_level: str | None = None,
    type: str | None = None,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    q = db.query(Product)
    if status_filter:
        q = q.filter(Product.status == status_filter)
    if risk_level:
        q = q.filter(Product.risk_level == risk_level)
    if type:
        q = q.filter(Product.type == type)
    q = q.order_by(Product.created_at.desc())
    items, total = paginate(q, page, page_size)
    return PaginatedProducts(
        total=total, page=page, page_size=page_size,
        items=[ProductOut.model_validate(p) for p in items],
    )


@router.post("", response_model=ProductOut, status_code=201)
def create_product(
    data: ProductCreate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
):
    if db.query(Product).filter(Product.product_code == data.product_code).first():
        raise HTTPException(status_code=409, detail="产品编号已存在")
    product = Product(**data.model_dump(), created_by=admin.id)
    db.add(product)
    db.commit()
    db.refresh(product)
    return ProductOut.model_validate(product)


@router.get("/{product_code}", response_model=ProductDetail)
def get_product(
    product_code: str,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    product = db.query(Product).filter(Product.product_code == product_code).first()
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    return ProductDetail.model_validate(product)


@router.put("/{product_code}", response_model=ProductOut)
def update_product(
    product_code: str,
    data: ProductUpdate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    product = db.query(Product).filter(Product.product_code == product_code).first()
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return ProductOut.model_validate(product)


@router.patch("/{product_code}/status", response_model=ProductOut)
def update_product_status(
    product_code: str,
    data: StatusUpdate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    product = db.query(Product).filter(Product.product_code == product_code).first()
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    if data.status not in ("draft", "active", "inactive"):
        raise HTTPException(status_code=400, detail="无效状态")
    product.status = data.status
    db.commit()
    db.refresh(product)
    return ProductOut.model_validate(product)


@router.post("/{product_code}/returns", response_model=ReturnCreateResponse, status_code=201)
def add_return_history(
    product_code: str,
    data: ReturnHistoryCreate,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    product = db.query(Product).filter(Product.product_code == product_code).first()
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在")

    rh = ReturnHistory(product_id=product.id, **data.model_dump())
    db.add(rh)
    db.flush()
    recalculate_risk(db, product)
    db.commit()
    db.refresh(rh)
    db.refresh(product)
    return ReturnCreateResponse(
        return_history=ReturnHistoryOut.model_validate(rh),
        product_metrics=ProductMetrics(
            expected_return=product.expected_return,
            return_stddev=product.return_stddev,
            risk_level=product.risk_level,
        ),
    )


@router.delete("/{product_code}/returns/{return_id}", response_model=ProductMetrics)
def delete_return_history(
    product_code: str,
    return_id: int,
    db: Session = Depends(get_db),
    _admin: Admin = Depends(get_current_admin),
):
    product = db.query(Product).filter(Product.product_code == product_code).first()
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在")

    rh = db.query(ReturnHistory).filter(
        ReturnHistory.id == return_id, ReturnHistory.product_id == product.id
    ).first()
    if rh is None:
        raise HTTPException(status_code=404, detail="收益记录不存在")

    db.delete(rh)
    db.flush()
    recalculate_risk(db, product)
    db.commit()
    db.refresh(product)
    return ProductMetrics(
        expected_return=product.expected_return,
        return_stddev=product.return_stddev,
        risk_level=product.risk_level,
    )
