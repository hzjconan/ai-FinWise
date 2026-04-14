class TestRecommendations:
    def _do_assessment(self, client, customer_code, sample_questions, pick="max"):
        """Helper: complete assessment picking max or min score options."""
        answers = []
        for q in sample_questions:
            if pick == "max":
                opt = max(q["options"], key=lambda o: o["score"])
            else:
                opt = min(q["options"], key=lambda o: o["score"])
            answers.append({"question_id": q["id"], "option_id": opt["id"]})
        client.post("/api/v1/assessment/submit", json={
            "customer_code": customer_code,
            "answers": answers,
        })

    def test_recommendations_after_assessment(
        self, client, customer_code, sample_questions, sample_product
    ):
        self._do_assessment(client, customer_code, sample_questions)
        resp = client.get("/api/v1/recommendations",
                          params={"customer_code": customer_code})
        assert resp.status_code == 200
        data = resp.json()
        assert data["risk_preference"] in ["C1", "C2", "C3", "C4", "C5"]
        assert data["risk_label"] != ""

    def test_no_assessment_returns_404(self, client, customer_code):
        resp = client.get("/api/v1/recommendations",
                          params={"customer_code": customer_code})
        assert resp.status_code == 404

    def test_nonexistent_customer_returns_404(self, client):
        resp = client.get("/api/v1/recommendations",
                          params={"customer_code": "CUS-NOPE"})
        assert resp.status_code == 404

    def test_exact_and_adjacent_matches(
        self, client, auth_header, customer_code, sample_questions
    ):
        """Create products at multiple risk levels, verify matching."""
        # Create products at R1 (low stddev) and R3 (medium stddev)
        for code, rates in [
            ("LOW-001", [(1.0, "2024-03-31"), (1.01, "2024-06-30"), (0.99, "2024-09-30")]),
            ("MED-001", [(3.0, "2024-03-31"), (8.0, "2024-06-30"), (5.0, "2024-09-30")]),
        ]:
            client.post("/api/v1/admin/products", json={
                "product_code": code, "name": f"产品{code}", "type": "混合", "min_investment": 0,
            }, headers=auth_header)
            for rate, date in rates:
                client.post(f"/api/v1/admin/products/{code}/returns", json={
                    "period_label": date[:7], "return_rate": rate, "recorded_at": date,
                }, headers=auth_header)
            client.patch(f"/api/v1/admin/products/{code}/status",
                         json={"status": "active"}, headers=auth_header)

        # Low score → conservative preference → should match low-risk products
        self._do_assessment(client, customer_code, sample_questions, pick="min")
        resp = client.get("/api/v1/recommendations",
                          params={"customer_code": customer_code})
        data = resp.json()
        all_codes = (
            [p["product_code"] for p in data["exact_matches"]]
            + [p["product_code"] for p in data["adjacent_matches"]]
        )
        # Should have some results
        assert len(all_codes) > 0
