from collections.abc import AsyncIterator
from typing import Callable

from app.services.llm.events import LLMEvent


class MockLLMClient:
    """脚本化的 LLM，测试与 dev 阶段使用。

    使用方式：把若干「响应」（每个响应是 LLMEvent 序列，或抛异常的 callable）压入 script，
    每次调用 stream_chat 弹出一个作为本次响应。
    """

    def __init__(self, script: list | None = None):
        # 每项为：list[LLMEvent] 表示正常响应；callable 抛出异常表示失败
        self.script: list[list[LLMEvent] | Callable] = list(script or [])
        self.calls: list[dict] = []  # 记录每次调用参数供断言

    def push(self, events: list[LLMEvent] | Callable) -> None:
        self.script.append(events)

    async def stream_chat(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict],
    ) -> AsyncIterator[LLMEvent]:
        self.calls.append({"system": system, "messages": messages, "tools": tools})

        if not self.script:
            raise RuntimeError("MockLLMClient script 为空，测试未压入响应")

        item = self.script.pop(0)
        if callable(item):
            # 抛异常模拟失败
            item()
            return  # pragma: no cover
        for ev in item:
            yield ev
