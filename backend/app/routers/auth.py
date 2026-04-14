from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.admin import Admin
from app.models.customer import Customer
from app.schemas.auth import AnonymousResponse, LoginRequest, TokenResponse
from app.utils.auth import create_access_token, verify_password
from app.utils.code_generator import generate_code

router = APIRouter()


@router.post("/admin/login", response_model=TokenResponse)
def admin_login(data: LoginRequest, db: Session = Depends(get_db)):
    admin = db.query(Admin).filter(Admin.username == data.username).first()
    if admin is None or not verify_password(data.password, admin.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    token = create_access_token({"sub": admin.username, "role": "admin"})
    return TokenResponse(
        access_token=token,
        expires_in=settings.JWT_EXPIRE_HOURS * 3600,
    )


@router.post("/customer/anonymous", response_model=AnonymousResponse, status_code=201)
def create_anonymous_customer(db: Session = Depends(get_db)):
    for _ in range(3):
        code = generate_code(db, Customer, "CUS")
        customer = Customer(code=code)
        db.add(customer)
        try:
            db.commit()
            return AnonymousResponse(customer_code=code)
        except IntegrityError:
            db.rollback()
    raise HTTPException(status_code=500, detail="无法生成唯一客户编号")
