"""AI 对话评估的业务逻辑。

核心职责：
- 会话创建、恢复、重开
- 与 LLM 的单轮交互（含自动重试 1 次）
- 消息落盘（用户消息 + 助手消息）
- conclude 时创建 Assessment 并完成会话
- 把 LLM 事件翻译为 SSE 事件字典（由 router 负责序列化）

设计要点（来自 03-ai-assessment-design.md）：
- 每个 customer 同时最多 1 条 status='active' 的 session
- user 消息只在 LLM 成功响应后才写入 chat_messages（避免重试导致重复）
- conclude 在单个事务内写 assessment + 更新 session.status + 关联 chat_session_id
"""

import json
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from unicodedata import normalize

from sqlalchemy.orm import Session

from app.models.assessment import Assessment
from app.models.chat import ChatMessage, ChatSession
from app.models.customer import Customer
from app.models.product import Product
from app.services.llm.base import LLMClient
from app.services.llm.events import LLMError, TextDelta, ToolResult
from app.services.llm.prompts import load_system_prompt, load_dimensions
from app.services.risk_calculator import MATCH_RULES, PREFERENCE_LABELS, calculate_risk_preference
from app.utils.code_generator import generate_code

VALID_RISK_PREFERENCE = frozenset(PREFERENCE_LABELS)
VALID_DIMENSION_KEYS = frozenset(d["key"] for d in load_dimensions())

# Tool 名称常量
TOOL_ASK = "ask_next_question"
TOOL_CONCLUDE = "conclude_assessment"
TOOL_SEARCH = "search_products"  # 阶段三②：可执行工具（服务端执行→结果回喂→循环继续）
TOOL_GET_DETAIL = "get_product_detail" # 阶段三② 练习5 加第二个可执行工具

TOOLS_SCHEMA: list[dict] = [
    {
        "name": TOOL_ASK,
        "description": "继续提问以收集信息。",
        "input_schema": {
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
        },
    },
    {
        "name": TOOL_CONCLUDE,
        "description": "信息充分时输出评估结论。",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "risk_preference": {
                    "type": "string",
                    "enum": ["C1", "C2", "C3", "C4", "C5"],
                },
                "summary": {"type": "string"},
                "dimensions": {"type": "object"},
            },
            "required": ["content", "risk_preference", "summary", "dimensions"],
        },
    },
    {
        "name": TOOL_SEARCH,
        "description": "（可选）按风险等级查询当前在售产品，供评估参考。风险等级取值 C1–C5。",
        "input_schema": {
            "type": "object",
            "properties": {
                "risk_level": {"type": "string", "enum": ["C1", "C2", "C3", "C4", "C5"]},
            },
            "required": ["risk_level"],
        },
    },
    {
        "name": TOOL_GET_DETAIL,
        "description": "（可选）根据产品代码查询多个产品的详细信息。",
        "input_schema": {
            "type": "object",
            "properties": {"product_codes": {"type": "array", "items": {"type": "string"}}},
            "required": ["product_codes"],
        },
    },
]

MAX_AGENT_STEPS = 5  # ★ agent loop 硬上限：防止可执行工具被无限调用（失控/烧钱）

# 工具分类（靠工具名约定区分，不改数据结构）——阶段三② 步骤1：
#   - 终态工具：模型调它 = 本回合结束（ask 继续问 / conclude 下结论），loop 应收尾。
#   - 可执行工具：服务端执行、把结果回喂给模型，loop 继续（search_products）。
# 注意：search_products 尚未加入 TOOLS_SCHEMA（步骤3循环就绪后再加），此处仅先建立分类概念，
#       不改动 handle_user_message 现有单步行为（现有测试应保持全绿）。
TERMINAL_TOOLS = frozenset({TOOL_ASK, TOOL_CONCLUDE})
EXECUTABLE_TOOLS = frozenset({TOOL_SEARCH, TOOL_GET_DETAIL})


def is_terminal_tool(name: str) -> bool:
    """模型这次调的工具是否为终态工具（调用即结束本回合）。"""
    return name in TERMINAL_TOOLS


