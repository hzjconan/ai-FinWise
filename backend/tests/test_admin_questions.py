class TestCreateQuestion:
    def test_create_with_options(self, client, auth_header):
        resp = client.post("/api/v1/admin/questions", json={
            "content": "测试题目",
            "sort_order": 1,
            "options": [
                {"content": "选项A", "score": 1},
                {"content": "选项B", "score": 3},
            ],
        }, headers=auth_header)
        assert resp.status_code == 201
        data = resp.json()
        assert data["content"] == "测试题目"
        assert len(data["options"]) == 2

    def test_create_missing_content(self, client, auth_header):
        resp = client.post("/api/v1/admin/questions", json={
            "sort_order": 1,
            "options": [{"content": "A", "score": 1}],
        }, headers=auth_header)
        assert resp.status_code == 422


class TestListQuestions:
    def test_list_ordered(self, client, auth_header, sample_questions):
        resp = client.get("/api/v1/admin/questions", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["sort_order"] <= data[1]["sort_order"]


class TestUpdateQuestion:
    def test_update_replaces_options(self, client, auth_header, sample_questions):
        qid = sample_questions[0]["id"]
        resp = client.put(f"/api/v1/admin/questions/{qid}", json={
            "content": "更新后的题目",
            "sort_order": 1,
            "options": [
                {"content": "新选项A", "score": 2},
                {"content": "新选项B", "score": 4},
                {"content": "新选项C", "score": 5},
            ],
        }, headers=auth_header)
        assert resp.status_code == 200
        assert resp.json()["content"] == "更新后的题目"
        assert len(resp.json()["options"]) == 3

    def test_update_nonexistent(self, client, auth_header):
        resp = client.put("/api/v1/admin/questions/9999", json={
            "content": "X", "sort_order": 1, "options": [{"content": "A", "score": 1}],
        }, headers=auth_header)
        assert resp.status_code == 404


class TestDeleteQuestion:
    def test_delete_success(self, client, auth_header, sample_questions):
        qid = sample_questions[0]["id"]
        resp = client.delete(f"/api/v1/admin/questions/{qid}", headers=auth_header)
        assert resp.status_code == 204
        # Verify deleted
        listing = client.get("/api/v1/admin/questions", headers=auth_header).json()
        assert len(listing) == 1

    def test_delete_nonexistent(self, client, auth_header):
        resp = client.delete("/api/v1/admin/questions/9999", headers=auth_header)
        assert resp.status_code == 404
