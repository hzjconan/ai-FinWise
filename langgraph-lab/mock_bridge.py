"""教学用 mock bridge —— 只模拟"合法的 Anthropic 响应结构"，让 ChatAnthropic 能跑通。

背景：真 bridge（backend/scratch）只支持 stream=true（SSE），非流式 501；而 langchain 的
ChatAnthropic.invoke() 默认走【非流式】、期望一个完整 Message JSON → 两边对不上就崩
（'str' object has no attribute 'model_dump'，见 langgraph-notes）。

这个 mock【不接真模型】，只做一件事：收到 POST /v1/messages，按请求里的工具名返回一个
【结构合法的、非流式的】Anthropic Message JSON，content 里塞一个 tool_use 块 + 写死的假 input。
够 ChatAnthropic 解析成 AIMessage.tool_calls，满足 lg_04 学 langchain 接口的教学目的。

起服务：cd langgraph-lab && .venv/bin/uvicorn mock_bridge:app --port 8788
（端口 8788，避开真 bridge 的 8787）
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI()

# 按工具名返回写死的假 input（离线、确定性——教学用，不接真模型）
CANNED_INPUT: dict[str, dict] = {
    "assess": {"dimensions": {"experience": 4, "loss_tolerance": 3, "income_stability": 5,
                              "investment_horizon": 3, "volatility_tolerance": 4}},
    "recommend": {"recommended_code": "P-R4", "reason": "（mock）候选中与该等级最匹配的一款。"},
}


class MessagesRequest(BaseModel):
    model: str = "claude-haiku-4-5-20251001"
    system: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    max_tokens: int = 1024
    stream: bool = False


@app.post("/v1/messages")
async def create_message(req: MessagesRequest):
    # 挑第一个工具，回一个 tool_use 块（bridge 约定：模型总以工具形式作答）
    tool_name = req.tools[0]["name"] if req.tools else "unknown"
    tool_input = CANNED_INPUT.get(tool_name, {})

    # ★ 这就是"合法的 Anthropic 非流式 Message 响应结构"——ChatAnthropic 期望的形状
    message = {
        "id": f"msg_mock_{uuid.uuid4().hex[:8]}",
        "type": "message",
        "role": "assistant",
        "model": req.model,
        "content": [{
            "type": "tool_use",
            "id": f"toolu_mock_{uuid.uuid4().hex[:8]}",
            "name": tool_name,
            "input": tool_input,
        }],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }
    return JSONResponse(message)


@app.get("/healthz")
async def healthz():
    return {"ok": True}
