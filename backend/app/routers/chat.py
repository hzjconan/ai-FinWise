"""AI 对话评估的 SSE 路由。

业务逻辑收敛在 app.services.chat_service；本模块只做：
- HTTP 入参校验 / 依赖注入
- 把 service 的事件字典序列化成 Anthropic 风格 SSE
- 错误 → HTTPException 映射
"""

import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.chat import (
    ChatMessageOut,
    ChatMessageRequest,
    ChatStartRequest,
    ChatStartResponse,
)
from app.services import chat_service
from app.services.llm.base import LLMClient
from app.services.llm.factory import get_llm_client

router = APIRouter()
logger = logging.getLogger(__name__)

# S3：对外只给通用文案，原始异常细节（可能含内部实现/依赖/敏感信息）只进服务端日志。
_AI_UNAVAILABLE = "AI 暂时无法响应，请稍后重试"


def _serialize_sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


@router.post("/start", response_model=ChatStartResponse)
async def start_chat(
    payload: ChatStartRequest,
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm_client),
):
    customer = chat_service.find_customer(db, payload.customer_code)
    if customer is None:
        raise HTTPException(status_code=404, detail="客户不存在")

    active = chat_service.find_active_session(db, customer.id)
    if active is not None and active.messages:
        return ChatStartResponse(
            session_code=active.code,
            resumed=True,
            messages=[ChatMessageOut.model_validate(m) for m in active.messages],
        )

    session = active if active is not None else chat_service.create_session(db, customer.id)
    try:
        await chat_service.generate_opening(db, session, llm)
    except Exception as e:  # noqa: BLE001
        logger.warning("生成开场白失败", exc_info=e)   # 详情只进服务端日志
        raise HTTPException(status_code=503, detail=_AI_UNAVAILABLE) from e

    db.refresh(session)
    return ChatStartResponse(
        session_code=session.code,
        resumed=False,
        messages=[ChatMessageOut.model_validate(m) for m in session.messages],
    )


@router.post("/{session_code}/message")
async def send_message(
    session_code: str,
    payload: ChatMessageRequest,
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm_client),
):
    session = chat_service.find_session_by_code(db, session_code)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if session.status != "active":
        raise HTTPException(status_code=409, detail=f"会话状态 {session.status}，无法继续")

    async def stream() -> AsyncIterator[bytes]:
        async for ev in chat_service.handle_user_message(db, session, payload.content, llm):
            yield _serialize_sse(ev["event"], ev["data"])

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{session_code}/restart", response_model=ChatStartResponse)
async def restart_chat(
    session_code: str,
    db: Session = Depends(get_db),
    llm: LLMClient = Depends(get_llm_client),
):
    old = chat_service.find_session_by_code(db, session_code)
    if old is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    if old.status == "active":
        chat_service.abandon_session(db, old)

    session = chat_service.create_session(db, old.customer_id)
    try:
        await chat_service.generate_opening(db, session, llm)
    except Exception as e:  # noqa: BLE001
        logger.warning("生成开场白失败", exc_info=e)   # 详情只进服务端日志
        raise HTTPException(status_code=503, detail=_AI_UNAVAILABLE) from e

    db.refresh(session)
    return ChatStartResponse(
        session_code=session.code,
        resumed=False,
        messages=[ChatMessageOut.model_validate(m) for m in session.messages],
    )
