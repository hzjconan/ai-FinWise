from decimal import Decimal

from app.models.product import Product


def _make_product(db, code: str, risk_level: str | None, expected_return, status="active"):
    p = Product(
        product_code=code,
        name=code,
        type="债券",
        status=status,
        risk_level=risk_level,
        expected_return=expected_return,
    )
    db.add(p)
    return p


def test_hot_products_top_two_per_risk_level(client, db):
    # R1: 3 active → only top 2 returned
    _make_product(db, "R1-A", "R1", Decimal("3.00"))
    _make_product(db, "R1-B", "R1", Decimal("5.00"))
    _make_product(db, "R1-C", "R1", Decimal("4.00"))
    # R2: 1 active
    _make_product(db, "R2-A", "R2", Decimal("6.00"))
    db.commit()

    resp = client.get("/api/v1/products/hot")
    assert resp.status_code == 200
    items = resp.json()["items"]

    r1 = [i for i in items if i["risk_level"] == "R1"]
    assert len(r1) == 2
    # Within-group descending by expected_return
    assert [i["product_code"] for i in r1] == ["R1-B", "R1-C"]

    r2 = [i for i in items if i["risk_level"] == "R2"]
    assert len(r2) == 1


def test_hot_products_excludes_inactive(client, db):
    _make_product(db, "A1", "R3", Decimal("9.00"), status="active")
    _make_product(db, "A2", "R3", Decimal("99.00"), status="draft")
    db.commit()

    resp = client.get("/api/v1/products/hot")
    codes = [i["product_code"] for i in resp.json()["items"]]
    assert "A1" in codes
    assert "A2" not in codes


def test_hot_products_excludes_null_risk_level(client, db):
    _make_product(db, "HAS-RISK", "R3", Decimal("5.00"))
    _make_product(db, "NO-RISK", None, Decimal("99.00"))
    db.commit()

    resp = client.get("/api/v1/products/hot")
    codes = [i["product_code"] for i in resp.json()["items"]]
    assert "HAS-RISK" in codes
    assert "NO-RISK" not in codes


def test_hot_products_empty(client):
    resp = client.get("/api/v1/products/hot")
    assert resp.status_code == 200
    assert resp.json() == {"items": []}
