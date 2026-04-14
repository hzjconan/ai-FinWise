class TestGetActiveQuestions:
    def test_returns_active_only(self, client, sample_questions):
        resp = client.get("/api/v1/assessment/questions")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_empty_when_no_questions(self, client):
        resp = client.get("/api/v1/assessment/questions")
        assert resp.status_code == 200
        assert resp.json() == []


class TestSubmitAssessment:
    def test_submit_success(self, client, customer_code, sample_questions):
        answers = []
        for q in sample_questions:
            # Pick the first option for each question
            answers.append({
                "question_id": q["id"],
                "option_id": q["options"][0]["id"],
            })
        resp = client.post("/api/v1/assessment/submit", json={
            "customer_code": customer_code,
            "answers": answers,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["assessment_code"].startswith("ASM-")
        assert data["source"] == "questionnaire"
        assert data["risk_preference"] in ["C1", "C2", "C3", "C4", "C5"]
        assert data["risk_label"] != ""
        assert data["description"] != ""

    def test_submit_invalid_customer(self, client, sample_questions):
        resp = client.post("/api/v1/assessment/submit", json={
            "customer_code": "CUS-NONEXISTENT",
            "answers": [{"question_id": 1, "option_id": 1}],
        })
        assert resp.status_code == 400

    def test_submit_invalid_option(self, client, customer_code, sample_questions):
        resp = client.post("/api/v1/assessment/submit", json={
            "customer_code": customer_code,
            "answers": [{"question_id": sample_questions[0]["id"], "option_id": 99999}],
        })
        assert resp.status_code == 400

    def test_high_score_gives_aggressive(self, client, customer_code, sample_questions):
        """Picking highest-score options should give C4 or C5."""
        answers = []
        for q in sample_questions:
            max_opt = max(q["options"], key=lambda o: o["score"])
            answers.append({"question_id": q["id"], "option_id": max_opt["id"]})
        resp = client.post("/api/v1/assessment/submit", json={
            "customer_code": customer_code,
            "answers": answers,
        })
        assert resp.json()["risk_preference"] in ["C4", "C5"]

    def test_low_score_gives_conservative(self, client, customer_code, sample_questions):
        """Picking lowest-score options should give C1 or C2."""
        answers = []
        for q in sample_questions:
            min_opt = min(q["options"], key=lambda o: o["score"])
            answers.append({"question_id": q["id"], "option_id": min_opt["id"]})
        resp = client.post("/api/v1/assessment/submit", json={
            "customer_code": customer_code,
            "answers": answers,
        })
        assert resp.json()["risk_preference"] in ["C1", "C2"]