def is_executable_tool(name: str) -> bool:
    """模型这次调的工具是否为可执行工具（需服务端执行 + 结果回喂 + 循环继续）。"""
    return name in EXECUTABLE_TOOLS


def _execute_tool(db: Session, name: str, tool_input: dict) -> dict:
    """执行可执行工具，返回结构化结果 dict（loop 会序列化成 tool_result 回喂给模型）。

    纯查询、无副作用、可单测。阶段三② 步骤2：search_products 复用产品查询，
    按风险等级查「active」产品并只回喂精简字段（控制 token，只给模型挑选所需信息）。
    """
    if name == TOOL_SEARCH:
        risk_level = tool_input.get("risk_level")
        rules = MATCH_RULES.get(risk_level, [])
        if len(rules) == 0:
            return {"risk_level": risk_level, "products": []}
        matched_risk_levels = rules.get("exact", [])
        products = (
            db.query(Product)
            .filter(Product.status == "active", Product.risk_level.in_(matched_risk_levels))
            .order_by(Product.expected_return.desc())
            .all()
        )
        return {
            "risk_level": risk_level,
            "products": [
                {
                    "product_code": p.product_code,
                    "name": p.name,
                    "type": p.type,
                    "expected_return": (
                        float(p.expected_return) if p.expected_return is not None else None
                    ),
                }
                for p in products
            ],
        }
    if name == TOOL_GET_DETAIL:
        products: list[Product] = db.query(Product).filter(Product.product_code.in_(tool_input.get("product_codes"))).all()
        return {"products": [
            {
                "product_code": p.product_code,
                "name": p.name,
                "expected_return": (
                    float(p.expected_return) if p.expected_return is not None else None
                ),
            } for p in products
        ]}
    raise ValueError(f"未知可执行工具: {name}")


# ---------- Session 查询 / 创建 ----------

def find_customer(db: Session, customer_code: str) -> Customer | None:
    return db.query(Customer).filter(Customer.code == customer_code).first()


def find_active_session(db: Session, customer_id: int) -> ChatSession | None:
    return (
        db.query(ChatSession)
        .filter(
            ChatSession.customer_id == customer_id,
            ChatSession.status == "active",
        )
        .order_by(ChatSession.created_at.desc())
        .first()
    )


def find_session_by_code(db: Session, code: str) -> ChatSession | None:
    return db.query(ChatSession).filter(ChatSession.code == code).first()


def create_session(db: Session, customer_id: int) -> ChatSession:
    code = generate_code(db, ChatSession, "CHAT")
    session = ChatSession(code=code, customer_id=customer_id, status="active")
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def abandon_session(db: Session, session: ChatSession) -> None:
    session.status = "abandoned"
    db.commit()


# ---------- 消息 API 格式转换 ----------

def build_api_messages(session: ChatSession) -> list[dict]:
    """把 chat_messages 转成 Anthropic messages 格式。"""
    result: list[dict] = []
    for msg in session.messages:
        if msg.role == "user":
            result.append({"role": "user", "content": msg.content})
        elif msg.role == "assistant":
            if msg.tool_use:
                result.append({
                    "role": "assistant",
                    "content": [{"type": "tool_use", "name": msg.tool_use["name"],
                                 "input": msg.tool_use["input"]}],
                })
            else:
                result.append({"role": "assistant", "content": msg.content})
    return result


# ---------- LLM 调用（含自动重试 1 次） ----------

