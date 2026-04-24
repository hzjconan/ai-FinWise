"""AnthropicLLMClient 测试：用 duck-typed fake 替代 AsyncAnthropic 客户端。

为什么不用 respx：SDK 内部可能换 HTTPX → httpx-sse 的 transport 或事件解析逻辑；
直接在 client.messages.stream 边界打 fake 更稳，也更贴近我们实际关心的契约。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.llm.anthropic_client import AnthropicLLMClient
from app.services.llm.events import TextDelta, ToolResult


# ---------- fake SDK ----------

@dataclass
class FakeBlock:
    type: str
    name: str | None = None
    input: dict | None = None


class FakeStream:
    def __init__(self, events: list, final_blocks: list[FakeBlock]):
        self._events = events
        self._final = SimpleNamespace(content=final_blocks)
        self.captured_kwargs: dict[str, Any] | None = None

    async def __aiter__(self):
        for ev in self._events:
            yield ev

    async def get_final_message(self):
        return self._final


class FakeStreamCM:
    def __init__(self, stream: FakeStream):
        self._stream = stream

    async def __aenter__(self):
        return self._stream

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeMessages:
    def __init__(self, stream: FakeStream):
        self._stream = stream
        self.call_kwargs: dict[str, Any] | None = None

    def stream(self, **kwargs: Any) -> FakeStreamCM:
        self.call_kwargs = kwargs
        return FakeStreamCM(self._stream)


class FakeClient:
    def __init__(self, stream: FakeStream):
        self.messages = FakeMessages(stream)


def _text_delta_event(text: str):
    return SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="text_delta", text=text),
    )


# ---------- helpers ----------

def _run(coro):
    return asyncio.run(coro)


async def _collect(agen):
    return [ev async for ev in agen]


# ---------- tests ----------

def test_stream_chat_yields_text_deltas_and_tool_result():
    stream = FakeStream(
        events=[_text_delta_event("你好"), _text_delta_event("，")],
        final_blocks=[
            FakeBlock(type="text"),
            FakeBlock(
                type="tool_use",
                name="ask_next_question",
                input={"content": "请问您有投资经验吗？"},
            ),
        ],
    )
    client = AnthropicLLMClient(client=FakeClient(stream))  # type: ignore[arg-type]

    events = _run(_collect(client.stream_chat(system="sys", messages=[], tools=[])))

    deltas = [e for e in events if isinstance(e, TextDelta)]
    tools = [e for e in events if isinstance(e, ToolResult)]
    assert [d.text for d in deltas] == ["你好", "，"]
    assert len(tools) == 1
    assert tools[0].name == "ask_next_question"
    assert tools[0].input == {"content": "请问您有投资经验吗？"}


def test_stream_chat_no_tool_use_yields_only_deltas():
    stream = FakeStream(
        events=[_text_delta_event("only text")],
        final_blocks=[FakeBlock(type="text")],
    )
    client = AnthropicLLMClient(client=FakeClient(stream))  # type: ignore[arg-type]
    events = _run(_collect(client.stream_chat(system="", messages=[], tools=[])))
    assert [type(e).__name__ for e in events] == ["TextDelta"]


def test_stream_chat_takes_first_tool_use_only():
    stream = FakeStream(
        events=[],
        final_blocks=[
            FakeBlock(type="tool_use", name="ask_next_question", input={"content": "Q"}),
            FakeBlock(type="tool_use", name="conclude_assessment", input={}),
        ],
    )
    client = AnthropicLLMClient(client=FakeClient(stream))  # type: ignore[arg-type]
    events = _run(_collect(client.stream_chat(system="", messages=[], tools=[])))
    tools = [e for e in events if isinstance(e, ToolResult)]
    assert len(tools) == 1
    assert tools[0].name == "ask_next_question"


def test_stream_chat_forwards_kwargs_to_sdk():
    fake = FakeClient(FakeStream(events=[], final_blocks=[]))
    client = AnthropicLLMClient(
        client=fake,  # type: ignore[arg-type]
        model="claude-opus-4-7",
        max_tokens=512,
    )
    _run(_collect(client.stream_chat(
        system="S",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"name": "t"}],
    )))
    assert fake.messages.call_kwargs is not None
    kw = fake.messages.call_kwargs
    assert kw["model"] == "claude-opus-4-7"
    assert kw["max_tokens"] == 512
    assert kw["system"] == "S"
    assert kw["messages"] == [{"role": "user", "content": "hi"}]
    assert kw["tools"] == [{"name": "t"}]


# ---------- factory ----------

def test_factory_returns_anthropic_client_when_provider_is_api(monkeypatch):
    from app.services.llm.factory import get_llm_client
    from app.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "api")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")

    client = get_llm_client()
    assert isinstance(client, AnthropicLLMClient)


def test_factory_raises_on_mock_provider(monkeypatch):
    from app.services.llm.factory import get_llm_client
    from app.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")
    with pytest.raises(NotImplementedError):
        get_llm_client()


def test_factory_raises_on_unknown_provider(monkeypatch):
    from app.services.llm.factory import get_llm_client
    from app.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "bogus")
    with pytest.raises(ValueError):
        get_llm_client()
