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
         #TODO 3的练习
        {"role": "user", "content": "我炒股 5 年了，能接受一定波动，但接受不了本金腰斩。"},
        #{"role": "user", "content": "随便吧，我也不知道，无所谓"},
       
        #TODO 1的练习
        {"role": "assistant", "content": "5 年股龄很扎实。那亏损 20% 左右您能接受吗？"},
        {"role": "user", "content": "不能"},
        {"role": "assistant", 'content': '明白，20% 太多了。那亏 10% 左右能接受吗？'},
        {"role": "user", "content": "差不多"},
        {"role": "assistant", 'content': '好的，10%左右可以。那这笔钱您打算投多久呢？'},
        {"role": "user", "content": "3到5年"},
        {"role": "assistant", 'content': '好的，3到5年挺好。那您目前收入稳定吗？'},
        {"role": "user", "content": "无工资收入"},
        {'content': '了解。那您有其他收入来源或应急储备吗？'},
        {"role": "user", "content": "暂时没有其他收入来源，只有存款"},
        {'content': '了解，主要靠存款。如果账户短期跌了10%，您会怎么做？'},
        {"role": "user", "content": "会再观望一会，或者止损"},
        # 这是修改risk_assessment_dimensions.yaml前模型最后的回复
        # {'content': '感谢您的耐心配合，评估已经完成。综合来看，您的风险偏好为 C3 平衡型：您有较丰富的投资经验，能接受 10% 左右的阶段性波动，但不希望出现更大的亏损。考虑到您目前没有固定收入、主要依靠存款，建议您在做任何投资安排时预留充足的应急资金。后续如有需要，可以随时重新评估。', 'risk_preference': 'C3', 'summary': '客户有 5 年股票投资经验，熟悉市场波动（经验 4 分）；可接受约 10% 的阶段性亏损，明确拒绝 20% 及以上回撤（损失承受 3 分）；目前无工资收入、无其他收入来源，仅有存款储备（收入稳定性 1 分）；计划投资期限 3 至 5 年（期限 4 分）；账户下跌 10% 时会先观望、必要时止损，心态相对平稳（波动态度 3 分）。五维均值 3.0，处于平衡型区间，综合评定为 C3。', 'dimensions': {'experience': 4, 'loss_tolerance': 3, 'income_stability': 1, 'investment_horizon': 4, 'volatility_tolerance': 3}}
        # 这是修改risk_assessment_dimensions.yaml后模型最后的回复
        # {'content': '感谢您的耐心配合！结合我们的交流，我已完成对您的风险评估，结论为 C5（激进型）。这只是基于问卷的参考画像，实际配置时还请结合您的真实资金安排综合考量。如需调整，随时可以再来聊。', 'risk_preference': 'C5', 'summary': '客户炒股5年、熟悉市场波动（投资经验5）；明确拒绝20%亏损，但可接受约10%的阶段性浮亏，已超过8%锚点（损失承受5）；计划投资3-5年长期资金（投资期限5）；目前无工资收入，仅有存款作为应急储备，匹配‘无收入有储备’锚点（收入稳定性5）；账户下跌10%时会先观望、必要时止损，介于‘关注不操作’之间（波动态度3）。五维均值约4.6，落入C5区间。需提示：客户主观风险偏好偏谨慎（不接受本金腰斩），与锚点评分存在偏差，建议人工复核。', 'dimensions': {'experience': 5, 'loss_tolerance': 5, 'income_stability': 5, 'investment_horizon': 5, 'volatility_tolerance': 3}}
    ]
    await run_one_turn(client, system, messages)

    # ---- 练习 TODO（这才是重点，动手改）----
    # ⚠️ 本次练习曾改动业务 prompt（backend/prompts/），做完已把原文件复原；
    #    改动过的版本存档在 backend/scratch/s2_01_experiment_prompts/（含 README）。
    #    下面 TODO#1/#2 的观察结果，都是用那份「改动版」prompt 跑出来的。
    #
    # 1. 打开 backend/prompts/risk_assessment_dimensions.yaml，改某个维度的 anchors 描述，
    #    重跑本脚本，观察 conclude 时的评分倾向是否变化。
    #    ✅ 结果：把锚点改激进（如损失承受 8%以上=5、无收入=5）后，同一段客户对话（上面 messages）
    #       的 conclude 从 C3(均值3.0) 变成 C5(均值4.6)——客户一字没改，只因「标尺」变了。
    #       改前/改后的完整 conclude 见上面 L67-70 注释。深层洞察：锚点=评分 rubric，
    #       压扁刻度会把谨慎客户误判成激进（模型自己在 summary 里都提示了这个「张力」）。
    # 2. 在 backend/prompts/risk_assessment_system.md 里加一条约束，比如
    #    「每个问题不超过 20 字」，重跑，看 ask_next_question 的 content 是否变短。
    #    ✅ 结果：开场问题从约 150 字缩到约 28 字（"…您以前买过哪些理财产品？"）。
    #       但只是变短、并未严格 ≤20 字——再次印证：prompt 指令是软约束，尽力遵守不保证精确。
    # 3. 故意把上面 user 的回答改得很模糊（"随便吧"），看模型是继续追问还是硬下结论。
    #    —— 这就是在观察 prompt 对「失败模式」的防御力。
    #    ✅ 结果：用短历史 [assistant 问一句, user "随便吧，我也不知道，无所谓"] 单独跑，
    #       模型继续 ask_next_question：「没关系～平时钱多放余额宝还是股票？」——
    #       没有硬 conclude，还主动降低回答门槛（改成二选一）。system.md 里
    #       「信息不足不要提前收尾」这条约束成功防御了「客户敷衍」这种失败模式。


asyncio.run(main())