async def _call_llm_with_retry(
    llm: LLMClient,
    *,
    system: str,
    messages: list[dict],
    tools: list[dict],
) -> tuple[str, ToolResult | None, LLMError | None, list[TextDelta]]:
    """调用 LLM 并收集事件。失败重试一次。

    返回 (text, tool_result, llm_error, deltas)：
    - text: 累积的 content 文本
    - tool_result: 模型最终的 tool 调用；若无则 None（视作错误）
    - llm_error: 若 provider 明确上报 LLMError；否则 None
    - deltas: 原始 TextDelta 事件列表（用于 router 逐条转成 SSE）
    """
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            text_parts: list[str] = []
            deltas: list[TextDelta] = []
            tool_result: ToolResult | None = None
            llm_error: LLMError | None = None
            async for event in llm.stream_chat(system=system, messages=messages, tools=tools):
                if isinstance(event, TextDelta):
                    text_parts.append(event.text)
                    deltas.append(event)
                elif isinstance(event, ToolResult):
                    tool_result = event
                elif isinstance(event, LLMError):
                    llm_error = event
            return "".join(text_parts), tool_result, llm_error, deltas
        except Exception as e:  # noqa: BLE001
            last_exc = e
            continue
    # 两次都抛异常
    raise last_exc  # type: ignore[misc]


# ---------- 对外主流程 ----------

async def generate_opening(
    db: Session,
    session: ChatSession,
    llm: LLMClient,
) -> ChatMessage:
    """新建会话后立即调一次 LLM 生成开场白，作为首条 assistant 消息落盘。"""
    try:
        text, tool_result, llm_error, _ = await _call_llm_with_retry(
            llm,
            system=load_system_prompt(),
            messages=[],
            tools=TOOLS_SCHEMA,
        )
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"生成开场白失败：{e}") from e

    if llm_error is not None:
        raise RuntimeError(f"生成开场白失败：{llm_error.message}")
    if tool_result is None or tool_result.name != TOOL_ASK:
        raise RuntimeError("开场白必须调用 ask_next_question")

    content = tool_result.input.get("content") or text
    msg = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=content,
        tool_use={"name": tool_result.name, "input": tool_result.input},
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def count_user_rounds(session: ChatSession) -> int:
    """统计客户发出的消息轮次（不含系统开场白）。"""
    return sum(1 for m in session.messages if m.role == "user")


