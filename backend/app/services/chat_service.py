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

from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models.assessment import Assessment
from app.models.chat import ChatMessage, ChatSession
from app.models.customer import Customer
from app.services.llm.base import LLMClient
from app.services.llm.events import LLMError, TextDelta, ToolResult
from app.services.risk_calculator import PREFERENCE_LABELS
from app.utils.code_generator import generate_code

# Tool 名称常量
TOOL_ASK = "ask_next_question"
TOOL_CONCLUDE = "conclude_assessment"

# P1 阶段的 system prompt 与 tools 定义占位——P2 接入真实 LLM 时换成
# 从 backend/prompts/ 配置文件加载 + prompt caching 拆分
SYSTEM_PROMPT_PLACEHOLDER = (
    "你是 FinWise 平台的理财风险评估助手。通过 5–8 轮对话评估客户的风险偏好。"
    "每轮必须调用 ask_next_question 或 conclude_assessment 工具之一。"
)

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
]


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
            system=SYSTEM_PROMPT_PLACEHOLDER,
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
    history_msgs = build_api_messages(session)
    new_messages = history_msgs + [{"role": "user", "content": user_content}]

    try:
        text, tool_result, llm_error, deltas = await _call_llm_with_retry(
            llm,
            system=SYSTEM_PROMPT_PLACEHOLDER,
            messages=new_messages,
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

    # 逐条吐 delta
    for delta in deltas:
        yield {"event": "delta", "data": {"content": delta.text}}

    assistant_content = tool_result.input.get("content") or text

    # 持久化 user + assistant 消息
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
        payload = tool_result.input
        assessment = Assessment(
            code=generate_code(db, Assessment, "ASM"),
            customer_id=session.customer_id,
            source="ai_chat",
            risk_preference=payload["risk_preference"],
            ai_summary=payload.get("summary"),
            ai_dimensions=payload.get("dimensions"),
            chat_session_id=session.id,
        )
        # 若 dimensions 给了，顺便填 normalized_score（5 维均值 × 20 → 0–100）
        dims: dict[str, Any] = payload.get("dimensions") or {}
        if dims:
            values = [v for v in dims.values() if isinstance(v, (int, float))]
            if values:
                assessment.normalized_score = Decimal(
                    str(round(sum(values) / len(values) * 20, 2))
                )
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

    # 继续问
    db.commit()
    db.refresh(session)
    yield {
        "event": "completed",
        "data": {"phase": "asking", "round": count_user_rounds(session)},
    }
