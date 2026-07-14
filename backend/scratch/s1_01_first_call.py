"""阶段 1 · 练习 01：你的第一次 LLM 调用（结构化输出）

学习目标：
- 用官方 anthropic SDK 发起一次调用，理解四个核心入参：model / system / messages / tools。
- 理解「结构化输出」：模型的回答不是自由文本，而是一次符合 tool schema 的 JSON 调用。
  （这正是阶段 3 agent 的地基——tool 既能做输出格式，也能做真正的工具。）

运行：
    1. 另开终端启动 bridge：bash backend/scratch/run_bridge.sh
    2. cd backend && .venv/bin/python scratch/s1_01_first_call.py

对照真实 API 的差异见文末注释。
"""
from __future__ import annotations

import asyncio

from _bridge import MODEL, make_client, section

# --- 定义一个最简单的「工具」：让模型把答案填进 answer 字段 ---
# input_schema 用的是标准 JSON Schema。模型必须返回符合它的 JSON。
ANSWER_TOOL = {
    "name": "answer",
    "description": "用一段话回答用户的问题。",
    "input_schema": {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    },
}


async def main() -> None:
    client = make_client()

    # system：设定模型的角色/规则，不属于对话本身。
    system = "你是一位耐心的编程导师，擅长用类比向工程师解释 AI 概念。"

    # messages：对话历史。role 只能是 user / assistant。
    messages = [
        {"role": "user", "content": "用一个类比向有经验的后端工程师解释：什么是 LLM 的 context window？"}
    ]

    section("请求参数")
    print("model   :", MODEL)
    print("system  :", system)
    print("messages:", messages)

    # bridge 只支持 stream=true，所以用 .stream() 上下文管理器。
    # 这段写法和仓库业务代码 app/services/llm/anthropic_client.py 完全一致。
    async with client.messages.stream(
        model=MODEL,
        system=system,
        messages=messages,
        tools=[ANSWER_TOOL],
        max_tokens=1024,
    ) as stream:
        # 流结束后，从 final_message 里取模型最终产出的 tool_use 块。
        final = await stream.get_final_message()

    section("模型返回（结构化）")
    for block in final.content:
        if getattr(block, "type", None) == "tool_use":
            print("工具名 :", block.name)
            print("参数   :", dict(block.input))
            print()
            print("→ answer 字段内容：")
            print(block.input.get("answer"))

    # ---- 练习 TODO（改完重跑，观察变化）----
    # 1. 把 system 改成「你只会用一句话回答」，看回答长度是否变化。
    # 2. 给 messages 再加一轮 assistant + user，模拟多轮（下个脚本会专门练）。
    # 3. 把 ANSWER_TOOL 的 schema 加一个必填字段 `analogy_target`（类比对象），
    #    看模型是否会乖乖填上——这就是 schema 约束输出的威力。


asyncio.run(main())

# ============================================================
# 对照真实 API（需 ANTHROPIC_API_KEY）时的差异：
# - 不带 tools 也能调，模型会直接返回自由文本（text block）。
# - 可以用 stream=False 的 client.messages.create(...) 一次拿完整结果。
# - final.usage.input_tokens / output_tokens 是真实 token 数（bridge 里是 0）。
# - temperature 生效（bridge 忽略）。
# 换真实 API：设 ANTHROPIC_API_KEY，并去掉 _bridge.py 里的 base_url。
# ============================================================
