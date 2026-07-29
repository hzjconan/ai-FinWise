"""chat_service + MockLLMClient 的单元测试。

没有接入 pytest-asyncio，因此用 asyncio.run 直接驱动 async 函数。
"""
import asyncio

import pytest

import json

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


def _search_events(risk_level: str = "C4") -> list:
    return [ToolResult(name=chat_service.TOOL_SEARCH, input={"risk_level": risk_level})]


def _conclude_events(
    content: str = "评估完成",
    pref: str = "C3",
    summary: str = "客户属于稳健型",
    dimensions: dict | None = {"experience": 5, "loss_tolerance": 3, "income_stability": 3, "investment_horizon": 4, "volatility_tolerance": 3},
) -> list:
    return [
        ToolResult(
            name=chat_service.TOOL_CONCLUDE,
            input={
                "content": content,
                "risk_preference": pref,
                "summary": summary,
                "dimensions": dimensions,
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
    # 终态工具（ask/conclude）回放成纯 assistant 文本，不是 tool_use 块——
    # 避免历史里出现「后面没有配对 tool_result 的悬空 tool_use」（真实 API 会拒）
    assert msgs[0] == {"role": "assistant", "content": "你好？"}
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
                dimensions={"experience": 4, "loss_tolerance": 4, "income_stability": 4, "investment_horizon": 4, "volatility_tolerance": 4}, # sum=20 → 80 → C5
    )])

    events = _run(_collect(chat_service.handle_user_message(db, session, "我追求高收益", llm)))

    completed = [e for e in events if e["event"] == "completed"]
    assert len(completed) == 1
    data = completed[0]["data"]
    assert data["phase"] == "concluded"
    assert data["assessment"]["risk_preference"] == "C5"
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


def test_handle_user_message_conclude_after_search(db):
    """阶段三② 步骤3 验收：模型先调可执行工具 search_products（执行+回喂，不落库不吐 delta），
    再 conclude。断言：① 中间不落库/不吐 search delta ② 最终建 Assessment
    ③ 调 2 次 LLM 且第 2 次 messages 含 tool_result（search 结果被回喂）。"""
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    _make_product(db, "P-C4", "成长精选混合", "C4", "0.085")
    db.commit()

    llm = MockLLMClient([
        _search_events("C4"),         # 第 1 轮：可执行工具 → 执行、回喂、继续
        _conclude_events(pref="C4"),  # 第 2 轮：终态工具 → 收尾
    ])

    events = _run(_collect(chat_service.handle_user_message(db, session, "我追求高收益", llm)))

    # ① 中间 search 不落库：最终只落 user + assistant(conclude) 两条（无 search 那条）
    msgs = db.query(ChatMessage).filter_by(session_id=session.id).order_by(ChatMessage.id).all()
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[1].tool_use["name"] == chat_service.TOOL_CONCLUDE
    #    中间 search 不吐 delta：所有 delta 都只来自 conclude 的 content
    delta_events = [e for e in events if e["event"] == "delta"]
    assert all(e["data"]["content"] == "评估完成" for e in delta_events)

    # ② 最终建了 Assessment
    completed = [e for e in events if e["event"] == "completed"]
    assert len(completed) == 1 and completed[0]["data"]["phase"] == "concluded"
    assessments = db.query(Assessment).filter_by(customer_id=customer.id).all()
    assert len(assessments) == 1 and assessments[0].risk_preference == "C4"

    # ③ 调了 2 次 LLM，且第 2 次 messages 含 tool_result（search 结果确实回喂给了模型）
    assert len(llm.calls) == 2
    second_messages = llm.calls[1]["messages"]
    assert any(
        isinstance(m.get("content"), list)
        and any(b.get("type") == "tool_result" for b in m["content"])
        for m in second_messages
    )


def test_executable_tool_use_and_result_paired_by_id(db):
    """可执行工具回喂：tool_use.id 与 tool_result.tool_use_id 必须配对（真实 Anthropic API 强制）。"""
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    _make_product(db, "P-R4", "成长精选混合", "R4", "0.085")
    db.commit()

    # 带 id 的可执行工具调用 → 执行、回喂 → 再 conclude 收尾
    search_with_id = [ToolResult(name=chat_service.TOOL_SEARCH, input={"risk_level": "C4"}, id="toolu_test_123")]
    llm = MockLLMClient([search_with_id, _conclude_events(pref="C4")])

    events = _run(_collect(chat_service.handle_user_message(db, session, "我要投资", llm)))
    assert events[-1]["event"] == "completed"

    # 第 2 次调用回喂的 messages 里，抓出 tool_use 的 id 与 tool_result 的 tool_use_id
    tool_use_id = tool_result_ref = None
    for m in llm.calls[1]["messages"]:
        if isinstance(m.get("content"), list):
            for b in m["content"]:
                if b.get("type") == "tool_use":
                    tool_use_id = b.get("id")
                if b.get("type") == "tool_result":
                    tool_result_ref = b.get("tool_use_id")
    assert tool_use_id == "toolu_test_123"          # 源 id 被带上 tool_use
    assert tool_result_ref == "toolu_test_123"      # tool_result 用同一个 id 指回去
    assert tool_use_id == tool_result_ref           # 配对成立


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


