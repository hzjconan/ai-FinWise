"""阶段 1 · 练习 03：上下文即内存——模型是无状态的

学习目标（最反直觉、也最重要的一点）：
- LLM 没有记忆。它「记得」的一切，都是你在 messages 数组里**重新喂**给它的。
- 用一个对照实验证明：带历史 vs 不带历史，模型的表现天差地别。

运行：
    cd backend && .venv/bin/python scratch/s1_03_multiturn.py
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


async def ask(client, messages: list[dict]) -> str:
    async with client.messages.stream(
        model=MODEL,
        system="你是助手。回答尽量简短。",
        messages=messages,
        tools=[ANSWER_TOOL],
        max_tokens=512,
    ) as stream:
        final = await stream.get_final_message()
    for block in final.content:
        if getattr(block, "type", None) == "tool_use":
            return block.input.get("answer", "")
    return "(无回答)"


async def main() -> None:
    client = make_client()

    # 场景 A：带完整历史。模型能「记住」我叫 阿康。
    section("A. 带历史（messages 里含之前的对话）")
    history = [
        {"role": "user", "content": "你好，我叫阿康，是个后端工程师。"},
        {"role": "assistant", "content": "你好阿康！很高兴认识你。"},
        {"role": "user", "content": "我叫什么名字？我的职业是什么？"},
        
        # 练习1 加几轮，问一个只有靠前几轮才知道答案的问题
        {"role": "assistant", "content": "你叫阿康，职业是后端工程师。"},
        {"role": "user", "content": "我喜欢吃青菜"},
        {"role": "assistant", "content": "好的，记住啦，阿康喜欢吃青菜"},
        {"role": "user", "content": "我喜欢打羽毛球"},
        {"role": "assistant", "content": "好的，阿康！记住啦——你喜欢打羽毛球。"},
        {"role": "user", "content": "我喜欢什么食物？"}
    ]
    # 练习2 砍历史，看模型「何时」开始失忆——并排对比"还记得的"vs"刚失忆的"两刀。
    # 「青菜」这条食物信息只在 [4][5] 两轮（=倒数第 5、第 4 条）：
    #   history[-5:] 含 [4] → 还记得；history[-3:] 砍到 [6:] → 不含青菜 → 失忆。
    # 转折点就在 -4 与 -3 之间。
    print("→ 完整历史      :", await ask(client, history))
    print("→ 后5条(含青菜) :", await ask(client, history[-5:]))   # 应答对
    print("→ 后3条(砍青菜) :", await ask(client, history[-3:]))   # 应失忆

    # 场景 B：不带历史，直接问同一个问题。模型无从得知。
    section("B. 不带历史（只发最后一个问题）")
    no_history = [
        {"role": "user", "content": "我叫什么名字？我的职业是什么？"},
    ]
    print("→", await ask(client, no_history))

    section("结论")
    print("A 能答对、B 答不出——因为模型的『记忆』完全来自你传的 messages。")
    print("这正是仓库 chat_service.build_api_messages() 每轮都要把历史重新拼进去的原因。")

    # ---- 练习 TODO ----
    # 1. 在 A 的历史里再加几轮，问一个只有靠前几轮才知道答案的问题。
    # 2. 把 A 历史砍到只剩最后一轮，看它何时开始「失忆」——直观感受 context window。


asyncio.run(main())
