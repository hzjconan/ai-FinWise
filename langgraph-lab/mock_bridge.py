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
    "search_products": {"risk_level": "C4"},   # lg_05 ReAct agent 用
}


def _has_tool_result(messages: list[dict]) -> bool:
    """请求的 messages 里有没有 tool_result 块（= 工具已执行、结果回喂回来了）。
    有 → 说明是 ReAct loop 的第二轮，该收尾了（返回纯文本 end_turn）。"""
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                return True
    return False


class MessagesRequest(BaseModel):
    model: str = "claude-haiku-4-5-20251001"
    system: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    max_tokens: int = 1024
    stream: bool = False


@app.post("/v1/messages")
async def create_message(req: MessagesRequest):
    base = {"id": f"msg_mock_{uuid.uuid4().hex[:8]}", "type": "message", "role": "assistant",
            "model": req.model, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10}}

    # ★ ReAct loop 支持：若 messages 里已有 tool_result（工具执行过了）→ 返回纯文本收尾（end_turn），
    #   让 create_react_agent 的循环自然停；否则返回 tool_use（第一轮，让它去调工具）。
    if _has_tool_result(req.messages):
        return JSONResponse({**base, "stop_reason": "end_turn",
                             "content": [{"type": "text", "text": "（mock）已根据查询结果完成，推荐 P-R4 成长精选混合。"}]})

    tool_name = req.tools[0]["name"] if req.tools else "unknown"
    return JSONResponse({**base, "stop_reason": "tool_use",
                         "content": [{"type": "tool_use", "id": f"toolu_mock_{uuid.uuid4().hex[:8]}",
                                      "name": tool_name, "input": CANNED_INPUT.get(tool_name, {})}]})


@app.get("/healthz")
async def healthz():
    return {"ok": True}