# ---------- 阶段三② 步骤2：_execute_tool（search_products 复用产品查询）----------

def _make_product(db, code, name, risk_level, ret, status="active", ptype="混合基金"):
    from decimal import Decimal

    from app.models.product import Product
    p = Product(product_code=code, name=name, type=ptype, status=status,
                risk_level=risk_level, expected_return=Decimal(str(ret)))
    db.add(p)
    return p


def test_execute_search_products_returns_active_products_by_risk_level(db):
    _make_product(db, "P-R4-A", "成长精选混合", "R4", "0.085")
    _make_product(db, "P-R4-B", "科技行业ETF", "R4", "0.112", ptype="ETF")
    _make_product(db, "P-R1", "稳盈货币A", "R1", "0.021")          # 别的等级 → 应排除
    _make_product(db, "P-R4-D", "草稿产品", "R4", "0.090", status="draft")  # 非 active → 应排除
    db.commit()

    result = chat_service._execute_tool(db, chat_service.TOOL_SEARCH, {"risk_level": "C4"})

    assert result["risk_level"] == "C4"
    names = [p["name"] for p in result["products"]]
    # 只返回 C4 且 active，按 expected_return 降序
    assert names == ["科技行业ETF", "成长精选混合"]
    # 精简字段（控制 token）
    assert set(result["products"][0].keys()) == {"product_code", "name", "type", "expected_return"}
    assert result["products"][0]["expected_return"] == 0.112


def test_execute_search_products_empty_when_no_match(db):
    _make_product(db, "P-C1", "稳盈货币A", "C1", "0.021")
    db.commit()
    result = chat_service._execute_tool(db, chat_service.TOOL_SEARCH, {"risk_level": "C5"})
    assert result == {"risk_level": "C5", "products": []}


def test_execute_tool_unknown_raises(db):
    with pytest.raises(ValueError, match="未知可执行工具"):
        chat_service._execute_tool(db, "no_such_tool", {})


# ---------- 阶段三② 步骤1：工具分类（可执行 vs 终态）----------

def test_tool_classification_terminal_vs_executable():
    # 终态工具：ask / conclude —— 调用即结束本回合
    assert chat_service.is_terminal_tool(chat_service.TOOL_ASK)
    assert chat_service.is_terminal_tool(chat_service.TOOL_CONCLUDE)
    assert not chat_service.is_executable_tool(chat_service.TOOL_ASK)
    assert not chat_service.is_executable_tool(chat_service.TOOL_CONCLUDE)

    # 可执行工具：search_products —— 关键断言：它「不是终态」，是「可执行」
    assert chat_service.is_executable_tool(chat_service.TOOL_SEARCH)
    assert not chat_service.is_terminal_tool(chat_service.TOOL_SEARCH)

    # 未知工具：两者都不是（防御分流时会被当作未知处理）
    assert not chat_service.is_terminal_tool("unknown_tool")
    assert not chat_service.is_executable_tool("unknown_tool")


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


