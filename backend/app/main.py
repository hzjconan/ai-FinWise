from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.models import *  # noqa: F401, F403 — ensure all models are registered
from app.routers import admin_products, admin_questions, assessment, auth, customers, products, recommendations
from app.utils.auth import hash_password
from app.config import settings


def seed_default_admin():
    """Create default admin if none exists."""
    from app.database import SessionLocal
    from app.models.admin import Admin

    db = SessionLocal()
    try:
        if db.query(Admin).first() is None:
            admin = Admin(
                username=settings.ADMIN_DEFAULT_USERNAME,
                password_hash=hash_password(settings.ADMIN_DEFAULT_PASSWORD),
            )
            db.add(admin)
            db.commit()
    finally:
        db.close()


def _check_security():
    """Warn or block if running with insecure defaults in production."""
    if settings.ENV != "dev":
        if settings.JWT_SECRET_KEY == "dev-secret-key-change-in-production":
            raise RuntimeError(
                "生产环境禁止使用默认 JWT 密钥，请设置环境变量 FINWISE_JWT_SECRET_KEY"
            )
        if settings.ADMIN_DEFAULT_PASSWORD == "admin123":
            import warnings
            warnings.warn(
                "生产环境建议修改默认管理员密码，设置 FINWISE_ADMIN_DEFAULT_PASSWORD",
                stacklevel=1,
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_security()
    # In dev mode, auto-create tables for convenience.
    # In prod, use: alembic upgrade head
    if settings.ENV == "dev":
        Base.metadata.create_all(bind=engine)
    seed_default_admin()
    yield


app = FastAPI(title="FinWise API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["认证"])
app.include_router(admin_products.router, prefix="/api/v1/admin/products", tags=["管理端-产品"])
app.include_router(admin_questions.router, prefix="/api/v1/admin/questions", tags=["管理端-问卷"])
app.include_router(products.router, prefix="/api/v1/products", tags=["客户端-产品"])
app.include_router(assessment.router, prefix="/api/v1/assessment", tags=["客户端-评估"])
app.include_router(recommendations.router, prefix="/api/v1/recommendations", tags=["客户端-推荐"])
app.include_router(customers.router, prefix="/api/v1/customers", tags=["客户端-客户"])
