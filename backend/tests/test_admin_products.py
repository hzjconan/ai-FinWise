class TestCreateProduct:
    def test_create_success(self, client, auth_header):
        resp = client.post("/api/v1/admin/products", json={
            "product_code": "WY-001",
            "name": "稳健增值1号",
            "type": "债券",
            "min_investment": 10000,
        }, headers=auth_header)
        assert resp.status_code == 201
        data = resp.json()
        assert data["product_code"] == "WY-001"
        assert data["status"] == "draft"

    def test_create_duplicate_code(self, client, auth_header):
        payload = {
            "product_code": "DUP-001",
            "name": "产品A",
            "type": "债券",
            "min_investment": 0,
        }
        client.post("/api/v1/admin/products", json=payload, headers=auth_header)
        resp = client.post("/api/v1/admin/products", json=payload, headers=auth_header)
        assert resp.status_code == 409

    def test_create_missing_required_field(self, client, auth_header):
        resp = client.post("/api/v1/admin/products", json={
            "product_code": "X-001",
        }, headers=auth_header)
        assert resp.status_code == 422


class TestListProducts:
    def test_list_empty(self, client, auth_header):
        resp = client.get("/api/v1/admin/products", headers=auth_header)
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_with_products(self, client, auth_header, sample_product):
        resp = client.get("/api/v1/admin/products", headers=auth_header)
        assert resp.json()["total"] == 1

    def test_filter_by_status(self, client, auth_header, sample_product):
        resp = client.get("/api/v1/admin/products?status=active", headers=auth_header)
        assert resp.json()["total"] == 1
        resp = client.get("/api/v1/admin/products?status=draft", headers=auth_header)
        assert resp.json()["total"] == 0


class TestProductDetail:
    def test_get_detail(self, client, auth_header, sample_product):
        resp = client.get(f"/api/v1/admin/products/{sample_product}", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["product_code"] == "TEST-001"
        assert len(data["return_histories"]) == 4
        assert data["risk_level"] is not None

    def test_get_nonexistent(self, client, auth_header):
        resp = client.get("/api/v1/admin/products/NOPE-999", headers=auth_header)
        assert resp.status_code == 404


class TestUpdateProduct:
    def test_update_name(self, client, auth_header, sample_product):
        resp = client.put(f"/api/v1/admin/products/{sample_product}", json={
            "name": "新名称",
        }, headers=auth_header)
        assert resp.status_code == 200
        assert resp.json()["name"] == "新名称"


class TestProductStatus:
    def test_activate_and_deactivate(self, client, auth_header):
        client.post("/api/v1/admin/products", json={
            "product_code": "ST-001", "name": "状态测试", "type": "股票", "min_investment": 0,
        }, headers=auth_header)
        resp = client.patch("/api/v1/admin/products/ST-001/status",
                            json={"status": "active"}, headers=auth_header)
        assert resp.json()["status"] == "active"
        resp = client.patch("/api/v1/admin/products/ST-001/status",
                            json={"status": "inactive"}, headers=auth_header)
        assert resp.json()["status"] == "inactive"

    def test_invalid_status(self, client, auth_header, sample_product):
        resp = client.patch(f"/api/v1/admin/products/{sample_product}/status",
                            json={"status": "deleted"}, headers=auth_header)
        assert resp.status_code == 400


class TestReturnHistory:
    def test_add_return(self, client, auth_header):
        client.post("/api/v1/admin/products", json={
            "product_code": "RH-001", "name": "收益测试", "type": "混合", "min_investment": 0,
        }, headers=auth_header)
        resp = client.post("/api/v1/admin/products/RH-001/returns", json={
            "period_label": "2024-Q1", "return_rate": 5.5, "recorded_at": "2024-03-31",
        }, headers=auth_header)
        assert resp.status_code == 201
        assert "product_metrics" in resp.json()

    def test_delete_return(self, client, auth_header, sample_product):
        detail = client.get(f"/api/v1/admin/products/{sample_product}",
                            headers=auth_header).json()
        return_id = detail["return_histories"][0]["id"]
        resp = client.delete(
            f"/api/v1/admin/products/{sample_product}/returns/{return_id}",
            headers=auth_header,
        )
        assert resp.status_code == 200

    def test_risk_recalculation(self, client, auth_header):
        client.post("/api/v1/admin/products", json={
            "product_code": "RC-001", "name": "重算测试", "type": "债券", "min_investment": 0,
        }, headers=auth_header)
        client.post("/api/v1/admin/products/RC-001/returns", json={
            "period_label": "Q1", "return_rate": 4.0, "recorded_at": "2024-03-31",
        }, headers=auth_header)
        resp = client.post("/api/v1/admin/products/RC-001/returns", json={
            "period_label": "Q2", "return_rate": 4.5, "recorded_at": "2024-06-30",
        }, headers=auth_header)
        metrics = resp.json()["product_metrics"]
        assert metrics["expected_return"] is not None
        assert metrics["risk_level"] is not None