# ============================================================
# 阶段三② 练习 TODO —— 在真实 chat_service 上练手
#   规则：遵守仓库硬约束「改动必须有测试」；玩法同 scratch——自己改码 + 写测试，改完让我 review + 跑。
#   建议从 #3 开始（修一个真实缺口，价值最高）。
# ------------------------------------------------------------
# 3. ★ 补「未知工具」防御（先做）
#    现状缺口：handle_user_message 里，若模型调了「既非可执行、也非 ask/conclude」的未知工具，
#      is_executable_tool 为假 → 落到终态分支 → 因 name != TOOL_CONCLUDE → 被【误当成 asking】处理。
#    改哪：app/services/chat_service.py 的 handle_user_message 终态分支——先判 name 是否属于已知
#      终态工具(TERMINAL_TOOLS)，否则 yield {"code":"invalid_response"/"unknown_tool"} 的 error
#      并 return（别静默当 ask）。参照你 s3_01 的「显式三分流」。
#    加测试：mock 返回一个未知工具名的 ToolResult（如 ToolResult(name="foo", input={})），
#      断言 yield 了 error 事件、且没建 Assessment、没落 ChatMessage。
#    练的：把 scratch 的「防御未知工具」焊到真实代码。
#
# 4. 测 MAX_STEPS 兜底（纯加测试，不改码）
#    加测试：给 MockLLMClient 连续 push 6 个 _search_events()（永不 conclude），
#      断言最终 yield 了 {"code": "max_steps"} 的 error、没建 Assessment、没落中间 ChatMessage。
#    练的：验证 MAX_AGENT_STEPS 安全阀（C 文档专门点名的测试）。
#
# 5. 加第二个可执行工具 get_product_detail(product_code)
#    改哪：TOOLS_SCHEMA 加工具定义、EXECUTABLE_TOOLS 加名字、_execute_tool 加分支
#      （复用 Product 查询，按 product_code 返回某产品更多字段）。
#    加测试：_execute_tool 按 code 返回正确详情；进阶可再加 search→detail→conclude 三步 loop 测试。
#    练的：在真实 agent loop 上「扩工具」（对应 s3_01 的 subtract 练习）。
#
# 6. 加硬校验：conclude 落库前校验 risk_preference ∈ C1–C5，非法则 error 不落库
#    改哪：handle_user_message 的 conclude 分支，落 Assessment 前加服务端校验。
#    加测试：mock 返回 conclude 但 risk_preference="C9"（越界），断言 yield error、没建 Assessment。
#    练的：把「软约束(schema enum) + 硬校验(服务端兜底)」焊到真实评估流程。
#
# 7. ★ 把定级从模型手里拿走：conclude 用「维度分 → 确定性阈值」定级（B#6 的下一步）
#    ---- 目的（为什么做这个练习）----
#    风险等级(C1–C5)是有业务后果的关键值——它决定给客户推什么风险的产品。而「维度分 → 等级」
#    是一步纯机械的阈值映射，不该由模型自由裁量。真机实证：同一套维度分（均值 3.6 → normalized 72），
#    模型两次自报一次 C4、一次 C3，且 C3 那次跟它【自己给的维度分】(72 按阈值应为 C4)自相矛盾——
#    软判断会在边界抖。目标：让模型只出它擅长的「维度分」，「维度分→等级」交给确定性代码。
#
#    ---- 现状缺口：同一个系统里有两套定级方式 ----
#      · 问卷链路（确定性）：calculate_risk_preference(risk_calculator.py:69)——把分数按
#        PREFERENCE_THRESHOLDS 映射到 C 级，纯阈值、零裁量、可复现。
#      · AI 对话链路（模型裁量）：conclude 分支直接 risk_preference=payload["risk_preference"]，
#        信任模型【自报】的等级。B#6 只校验它 ∈ C1–C5，不校验它对不对。
#    问卷是确定性的、AI 是模型裁量的——这就是要弥合的缺口。而 conclude 分支其实【已经在算】
#    normalized_score(维度均值×20)了，只差最后一步「用它定级」没接上。
#
#    ---- 改哪 ----
#    handle_user_message 的 conclude 分支：用模型给的 dimensions 算 total_score/max_possible，
#    走 calculate_risk_preference（total=sum(维度值)、max=维度数×5）拿到 preference_code，
#    用【算出来的】等级落库，不再信 payload["risk_preference"]（它降级为参考，可忽略或做一致性
#    对比、不一致时记日志）。校验重心从「risk_preference 合法」移到「dimensions 存在且为 5 维」——
#    畸形维度分沿用 B#6 思路：拦下（error 不落库），别拿残缺数据算。
#
#    ---- 加测试 ----
#    · 钉死抖动：mock conclude 给维度均值 3.6（如 experience=5,loss=3,income=3,horizon=4,vol=3）、
#      但 risk_preference 自报 "C3"，断言落库 Assessment.risk_preference == "C4"
#      （以维度分算出的为准，不随模型自报走）。这把那次 C4/C3 抖动用测试永久钉死。
#    · 边界：构造正好落某档的维度分，断言映射到预期等级。
#    练的：把「关键值来自权威计算、不信模型」从原则变成代码。
# ============================================================

# 阶段三② 练习3 补「未知工具」防御
def _unknown_tool_use(content: str) -> list:
    return [
        TextDelta(text=content),
        ToolResult(name="unknown_tool", input={"content": content}),
    ]
