"""阶段 2 · 练习 01：prompt 即代码——玩转仓库真实的风险评估 prompt

学习目标：
- 看懂仓库怎么把「5 个维度 + 评分锚点」组织成 system prompt（prompts/ 目录）。
- 亲手改一处 prompt，观察模型行为如何变化——建立「prompt 是可调的代码」的直觉。
- 复用仓库真实的 TOOLS_SCHEMA（ask_next_question / conclude_assessment）。

运行：
    cd backend && .venv/bin/python scratch/s2_01_prompt_shaping.py

前置：bridge 已启动。
"""
from __future__ import annotations

import asyncio

from _bridge import BridgeParseError, call_tool, make_client, section

# 复用仓库业务代码里的真实 prompt 与工具定义（_bridge 已把 backend 加进 sys.path）。
from app.services.chat_service import TOOLS_SCHEMA
from app.services.llm.prompts import load_system_prompt


async def run_one_turn(client, system: str, messages: list[dict]) -> None:
    try:
        blocks = await call_tool(client, system=system, messages=messages, tools=TOOLS_SCHEMA)
    except BridgeParseError as e:
        # 观察到的失败模式：模型输出了非法 JSON，bridge 解析失败（真实 API 不会这样）。
        print("⚠️ 失败模式（格式跑偏）——bridge 解析不了模型输出：")
        print("  ", str(e)[:300])
        return
    for b in blocks:
        print("调用工具 :", b["name"])
        print("参数     :", b["input"])


async def main() -> None:
    client = make_client()
    system = load_system_prompt()

    section("真实 system prompt（前 600 字）")
    print(system[:600], "...\n")

    section("开场（空历史）——模型应调用 ask_next_question 抛出第一个问题")
    await run_one_turn(client, system, messages=[])

    section("模拟客户回答后，模型如何继续")
    messages = [
        {"role": "assistant", "content": "为了给你合适的建议，能先聊聊你的投资经验吗？"},
        {"role": "user", "content": "我炒股 5 年了，能接受一定波动，但接受不了本金腰斩。"},
    ]
    await run_one_turn(client, system, messages)

    # ---- 练习 TODO（这才是重点，动手改）----
    # 1. 打开 backend/prompts/risk_assessment_dimensions.yaml，改某个维度的 anchors 描述，
    #    重跑本脚本，观察 conclude 时的评分倾向是否变化。
    # 2. 在 backend/prompts/risk_assessment_system.md 里加一条约束，比如
    #    「每个问题不超过 20 字」，重跑，看 ask_next_question 的 content 是否变短。
    # 3. 故意把上面 user 的回答改得很模糊（"随便吧"），看模型是继续追问还是硬下结论。
    #    —— 这就是在观察 prompt 对「失败模式」的防御力。


asyncio.run(main())
