"""POST /v1/messages 端点：Anthropic Messages API 子集。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from claude_cli_bridge.cli_runner import CLIRunError, run_claude_cli
from claude_cli_bridge.prompt_builder import build_prompt
from claude_cli_bridge.sse_emitter import DEFAULT_MODEL, emit_error, emit_tool_use_stream
from claude_cli_bridge.tool_parser import ToolParseError, parse_tool_call

router = APIRouter()


class MessagesRequest(BaseModel):
    model: str = DEFAULT_MODEL
    system: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    max_tokens: int = 1024
    stream: bool = True


@router.post("/messages")
async def create_message(req: MessagesRequest):
    if not req.stream:
        # 业务侧的 AnthropicLLMClient 永远走 stream=true；非流式留给后续按需实现
        raise HTTPException(status_code=501, detail="bridge 仅实现 stream=true")
    if not req.tools:
        raise HTTPException(status_code=400, detail="bridge 要求至少一个 tool 定义")

    allowed = [t["name"] for t in req.tools]
    prompt = build_prompt(
        system=req.system or "",
        messages=req.messages,
        tools=req.tools,
    )

    async def stream():
        try:
            raw = await run_claude_cli(prompt)
        except CLIRunError as e:
            yield emit_error(str(e), error_type="api_error")
            return

        try:
            tool_name, tool_input = parse_tool_call(raw, allowed)
        except ToolParseError as e:
            yield emit_error(f"模型输出解析失败：{e}", error_type="invalid_response")
            return

        for chunk in emit_tool_use_stream(
            tool_name=tool_name, tool_input=tool_input, model=req.model
        ):
            yield chunk

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