def test_unknown_tool(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    llm = MockLLMClient([_unknown_tool_use("未知工具")])

    results = _run(_collect(chat_service.handle_user_message(db, session, "明天天气怎么样", llm)))
    assert len(llm.calls) == 1
    assert db.query(Assessment).filter_by(customer_id=customer.id).count() == 0
    assert db.query(ChatMessage).filter_by(session_id=session.id).count() == 0
    assert results[0]["event"] == "error"
    assert results[0]["data"] == {"code": "unknown_tool", "message": "未知工具"}

# 阶段三② 练习4 测 MAX_STEPS 兜底
def test_max_step_limit(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    llm = MockLLMClient([_search_events("C4") for _ in range(chat_service.MAX_AGENT_STEPS + 1)])

    results = _run(_collect(chat_service.handle_user_message(db, session, "我要投资", llm)))
    assert len(llm.calls) == chat_service.MAX_AGENT_STEPS
    assert db.query(Assessment).filter_by(customer_id=customer.id).count() == 0
    assert db.query(ChatMessage).filter_by(session_id=session.id).count() == 0
    assert results[-1]["event"] == "error"
    assert results[-1]["data"]["code"] == "max_steps"

# 阶段三② 练习5 加第二个可执行工具
def _get_product_detail(product_codes: list[str]):
    return [ToolResult(name=chat_service.TOOL_GET_DETAIL, input={"product_codes": product_codes})]

def test_get_valid_products_detail(db):
    _make_product(db, "P-C4-A", "成长精选混合", "C4", "0.085")
    _make_product(db, "P-C4-B", "科技行业ETF", "C4", "0.112", ptype="ETF")
    _make_product(db, "P-C1", "稳盈货币A", "C1", "0.021")
    db.commit()

    results = chat_service._execute_tool(db, chat_service.TOOL_GET_DETAIL, {"product_codes": ["P-C4-B"]})
    assert len(results["products"]) == 1
    p = results["products"][0]
    assert p["product_code"] == "P-C4-B" and p["name"] == "科技行业ETF"
    assert p["expected_return"] == 0.112

def test_get_invalid_products_detail(db):
    _make_product(db, "P-C4-A", "成长精选混合", "C4", "0.085")
    db.commit()

    results = chat_service._execute_tool(db, chat_service.TOOL_GET_DETAIL, {"product_codes": ["P-C4-B"]})
    assert len(results["products"]) == 0

def test_loop_search_then_detail_then_conclude(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    _make_product(db, "P-C4-B", "科技行业ETF", "C4", "0.112", ptype="ETF")
    db.commit()

    llm = MockLLMClient([_search_events("C4"), _get_product_detail(["P-C4-B"]), _conclude_events(pref="C4")])

    events = _run(_collect(chat_service.handle_user_message(db, session, "帮我看看产品", llm)))

    # 最终 completed 且 phase == "concluded"，并建了 1 条 Assessment(risk_preference=="C4")
    assert events[-1]["event"] == "completed"
    assert events[-1]["data"]["phase"] == "concluded"
    assert db.query(Assessment).filter_by(customer_id=customer.id, risk_preference="C4").count() == 1

    # 调了 3 次 LLM
    assert len(llm.calls) == 3

    # (关键): 最后一次调用 llm.calls[-1]["messages"] 里，含一个
    #  tool_use 块 name == chat_service.TOOL_GET_DETAIL —— 证明 get_detail 确实进了 loop 并被回喂
    #tu_msg = llm.calls[-1]["messages"].filter(lambda x: x["type"] == "tool_use" and x["name"] == chat_service.TOOL_GET_DETAIL)
    #assert tu_msg is not None
    last_messages = llm.calls[-1]["messages"]
    assert any(
        isinstance(m["content"], list) and
        any(
            b["type"] == "tool_use"
            and b["name"] == chat_service.TOOL_GET_DETAIL
            for b in m["content"]
        )
        for m in last_messages
    )

    # 中间两步不落库 —— 最终 ChatMessage 只有 ["user", "assistant"] 两条
    assert db.query(ChatMessage).filter_by(session_id=session.id).count() == 2

# 阶段三② 练习6 加硬校验：conclude 落库前校验 risk_preference ∈ C1–C5，非法则 error 不落库
def test_invalid_risk_preference(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    llm = MockLLMClient([_conclude_events(pref="C9")])

    results = _run(_collect(chat_service.handle_user_message(db, session, "我要投资", llm)))
    assert len(llm.calls) == 1
    assert db.query(Assessment).filter_by(customer_id=customer.id).count() == 0
    assert db.query(ChatMessage).filter_by(session_id=session.id).count() == 0
    assert results[0]["event"] == "error"
    assert results[0]["data"]["code"] == "invalid_risk_preference"

def test_missing_risk_preference(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    llm = MockLLMClient([
        [ToolResult(name=chat_service.TOOL_CONCLUDE, input={})]
    ])

    results = _run(_collect(chat_service.handle_user_message(db, session, "我要投资", llm)))
    assert len(llm.calls) == 1
    assert db.query(Assessment).filter_by(customer_id=customer.id).count() == 0
    assert db.query(ChatMessage).filter_by(session_id=session.id).count() == 0
    assert results[0]["event"] == "error"
    assert results[0]["data"]["code"] == "invalid_risk_preference"

def test_valid_matched_risk_level(db):
    _make_product(db, "P-R4-B", "科技行业ETF", "R4", "0.112", ptype="ETF")
    db.commit()

    result = chat_service._execute_tool(db, chat_service.TOOL_SEARCH, {"risk_level": "C4"})
    
    assert result["risk_level"] == "C4"
    assert len(result["products"]) == 1
    p = result["products"][0]
    assert p["product_code"] == "P-R4-B" and p["name"] == "科技行业ETF"

def test_invalid_matched_risk_level(db):
    _make_product(db, "P-R4-B", "科技行业ETF", "R4", "0.112", ptype="ETF")
    db.commit()

    result = chat_service._execute_tool(db, chat_service.TOOL_SEARCH, {"risk_level": "C3"})
    
    assert result["risk_level"] == "C3"
    assert len(result["products"]) == 0

# 阶段三② 练习7 把定级从模型手里拿走：conclude 用「维度分 → 确定性阈值」定级
def test_caculate_risk_preference_from_valid_dimensions(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    dimensions = {"experience": 5, "loss_tolerance": 3, "income_stability": 3, "investment_horizon": 4, "volatility_tolerance": 3}
    llm = MockLLMClient([_conclude_events(pref="C2", dimensions=dimensions)])
    result = _run(_collect(chat_service.handle_user_message(db, session, "我要投资", llm)))
    # 自己计算 risk_preference，不采纳模型给出的值——验证「落库的值」
    asm: Assessment = db.query(Assessment).filter_by(customer_id=customer.id).one()
    assert asm.risk_preference == "C4"

def test_caculate_risk_preference_from_invalid_dimensions(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    llm = MockLLMClient([_conclude_events(pref="C2", dimensions={"experience": 5, "loss_tolerance": 3, "income_stability": 3,
                  "investment_horizon": 4, "unknown": 1})])
    result = _run(_collect(chat_service.handle_user_message(db, session, "我要投资", llm)))
    assert result[-1]["event"] == "error"
    assert result[-1]["data"]["code"] == "invalid_dimensions"
    assert db.query(Assessment).filter_by(customer_id=customer.id).count() == 0

def test_caculate_risk_preference_from_invalid_dimensions_count(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    llm = MockLLMClient([_conclude_events(pref="C2", dimensions={"experience": 5, "loss_tolerance": 3, "income_stability": 3,
                  "investment_horizon": 4, "volatility_tolerance": 3, "unknown": 1})])
    result = _run(_collect(chat_service.handle_user_message(db, session, "我要投资", llm)))
    assert result[-1]["event"] == "error"
    assert result[-1]["data"]["code"] == "invalid_dimensions"
    assert db.query(Assessment).filter_by(customer_id=customer.id).count() == 0

def test_caculate_risk_preference_from_empty_dimensions(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)
    llm = MockLLMClient([_conclude_events(pref="C2", dimensions=None)])
    result = _run(_collect(chat_service.handle_user_message(db, session, "我要投资", llm)))
    assert result[-1]["event"] == "error"
    assert result[-1]["data"]["code"] == "invalid_dimensions"
    assert db.query(Assessment).filter_by(customer_id=customer.id).count() == 0

def test_caculate_risk_preference_from_non_numeric_dimensions(db):
    customer = _make_customer(db)
    session = chat_service.create_session(db, customer.id)

    # 5 个键，但有一个是字符串（个数够、类型不对）—— 旧校验会漏过、静默用 4 维算错
    dimensions = {"experience": 5, "loss_tolerance": 3, "income_stability": 3, "investment_horizon": 4, "volatility_tolerance": "高"}
    llm = MockLLMClient([_conclude_events(pref="C2", dimensions=dimensions)])
    result = _run(_collect(chat_service.handle_user_message(db, session, "我要投资", llm)))
    assert result[-1]["event"] == "error"
    assert result[-1]["data"]["code"] == "invalid_dimensions"
    assert db.query(Assessment).filter_by(customer_id=customer.id).count() == 0