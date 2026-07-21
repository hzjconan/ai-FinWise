"""chat_service + MockLLMClient 的单元测试。

没有接入 pytest-asyncio，因此用 asyncio.run 直接驱动 async 函数。
"""
import asyncio

import pytest

from app.models.assessment import Assessment
from app.models.chat import ChatMessage, ChatSession
from app.models.customer import Customer
from app.services import chat_service
from app.services.llm.events import LLMError, TextDelta, ToolResult
from app.services.llm.factory import get_llm_client
from app.services.llm.mock import MockLLMClient


# ---------- helpers ----------

def _run(coro):
    return asyncio.run(coro)


async def _collect(agen):
    return [ev async for ev in agen]


def _make_customer(db) -> Customer:
    c = Customer(code="CUS-TEST01", nickname="测试客户")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _ask_events(content: str) -> list:
    return [
        TextDelta(text=content),
        ToolResult(name=chat_service.TOOL_ASK, input={"content": content}),
    ]


def _conclude_events(
    content: str = "评估完成",
    pref: str = "C3",
    summary: str = "客户属于稳健型",
    dimensions: dict | None = None,
) -> list:
    return [
        ToolResult(
            name=chat_service.TOOL_CONCLUDE,
            input={
                "content": content,
                "risk_preference": pref,
                "summary": summary,
                "dimensions": dimensions or {"risk_tolerance": 3, "experience": 3},
            },
        ),
    ]


# ---------- MockLLMClient ----------

def test_mock_client_empty_script_raises():
    client = MockLLMClient()

    async def go():
        async for _ in client.stream_chat(system="", messages=[], tools=[]):
            pass

    with pytest.raises(RuntimeError, match="script 为空"):
        _run(go())


def test_mock_client_yields_events_and_records_call():
    client = MockLLMClient([_ask_events("你好")])
    events = _run(_collect(
        client.stream_chat(system="sys", messages=[{"role": "user", "content": "hi"}], tools=[])
    ))
    assert any(isinstance(e, TextDelta) for e in events)
    assert any(isinstance(e, ToolResult) for e in events)
    assert len(client.calls) == 1
    assert client.calls[0]["system"] == "sys"


def test_mock_client_callable_item_raises():
    def boom():
        raise RuntimeError("net down")

    client = MockLLMClient([boom])

    async def go():
        async for _ in client.stream_chat(system="", messages=[], tools=[]):
            pass

    with pytest.raises(RuntimeError, match="net down"):
        _run(go())


# ---------- factory ----------

def test_get_llm_client_not_implemented_in_p1():
    with pytest.raises(NotImplementedError):
        get_llm_client()


# ---------- session 基础操作 ----------