async def handle_user_message(
    db: Session,
    session: ChatSession,
    user_content: str,
    llm: LLMClient,
) -> AsyncIterator[dict]:
    """处理一条 user 消息。yield SSE 事件字典（由 router 序列化）。

    事件序列（正常情况）：
    - 多次 {"event": "delta", "data": {"content": "..."}}
    - 一次 {"event": "completed", "data": {"phase": "asking" | "concluded", "round": N, "assessment"?}}

    错误情况：
    - {"event": "error", "data": {"code": "...", "message": "..."}}
    """
    # 工作消息（内存态）：历史 + 本轮 user。search_products 的中间往返只在这里累积，
    # 不落库、不吐 delta（用户不该看到内部工具调用）。
    messages = build_api_messages(session) + [{"role": "user", "content": user_content}]

    # ★ agent loop：调 LLM → 分流（可执行→执行回喂继续 / 终态→收尾）→ 直到收尾或触上限
    for _step in range(MAX_AGENT_STEPS):
        try:
            text, tool_result, llm_error, deltas = await _call_llm_with_retry(
                llm,
                system=load_system_prompt(),
                messages=messages,
                tools=TOOLS_SCHEMA,
            )
        except Exception as e:  # noqa: BLE001
            yield {"event": "error", "data": {"code": "llm_error", "message": str(e)}}
            return

        if llm_error is not None:
            yield {"event": "error", "data": {"code": llm_error.code, "message": llm_error.message}}
            return

        if tool_result is None:
            yield {
                "event": "error",
                "data": {"code": "invalid_response", "message": "LLM 未返回 tool_use"},
            }
            return

        # ---- 可执行工具：执行 → 结果回喂 messages（内存，不落库、不吐 delta）→ 继续循环 ----
        if is_executable_tool(tool_result.name):
            result = _execute_tool(db, tool_result.name, tool_result.input)
            messages.append({
                "role": "assistant",
                "content": [{"type": "tool_use", "name": tool_result.name, "input": tool_result.input}],
            })
            messages.append({
                "role": "user",
                "content": [{"type": "tool_result", "content": json.dumps(result, ensure_ascii=False)}],
            })
            continue

        # 阶段三② 练习3 补「未知工具」防御
        if not is_terminal_tool(tool_result.name):
            yield {"event": "error", "data": {"code": "unknown_tool", "message": "未知工具"}}
            return

        # 阶段三② 练习6 加硬校验：conclude 落库前校验 risk_preference ∈ C1–C5，非法则 error 不落库
        if tool_result.name == TOOL_CONCLUDE:
            payload = tool_result.input
            if payload.get("risk_preference") not in VALID_RISK_PREFERENCE:
                yield {"event": "error", "data": {"code": "invalid_risk_preference", "message": "风险偏好无效"}}
                return
            # 阶段三② 练习7 dimensions 缺失 / 空 / 不是 5 维 → 畸形
            dimensions = payload.get("dimensions")
            if (not isinstance(dimensions, dict) 
                or set(dimensions.keys()) != VALID_DIMENSION_KEYS
                or not all(isinstance(v, (int, float)) for v in dimensions.values())):
                yield {"event": "error", "data": {"code": "invalid_dimensions", "message": "维度分数无效"}}
                return

            values = list(dimensions.values())

        # ---- 终态工具（ask / conclude）：吐 delta、落盘、收尾（行为与改造前一致）----
        assistant_content = tool_result.input.get("content") or text

        # 逐条吐 delta；若流里没有 text_delta（典型真实场景：模型直接输出 tool_use），
        # 把 tool input 的 content 作为单个 delta 兜底，避免前端拿到空白气泡。
        if deltas:
            for delta in deltas:
                yield {"event": "delta", "data": {"content": delta.text}}
        elif assistant_content:
            yield {"event": "delta", "data": {"content": assistant_content}}

        # 持久化 user + assistant 消息（一轮只在收尾时落一次 user）
        user_msg = ChatMessage(session_id=session.id, role="user", content=user_content)
        assistant_msg = ChatMessage(
            session_id=session.id,
            role="assistant",
            content=assistant_content,
            tool_use={"name": tool_result.name, "input": tool_result.input},
        )
        db.add_all([user_msg, assistant_msg])

        if tool_result.name == TOOL_CONCLUDE:
            # 单事务：落 Assessment + 完成 session
            assessment = Assessment(
                code=generate_code(db, Assessment, "ASM"),
                customer_id=session.customer_id,
                source="ai_chat",
                ai_summary=payload.get("summary"),
                ai_dimensions=dimensions,
                chat_session_id=session.id,
            )
            # 若 dimensions 给了，顺便填 normalized_score（5 维均值 × 20 → 0–100）
            # 阶段三② 练习7 把定级从模型手里拿走：conclude 用「维度分 → 确定性阈值」定级
            normalized, preference, *_ = calculate_risk_preference(
                sum(values), 
                # 各维度满分5
                len(values)*5
            )
            assessment.risk_preference = preference
            assessment.normalized_score = normalized

            db.add(assessment)
            session.status = "completed"
            db.commit()
            db.refresh(assessment)

            yield {
                "event": "completed",
                "data": {
                    "phase": "concluded",
                    "round": count_user_rounds(session),
                    "assessment": {
                        "assessment_code": assessment.code,
                        "source": "ai_chat",
                        "risk_preference": assessment.risk_preference,
                        "risk_label": PREFERENCE_LABELS.get(assessment.risk_preference, "未知"),
                        "ai_summary": assessment.ai_summary,
                        "ai_dimensions": assessment.ai_dimensions,
                    },
                },
            }
            return

        # 继续问（TOOL_ASK）
        db.commit()
        db.refresh(session)
        yield {
            "event": "completed",
            "data": {"phase": "asking", "round": count_user_rounds(session)},
        }
        return

    # 循环到 MAX_AGENT_STEPS 仍未收尾（可执行工具连续调用未终止）→ 兜底错误，防失控
    yield {
        "event": "error",
        "data": {"code": "max_steps", "message": "agent 未能在限定步数内完成"},
    }
