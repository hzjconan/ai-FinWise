from collections.abc import AsyncIterator
from typing import Protocol

from app.services.llm.events import LLMEvent


class LLMClient(Protocol):
    """LLM 调用抽象。P1 使用 MockLLMClient；P2 由 Anthropic SDK 实现。

    失败语义：
    - 瞬时故障（网络、5xx、解析错误）应直接抛异常，由上层做重试
    - 结构性错误（比如输入不合法）可以通过 yield LLMError 上报
    """

    async def stream_chat(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict],
    ) -> AsyncIterator[LLMEvent]:
        ...
