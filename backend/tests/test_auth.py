class TestAdminLogin:
    def test_login_success(self, client, admin_token):
        # admin_token fixture already created the admin user
        resp = client.post("/api/v1/auth/admin/login", json={
            "username": "testadmin",
            "password": "testpass",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] > 0

    def test_login_wrong_password(self, client, admin_token):
        resp = client.post("/api/v1/auth/admin/login", json={
            "username": "testadmin",
            "password": "wrongpass",
        })
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        resp = client.post("/api/v1/auth/admin/login", json={
            "username": "nobody",
            "password": "whatever",
        })
        assert resp.status_code == 401


class TestAnonymousCustomer:
    def test_create_anonymous(self, client):
        resp = client.post("/api/v1/auth/customer/anonymous")
        assert resp.status_code == 201
        data = resp.json()
        assert data["customer_code"].startswith("CUS-")
        assert data["is_registered"] is False

    def test_unique_codes(self, client):
        codes = set()
        for _ in range(5):
            resp = client.post("/api/v1/auth/customer/anonymous")
            codes.add(resp.json()["customer_code"])
        assert len(codes) == 5


class TestAuthProtection:
    def test_admin_endpoint_without_token(self, client):
        resp = client.get("/api/v1/admin/products")
        assert resp.status_code == 401

    def test_admin_endpoint_with_invalid_token(self, client):
        resp = client.get("/api/v1/admin/products",
                          headers={"Authorization": "Bearer invalidtoken"})
        assert resp.status_code == 401
