"""AI 对话评估 SSE 路由集成测试。

通过 dependency_overrides 注入 MockLLMClient，避免真实 LLM。
"""
import json

import pytest

from app.main import app
from app.models.assessment import Assessment
from app.models.chat import ChatSession
from app.services import chat_service
from app.services.llm.events import LLMError, TextDelta, ToolResult
from app.services.llm.factory import get_llm_client
from app.services.llm.mock import MockLLMClient


# ---------- helpers ----------

def _ask(content: str) -> list:
    return [
        TextDelta(text=content),
        ToolResult(name=chat_service.TOOL_ASK, input={"content": content}),
    ]


def _conclude(pref: str = "C3") -> list:
    return [
        ToolResult(
            name=chat_service.TOOL_CONCLUDE,
            input={
                "content": "感谢您的耐心",
                "risk_preference": pref,
                "summary": "基于对话评估",
                "dimensions": {
                    "experience": 3,
                    "loss_tolerance": 3,
                    "income_stability": 3,
                    "investment_horizon": 3,
                    "volatility_tolerance": 3,
                },
            },
        ),
    ]


@pytest.fixture
def mock_llm():
    client = MockLLMClient()
    app.dependency_overrides[get_llm_client] = lambda: client
    yield client
    app.dependency_overrides.pop(get_llm_client, None)


def _parse_sse(text: str) -> list[dict]:
    """Parse SSE body into list of {event, data} dicts."""
    events: list[dict] = []
    for block in text.strip().split("\n\n"):
        if not block:
            continue
        event_name = None
        data_line = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_name = line[len("event: "):]
            elif line.startswith("data: "):
                data_line = line[len("data: "):]
        if event_name and data_line is not None:
            events.append({"event": event_name, "data": json.loads(data_line)})
    return events


# ---------- /start ----------

def test_start_creates_session_and_generates_opening(client, customer_code, mock_llm):
    mock_llm.push(_ask("欢迎！请问您有投资经验吗？"))

    resp = client.post("/api/v1/assessment/chat/start", json={"customer_code": customer_code})
    assert resp.status_code == 200
    body = resp.json()
    assert body["resumed"] is False
    assert body["session_code"].startswith("CHAT")
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "assistant"
    assert body["messages"][0]["content"] == "欢迎！请问您有投资经验吗？"


def test_start_resumes_existing_active_session(client, customer_code, mock_llm):
    mock_llm.push(_ask("Q1"))
    first = client.post("/api/v1/assessment/chat/start", json={"customer_code": customer_code}).json()

    # 第二次调 /start 不应该再触发 LLM
    resp = client.post("/api/v1/assessment/chat/start", json={"customer_code": customer_code})
    assert resp.status_code == 200
    body = resp.json()
    assert body["resumed"] is True
    assert body["session_code"] == first["session_code"]
    assert len(mock_llm.calls) == 1


def test_start_unknown_customer_returns_404(client, mock_llm):
    resp = client.post("/api/v1/assessment/chat/start", json={"customer_code": "CUS-NOEXIST"})
    assert resp.status_code == 404


def test_start_llm_failure_returns_503(client, customer_code, mock_llm, monkeypatch):
    from app.services import chat_service
    monkeypatch.setattr(chat_service, "RETRY_BASE_DELAY", 0)   # 免真退避 sleep

    def boom():
        raise RuntimeError("INTERNAL-secret-detail-xyz")   # 内部细节，不该外泄

    for _ in range(chat_service.MAX_LLM_ATTEMPTS):   # 每次都失败，耗尽重试
        mock_llm.push(boom)

    resp = client.post("/api/v1/assessment/chat/start", json={"customer_code": customer_code})
    assert resp.status_code == 503
    # S3：对外只给通用文案，不泄露原始异常内部细节
    assert "INTERNAL-secret-detail-xyz" not in resp.text
    assert "请稍后重试" in resp.json()["detail"]


