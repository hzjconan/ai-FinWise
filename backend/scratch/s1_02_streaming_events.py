"""阶段 1 · 练习 02：看清流式（streaming）的底层事件

学习目标：
- 理解流式响应不是「一段文本」，而是一串**事件**（message_start、content_block_delta…）。
- 看到模型的 JSON 是**一小段一小段**（input_json_delta）拼出来的——这就是仓库里
  对话气泡「逐字冒出来」的原理（app/services/llm/anthropic_client.py 就在处理这些事件）。
- 观察 usage 字段：bridge 里是 0（假的）；真实 API 里是真实 token 数。

运行：
    cd backend && .venv/bin/python scratch/s1_02_streaming_events.py
"""
from __future__ import annotations

import asyncio

from _bridge import MODEL, make_client, section

ANSWER_TOOL = {
    "name": "answer",
    "description": "回答用户问题。",
    "input_schema": {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    },
}


async def main() -> None:
    client = make_client()
    messages = [{"role": "user", "content": "列举 3 个 Python 的优点，每个一句话。"}]

    section("逐个打印流事件（event.type）")
    accumulated = ""
    async with client.messages.stream(
        model=MODEL,
        system="你是简洁的技术助手。",
        messages=messages,
        tools=[ANSWER_TOOL],
        max_tokens=1024,
    ) as stream:
        async for event in stream:
            etype = event.type
            # 只有 input_json_delta 携带真正的增量内容
            delta = getattr(event, "delta", None)
            if delta is not None and getattr(delta, "type", None) == "input_json_delta":
                piece = getattr(delta, "partial_json", "")
                accumulated += piece
                print(f"  [{etype}] +{piece!r}")
            else:
                print(f"  [{etype}]")

        final = await stream.get_final_message()

    section("拼接出来的完整 JSON（就是工具入参）")
    print(accumulated)

    section("token 用量")
    print("input_tokens :", final.usage.input_tokens, " ← bridge 恒为 0；真实 API 是真数字")
    print("output_tokens:", final.usage.output_tokens)

    # ---- 练习 TODO ----
    # 1. 把 max_tokens 改成 20，观察长回答是否被截断（stop_reason 会变）。
    # 2. 数一下 content_block_delta 事件出现了多少次——这就是「流」的颗粒度。
    # 3. 思考：为什么前端要处理这些增量事件，而不是等最终结果？（答案：首字延迟/体验）


asyncio.run(main())
