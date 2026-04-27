"""伪造 Anthropic Messages 流式 SSE 事件。

我们只发 tool_use 一种 content_block——业务侧的 AnthropicLLMClient 会从
final_message 取 tool_use，所以严格遵循官方事件序列即可：

  message_start
    content_block_start (type=tool_use, name, id, input={})
      content_block_delta (type=input_json_delta, partial_json="...")
      ...
    content_block_stop
  message_delta (stop_reason=tool_use)
  message_stop
"""
import json
import secrets
from collections.abc import Iterable

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def emit_tool_use_stream(
    *,
    tool_name: str,
    tool_input: dict,
    model: str = DEFAULT_MODEL,
    chunk_size: int = 32,
) -> Iterable[bytes]:
    """生成完整的 SSE 字节序列。

    chunk_size 控制 input_json_delta 切块大小，制造流式观感。
    """
    msg_id = f"msg_{secrets.token_hex(6)}"
    block_id = f"toolu_{secrets.token_hex(6)}"

    yield _sse(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": msg_id,
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": model,
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        },
    )

    yield _sse(
        "content_block_start",
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": block_id,
                "name": tool_name,
                "input": {},
            },
        },
    )

    full_json = json.dumps(tool_input, ensure_ascii=False)
    for i in range(0, len(full_json), chunk_size):
        partial = full_json[i : i + chunk_size]
        yield _sse(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": partial},
            },
        )

    yield _sse(
        "content_block_stop",
        {"type": "content_block_stop", "index": 0},
    )

    yield _sse(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use", "stop_sequence": None},
            "usage": {"output_tokens": 0},
        },
    )

    yield _sse("message_stop", {"type": "message_stop"})


def emit_error(message: str, *, error_type: str = "api_error") -> bytes:
    return _sse(
        "error",
        {"type": "error", "error": {"type": error_type, "message": message}},
    )


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()