def test_create_and_find_active_session(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    assert session.status == "active"
    assert session.code.startswith("CHAT")

    found = chat_service.find_active_session(db, customer.id)
    assert found is not None and found.id == session.id

    by_code = chat_service.find_session_by_code(db, session.code)
    assert by_code is not None and by_code.id == session.id


def test_abandon_session_sets_status(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    chat_service.abandon_session(db, session)
    assert session.status == "abandoned"
    assert chat_service.find_active_session(db, customer.id) is None


def test_find_customer_by_code(db):
    customer = _make_customer(db)
    got = chat_service.find_customer(db, customer.code)
    assert got is not None and got.id == customer.id
    assert chat_service.find_customer(db, "CUS-NOEXIST") is None


# ---------- build_api_messages ----------

def test_build_api_messages_user_and_assistant(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    db.add_all([
        ChatMessage(session_id=session.id, role="assistant", content="你好？",
                    tool_use={"name": "ask_next_question", "input": {"content": "你好？"}}),
        ChatMessage(session_id=session.id, role="user", content="我想投资"),
    ])
    db.commit()
    db.refresh(session)

    msgs = chat_service.build_api_messages(session)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "assistant"
    assert isinstance(msgs[0]["content"], list)
    assert msgs[0]["content"][0]["type"] == "tool_use"
    assert msgs[1] == {"role": "user", "content": "我想投资"}


# ---------- generate_opening ----------

def test_generate_opening_writes_assistant_message(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    llm = MockLLMClient([_ask_events("欢迎，请问您的投资目标？")])

    msg = _run(chat_service.generate_opening(db, session, llm))
    assert msg.role == "assistant"
    assert msg.content == "欢迎，请问您的投资目标？"
    assert msg.tool_use["name"] == chat_service.TOOL_ASK

    persisted = db.query(ChatMessage).filter_by(session_id=session.id).all()
    assert len(persisted) == 1


def test_generate_opening_rejects_conclude_tool(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    llm = MockLLMClient([_conclude_events()])

    with pytest.raises(RuntimeError, match="ask_next_question"):
        _run(chat_service.generate_opening(db, session, llm))


def test_generate_opening_surfaces_llm_error(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    llm = MockLLMClient([[LLMError(message="rate limit", code="rate_limited")]])

    with pytest.raises(RuntimeError, match="rate limit"):
        _run(chat_service.generate_opening(db, session, llm))


# ---------- handle_user_message ----------

def test_handle_user_message_asking_persists_both_messages(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    llm = MockLLMClient([_ask_events("您能接受多大跌幅？")])

    events = _run(_collect(chat_service.handle_user_message(db, session, "我想稳健投资", llm)))

    delta_events = [e for e in events if e["event"] == "delta"]
    completed = [e for e in events if e["event"] == "completed"]
    assert len(delta_events) == 1
    assert delta_events[0]["data"]["content"] == "您能接受多大跌幅？"
    assert len(completed) == 1
    assert completed[0]["data"]["phase"] == "asking"
    assert completed[0]["data"]["round"] == 1

    msgs = db.query(ChatMessage).filter_by(session_id=session.id).order_by(ChatMessage.id).all()
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[0].content == "我想稳健投资"
    assert msgs[1].tool_use["name"] == chat_service.TOOL_ASK


def test_handle_user_message_conclude_creates_assessment(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    llm = MockLLMClient([_conclude_events(
        pref="C4",
        summary="进取型",
        dimensions={"risk_tolerance": 4, "experience": 4, "horizon": 5, "liquidity": 3, "goal": 4},
    )])

    events = _run(_collect(chat_service.handle_user_message(db, session, "我追求高收益", llm)))

    completed = [e for e in events if e["event"] == "completed"]
    assert len(completed) == 1
    data = completed[0]["data"]
    assert data["phase"] == "concluded"
    assert data["assessment"]["risk_preference"] == "C4"
    assert data["assessment"]["source"] == "ai_chat"
    assert data["assessment"]["risk_label"]

    # session 落为 completed
    db.refresh(session)
    assert session.status == "completed"

    # Assessment 已创建 + normalized_score 被填充
    assessments = db.query(Assessment).filter_by(customer_id=customer.id).all()
    assert len(assessments) == 1
    a = assessments[0]
    assert a.source == "ai_chat"
    assert a.chat_session_id == session.id
    assert a.normalized_score is not None
    # 均值 4 × 20 = 80
    assert float(a.normalized_score) == 80.0


def test_handle_user_message_no_deltas_uses_tool_content_as_delta(db):
    """真实 LLM 直接走 tool_use 时，stream 里可能 0 个 text_delta。
    应把 tool input.content 作为单个 delta 吐出，避免前端空白气泡。"""
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    # 注意：这里只有 ToolResult，没有 TextDelta
    llm = MockLLMClient([[
        ToolResult(name=chat_service.TOOL_ASK, input={"content": "下一轮的问题文本"}),
    ]])

    events = _run(_collect(chat_service.handle_user_message(db, session, "我答 A1", llm)))
    delta_events = [e for e in events if e["event"] == "delta"]
    assert len(delta_events) == 1
    assert delta_events[0]["data"]["content"] == "下一轮的问题文本"
    completed = [e for e in events if e["event"] == "completed"]
    assert len(completed) == 1 and completed[0]["data"]["phase"] == "asking"


def test_handle_user_message_llm_error_yields_error_event_and_does_not_persist(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    llm = MockLLMClient([[LLMError(message="内容违规", code="content_policy")]])

    events = _run(_collect(chat_service.handle_user_message(db, session, "test", llm)))
    assert events == [{"event": "error", "data": {"code": "content_policy", "message": "内容违规"}}]

    # 没有写入任何消息（user 也不写）
    assert db.query(ChatMessage).filter_by(session_id=session.id).count() == 0


def test_handle_user_message_retries_once_on_exception(db):
    """第一次 raise，第二次正常 → 最终成功。"""
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)

    def boom():
        raise RuntimeError("transient")

    llm = MockLLMClient([boom, _ask_events("再问一个问题")])

    events = _run(_collect(chat_service.handle_user_message(db, session, "hi", llm)))
    completed = [e for e in events if e["event"] == "completed"]
    assert len(completed) == 1
    assert completed[0]["data"]["phase"] == "asking"
    # 两次调用都被记录
    assert len(llm.calls) == 2


def test_handle_user_message_two_failures_yield_error(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)

    def boom1():
        raise RuntimeError("fail-1")

    def boom2():
        raise RuntimeError("fail-2")

    llm = MockLLMClient([boom1, boom2])
    events = _run(_collect(chat_service.handle_user_message(db, session, "hi", llm)))
    assert len(events) == 1
    assert events[0]["event"] == "error"
    assert events[0]["data"]["code"] == "llm_error"
    assert "fail-2" in events[0]["data"]["message"]


def test_handle_user_message_missing_tool_result_yields_error(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    # 只有 TextDelta，无 ToolResult
    llm = MockLLMClient([[TextDelta(text="只是闲聊")]])

    events = _run(_collect(chat_service.handle_user_message(db, session, "hi", llm)))
    assert events[-1]["event"] == "error"
    assert events[-1]["data"]["code"] == "invalid_response"


# ---------- 改造护栏：终态工具应恰好 1 次 LLM 调用（不循环）----------
# 现有 handle_user_message 每条用户消息只调一次 LLM。阶段三②要把它改成带 MAX_STEPS 的
# while 循环（引入可执行工具 search_products 时才多轮）。这两个测试显式钉死「终态工具
# ask/conclude 只触发一次 LLM 调用、随即终止」——改造若让终态路径误多转一轮，会立刻变红。

def test_handle_user_message_asking_makes_single_llm_call(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    llm = MockLLMClient([_ask_events("单轮提问")])

    _run(_collect(chat_service.handle_user_message(db, session, "我要投资", llm)))
    assert len(llm.calls) == 1


def test_handle_user_message_conclude_makes_single_llm_call(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    llm = MockLLMClient([_conclude_events()])

    _run(_collect(chat_service.handle_user_message(db, session, "我追求高收益", llm)))
    assert len(llm.calls) == 1


def test_count_user_rounds(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    db.add_all([
        ChatMessage(session_id=session.id, role="assistant", content="a1"),
        ChatMessage(session_id=session.id, role="user", content="u1"),
        ChatMessage(session_id=session.id, role="assistant", content="a2"),
        ChatMessage(session_id=session.id, role="user", content="u2"),
    ])
    db.commit()
    db.refresh(session)
    assert chat_service.count_user_rounds(session) == 2
