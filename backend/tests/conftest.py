import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.utils.auth import create_access_token, hash_password

# In-memory SQLite for tests
TEST_DATABASE_URL = "sqlite://"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    """Create all tables before each test, drop after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def admin_token():
    """Create an admin and return a valid JWT token."""
    from app.models.admin import Admin

    db = TestingSessionLocal()
    admin = Admin(username="testadmin", password_hash=hash_password("testpass"))
    db.add(admin)
    db.commit()
    db.close()
    return create_access_token({"sub": "testadmin", "role": "admin"})


@pytest.fixture
def auth_header(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture
def customer_code(client):
    """Create an anonymous customer and return the code."""
    resp = client.post("/api/v1/auth/customer/anonymous")
    return resp.json()["customer_code"]


@pytest.fixture
def sample_product(client, auth_header):
    """Create a sample product with return histories."""
    resp = client.post("/api/v1/admin/products", json={
        "product_code": "TEST-001",
        "name": "测试产品1号",
        "type": "债券",
        "investment_direction": "国债",
        "min_investment": 10000,
        "investment_period": 365,
        "description": "测试用产品",
    }, headers=auth_header)
    assert resp.status_code == 201

    # Add return histories
    for label, rate, date in [
        ("2024-Q1", 4.10, "2024-03-31"),
        ("2024-Q2", 4.35, "2024-06-30"),
        ("2024-Q3", 4.50, "2024-09-30"),
        ("2024-Q4", 4.25, "2024-12-31"),
    ]:
        client.post(f"/api/v1/admin/products/TEST-001/returns", json={
            "period_label": label, "return_rate": rate, "recorded_at": date,
        }, headers=auth_header)

    # Activate
    client.patch("/api/v1/admin/products/TEST-001/status",
                 json={"status": "active"}, headers=auth_header)

    return "TEST-001"


@pytest.fixture
def sample_questions(client, auth_header):
    """Create sample assessment questions."""
    questions = [
        {
            "content": "您的年龄段是？",
            "sort_order": 1,
            "options": [
                {"content": "25岁以下", "score": 5},
                {"content": "25-35岁", "score": 4},
                {"content": "35-50岁", "score": 3},
                {"content": "50-60岁", "score": 2},
                {"content": "60岁以上", "score": 1},
            ],
        },
        {
            "content": "您的投资经验？",
            "sort_order": 2,
            "options": [
                {"content": "无经验", "score": 1},
                {"content": "1-3年", "score": 3},
                {"content": "3年以上", "score": 5},
            ],
        },
    ]
    created = []
    for q in questions:
        resp = client.post("/api/v1/admin/questions", json=q, headers=auth_header)
        assert resp.status_code == 201
        created.append(resp.json())
    return created
