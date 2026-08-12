from collections.abc import AsyncIterator
from typing import Protocol

from app.services.llm.events import LLMEvent


class NonRetryableLLMError(Exception):
    """provider 无关的"不可重试"标记异常。

    由具体 client（如 AnthropicLLMClient）把【确定性错误】（400 参数非法、认证失败等
    ——重试也一样错）包成本异常抛出；上层 _call_llm_with_retry 见到它【立即抛、不重试】，
    避免白白重试浪费一次调用/费用/等待。其余异常视为可重试（网络、5xx、超时、限流）。

    ★ 设计：provider 特有的异常分类下沉到 client 层（它才知道 Anthropic 的异常类）；
      chat_service 只认这个抽象标记，保持 provider 无关。"""


class LLMClient(Protocol):
    """LLM 调用抽象。P1 使用 MockLLMClient；P2 由 Anthropic SDK 实现。

    失败语义：
    - 可重试（网络、5xx、超时、限流）→ 抛普通异常，由上层退避后重试
    - 不可重试（400 参数非法、认证失败）→ 抛 NonRetryableLLMError，上层立即抛不重试
    - 结构性错误（比如输入不合法）也可通过 yield LLMError 上报
    """

    async def stream_chat(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict],
    ) -> AsyncIterator[LLMEvent]:
        ...
