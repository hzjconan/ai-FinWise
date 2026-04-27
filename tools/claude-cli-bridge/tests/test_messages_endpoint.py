"""/v1/messages 集成测试：mock subprocess 调用，断言 SSE 事件序列。"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from claude_cli_bridge import cli_runner
from claude_cli_bridge.main import app

ASK_TOOL = {
    "name": "ask_next_question",
    "input_schema": {
        "type": "object",
        "properties": {"content": {"type": "string"}},
        "required": ["content"],
    },
}


@pytest.fixture
def client():
    return TestClient(app)


def _patch_cli(monkeypatch, raw: str | None = None, exc: Exception | None = None):
    async def fake(prompt: str, *, timeout: float = 90.0) -> str:
        if exc is not None:
            raise exc
        return raw or ""

    monkeypatch.setattr(cli_runner, "run_claude_cli", fake)
    # messages.py 直接 import 了符号，需要把那边也替换
    from claude_cli_bridge import messages
    monkeypatch.setattr(messages, "run_claude_cli", fake)


def _parse_sse(body: str) -> list[dict]:
    events = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_name = None
        data_line = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("data: "):
                data_line = line[6:]
        events.append({"event": event_name, "data": json.loads(data_line) if data_line else None})
    return events


def test_messages_returns_anthropic_style_sse(client, monkeypatch):
    _patch_cli(monkeypatch, raw='{"tool_name":"ask_next_question","tool_input":{"content":"Q1"}}')

    resp = client.post("/v1/messages", json={
        "model": "claude-haiku-4-5-20251001",
        "system": "sys",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [ASK_TOOL],
        "stream": True,
    })

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(resp.text)
    types = [e["event"] for e in events]
    assert types[0] == "message_start"
    assert "content_block_start" in types
    assert "content_block_delta" in types
    assert types[-1] == "message_stop"

    block_start = next(e for e in events if e["event"] == "content_block_start")
    assert block_start["data"]["content_block"]["name"] == "ask_next_question"


def test_messages_emits_error_event_when_cli_fails(client, monkeypatch):
    _patch_cli(monkeypatch, exc=cli_runner.CLIRunError("CLI 超时"))

    resp = client.post("/v1/messages", json={
        "messages": [],
        "tools": [ASK_TOOL],
        "stream": True,
    })
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events[-1]["event"] == "error"
    assert "CLI 超时" in events[-1]["data"]["error"]["message"]


def test_messages_emits_error_when_output_unparseable(client, monkeypatch):
    _patch_cli(monkeypatch, raw="not json at all")

    resp = client.post("/v1/messages", json={
        "messages": [],
        "tools": [ASK_TOOL],
        "stream": True,
    })
    events = _parse_sse(resp.text)
    assert events[-1]["event"] == "error"
    assert events[-1]["data"]["error"]["type"] == "invalid_response"


def test_messages_rejects_non_streaming(client):
    resp = client.post("/v1/messages", json={
        "messages": [], "tools": [ASK_TOOL], "stream": False,
    })
    assert resp.status_code == 501


def test_messages_rejects_no_tools(client):
    resp = client.post("/v1/messages", json={"messages": [], "tools": [], "stream": True})
    assert resp.status_code == 400


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}
