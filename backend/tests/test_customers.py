class TestFavorites:
    def test_add_and_list(self, client, customer_code, sample_product):
        resp = client.post(f"/api/v1/customers/{customer_code}/favorites", json={
            "product_code": sample_product,
        })
        assert resp.status_code == 201

        resp = client.get(f"/api/v1/customers/{customer_code}/favorites")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["product_code"] == sample_product

    def test_add_duplicate(self, client, customer_code, sample_product):
        client.post(f"/api/v1/customers/{customer_code}/favorites", json={
            "product_code": sample_product,
        })
        resp = client.post(f"/api/v1/customers/{customer_code}/favorites", json={
            "product_code": sample_product,
        })
        assert resp.status_code == 409

    def test_remove_favorite(self, client, customer_code, sample_product):
        client.post(f"/api/v1/customers/{customer_code}/favorites", json={
            "product_code": sample_product,
        })
        resp = client.delete(
            f"/api/v1/customers/{customer_code}/favorites/{sample_product}"
        )
        assert resp.status_code == 204

        resp = client.get(f"/api/v1/customers/{customer_code}/favorites")
        assert resp.json() == []

    def test_remove_not_favorited(self, client, customer_code, sample_product):
        resp = client.delete(
            f"/api/v1/customers/{customer_code}/favorites/{sample_product}"
        )
        assert resp.status_code == 404

    def test_nonexistent_customer(self, client, sample_product):
        resp = client.get("/api/v1/customers/CUS-NOPE/favorites")
        assert resp.status_code == 404

    def test_nonexistent_product(self, client, customer_code):
        resp = client.post(f"/api/v1/customers/{customer_code}/favorites", json={
            "product_code": "NOPE-999",
        })
        assert resp.status_code == 404


class TestAssessmentHistory:
    def test_empty_history(self, client, customer_code):
        resp = client.get(f"/api/v1/customers/{customer_code}/assessments")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_history_after_assessment(
        self, client, customer_code, sample_questions
    ):
        # Do an assessment
        answers = []
        for q in sample_questions:
            answers.append({
                "question_id": q["id"],
                "option_id": q["options"][0]["id"],
            })
        client.post("/api/v1/assessment/submit", json={
            "customer_code": customer_code,
            "answers": answers,
        })

        resp = client.get(f"/api/v1/customers/{customer_code}/assessments")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["source"] == "questionnaire"
        assert data[0]["code"].startswith("ASM-")