# ---------- /message ----------

def test_message_streams_delta_and_completed_asking(client, customer_code, mock_llm):
    mock_llm.push(_ask("Q1"))
    start = client.post("/api/v1/assessment/chat/start", json={"customer_code": customer_code}).json()
    code = start["session_code"]

    mock_llm.push(_ask("请问您能接受多大跌幅？"))
    resp = client.post(
        f"/api/v1/assessment/chat/{code}/message",
        json={"content": "我是新手"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    assert any(e["event"] == "delta" for e in events)
    completed = [e for e in events if e["event"] == "completed"]
    assert len(completed) == 1
    assert completed[0]["data"]["phase"] == "asking"
    assert completed[0]["data"]["round"] == 1


def test_message_concludes_creates_assessment(client, customer_code, mock_llm, db):
    mock_llm.push(_ask("Q1"))
    start = client.post("/api/v1/assessment/chat/start", json={"customer_code": customer_code}).json()
    code = start["session_code"]

    mock_llm.push(_conclude(pref="C2"))
    resp = client.post(
        f"/api/v1/assessment/chat/{code}/message",
        json={"content": "保守"},
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    completed = [e for e in events if e["event"] == "completed"]
    assert completed[-1]["data"]["phase"] == "concluded"
    assert completed[-1]["data"]["assessment"]["risk_preference"] == "C4"
    assert completed[-1]["data"]["assessment"]["source"] == "ai_chat"

    # 真的落了 Assessment
    assessments = db.query(Assessment).all()
    assert len(assessments) == 1
    assert assessments[0].source == "ai_chat"


def test_message_on_unknown_session_returns_404(client, mock_llm):
    resp = client.post(
        "/api/v1/assessment/chat/CHAT-NOEXIST/message",
        json={"content": "hi"},
    )
    assert resp.status_code == 404


def test_message_on_completed_session_returns_409(client, customer_code, mock_llm, db):
    mock_llm.push(_ask("Q1"))
    start = client.post("/api/v1/assessment/chat/start", json={"customer_code": customer_code}).json()
    code = start["session_code"]

    # 手动标记完成
    session = db.query(ChatSession).filter_by(code=code).first()
    session.status = "completed"
    db.commit()

    resp = client.post(
        f"/api/v1/assessment/chat/{code}/message",
        json={"content": "hi"},
    )
    assert resp.status_code == 409


def test_message_llm_error_streams_error_event(client, customer_code, mock_llm):
    mock_llm.push(_ask("Q1"))
    start = client.post("/api/v1/assessment/chat/start", json={"customer_code": customer_code}).json()
    code = start["session_code"]

    mock_llm.push([LLMError(message="违规", code="content_policy")])
    resp = client.post(
        f"/api/v1/assessment/chat/{code}/message",
        json={"content": "hi"},
    )
    # 200 因为流已开启；错误通过 event 传达
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events[-1]["event"] == "error"
    assert events[-1]["data"]["code"] == "content_policy"


# ---------- /restart ----------

def test_restart_abandons_old_and_creates_new(client, customer_code, mock_llm, db):
    mock_llm.push(_ask("Q1"))
    start = client.post("/api/v1/assessment/chat/start", json={"customer_code": customer_code}).json()
    old_code = start["session_code"]

    mock_llm.push(_ask("欢迎再次光临"))
    resp = client.post(f"/api/v1/assessment/chat/{old_code}/restart")
    assert resp.status_code == 200
    body = resp.json()
    assert body["resumed"] is False
    assert body["session_code"] != old_code
    assert body["messages"][0]["content"] == "欢迎再次光临"

    old = db.query(ChatSession).filter_by(code=old_code).first()
    assert old.status == "abandoned"


def test_restart_unknown_session_returns_404(client, mock_llm):
    resp = client.post("/api/v1/assessment/chat/CHAT-NOEXIST/restart")
    assert resp.status_code == 404
