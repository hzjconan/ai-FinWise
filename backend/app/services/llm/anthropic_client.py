"""基于官方 Anthropic SDK 的 LLMClient 实现。

与 dev 无差别：SDK 自动读取 ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL。
- 生产：默认连官方 API
- dev（配合 P2' bridge）：ANTHROPIC_BASE_URL=http://localhost:8787/v1

失败语义（契合 base.LLMClient 约定）：
- 瞬时故障（APIConnectionError、APIStatusError 5xx）→ 抛异常，由 chat_service 重试
- 结构性错误（BadRequestError、无 tool_use）→ 也抛异常，上层统一按瞬时处理

不包装 LLMError 事件：真实 API 的错误都是 HTTP 层面的，用异常语义更直白。
"""
from collections.abc import AsyncIterator
from typing import Any

from anthropic import AsyncAnthropic, AuthenticationError, BadRequestError, PermissionDeniedError

from app.services.llm.base import NonRetryableLLMError
from app.services.llm.events import LLMEvent, TextDelta, ToolResult

# L1：LLM 调用超时（秒）。挂起的调用不会无限等——超时抛异常、计入可重试。
DEFAULT_TIMEOUT_SECONDS = 30.0

# R1：这些 Anthropic 异常是【确定性错误】，重试也一样错 → 归为不可重试。
_NON_RETRYABLE = (BadRequestError, AuthenticationError, PermissionDeniedError)


class AnthropicLLMClient:
    def __init__(
        self,
        client: AsyncAnthropic | None = None,
        *,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 1024,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        # 允许注入客户端以便测试；生产走默认构造（读环境变量）。L1：默认带超时。
        self._client = client or AsyncAnthropic(timeout=timeout)
        self._model = model
        self._max_tokens = max_tokens

    async def stream_chat(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict],
    ) -> AsyncIterator[LLMEvent]:
        try:
            async for ev in self._stream(system=system, messages=messages, tools=tools):
                yield ev
        except _NON_RETRYABLE as e:
            # R1：确定性错误 → 包成 provider 无关的不可重试标记，让上层立即抛不重试
            raise NonRetryableLLMError(str(e)) from e

    async def _stream(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict],
    ) -> AsyncIterator[LLMEvent]:
        async with self._client.messages.stream(
            model=self._model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=self._max_tokens,
        ) as stream:
            # 1) 流式吐 text_delta
            async for event in stream:
                if event.type == "content_block_delta" and getattr(
                    event.delta, "type", None
                ) == "text_delta":
                    text = getattr(event.delta, "text", "")
                    if text:
                        yield TextDelta(text=text)

            # 2) 流结束后从 final_message 提取 tool_use（取第一个）
            final = await stream.get_final_message()
            for block in final.content:
                if getattr(block, "type", None) == "tool_use":
                    input_dict: dict[str, Any] = dict(block.input) if block.input else {}
                    yield ToolResult(name=block.name, input=input_dict, id=getattr(block, "id", ""))
                    return
