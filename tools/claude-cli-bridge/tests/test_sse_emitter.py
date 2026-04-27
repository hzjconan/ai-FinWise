import json

from claude_cli_bridge.sse_emitter import emit_error, emit_tool_use_stream


def _decode_events(chunks: list[bytes]) -> list[dict]:
    text = b"".join(chunks).decode("utf-8")
    events: list[dict] = []
    for block in text.split("\n\n"):
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


def test_tool_use_stream_event_sequence():
    chunks = list(emit_tool_use_stream(
        tool_name="ask_next_question",
        tool_input={"content": "请问您能接受多大跌幅？"},
        chunk_size=5,
    ))
    events = _decode_events(chunks)
    types = [e["event"] for e in events]

    assert types[0] == "message_start"
    assert types[1] == "content_block_start"
    assert types[-3] == "content_block_stop"
    assert types[-2] == "message_delta"
    assert types[-1] == "message_stop"
    # 中间至少有一个 input_json_delta
    deltas = [e for e in events if e["event"] == "content_block_delta"]
    assert len(deltas) >= 1
    for d in deltas:
        assert d["data"]["delta"]["type"] == "input_json_delta"

    # 拼回完整 JSON 必须等于原 input
    full = "".join(d["data"]["delta"]["partial_json"] for d in deltas)
    assert json.loads(full) == {"content": "请问您能接受多大跌幅？"}


def test_tool_use_stream_carries_tool_name_in_block_start():
    chunks = list(emit_tool_use_stream(tool_name="conclude_assessment", tool_input={}))
    events = _decode_events(chunks)
    block_start = next(e for e in events if e["event"] == "content_block_start")
    assert block_start["data"]["content_block"]["name"] == "conclude_assessment"
    assert block_start["data"]["content_block"]["type"] == "tool_use"


def test_message_delta_stop_reason_is_tool_use():
    chunks = list(emit_tool_use_stream(tool_name="ask_next_question", tool_input={"content": "x"}))
    events = _decode_events(chunks)
    msg_delta = next(e for e in events if e["event"] == "message_delta")
    assert msg_delta["data"]["delta"]["stop_reason"] == "tool_use"


def test_emit_error_format():
    chunk = emit_error("CLI 超时", error_type="api_error")
    events = _decode_events([chunk])
    assert events[0]["event"] == "error"
    assert events[0]["data"]["error"]["message"] == "CLI 超时"
    assert events[0]["data"]["error"]["type"] == "api_error"
