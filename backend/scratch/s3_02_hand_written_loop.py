"""阶段 3 · 练习 02（B）：你亲手写 agent loop —— 产品推荐 agent

这次换你写核心。前面 s3_01 是我搭好的；这里我只给「除 loop 主体外的一切」
（工具定义 / 假数据库 / 执行器 / main），run_agent 里的循环**由你从零写**。

场景（比计算器真实）：一个产品推荐 agent。
- 模型**不可能凭空知道**你的产品库 → 它**必须**调 search_products 才能拿到候选产品。
  （这正是「给 agent 真正需要、自己办不到的工具」的正例——不用逼它用。）
- 拿到产品列表后，模型挑一款，调终态工具 recommend 给出推荐 + 理由。

运行：
    1. 另开终端：bash backend/scratch/run_bridge.sh
    2. cd backend && .venv/bin/python scratch/s3_02_hand_written_loop.py

参照 s3_01 的 run_agent 来写，但别复制——自己想清楚每一步在干嘛。
"""
from __future__ import annotations

import asyncio
import json

from _bridge import call_tool, make_client, section

# ---- 可执行工具：模型必须调它才知道有哪些产品（服务端执行、结果回喂）----
SEARCH_PRODUCTS_TOOL = {
    "name": "search_products",
    "description": "按风险等级查询可推荐的理财产品列表。风险等级取值 C1–C5。",
    "input_schema": {
        "type": "object",
        "properties": {"risk_level": {"type": "string", "enum": ["C1", "C2", "C3", "C4", "C5"]}},
        "required": ["risk_level"],
    },
}
# ---- 终态工具：模型挑好产品后调它收尾（不执行、只收尾）----
RECOMMEND_TOOL = {
    "name": "recommend",
    "description": "已从候选产品中选定一款时调用，给出最终推荐及理由。",
    "input_schema": {
        "type": "object",
        "properties": {
            "product_name": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["product_name", "reason"],
    },
}

TOOLS = [SEARCH_PRODUCTS_TOOL, RECOMMEND_TOOL]
EXECUTABLE = {"search_products"}
TERMINAL = {"recommend"}

# 假的「产品库」——search_products 就是查它（真实系统里这里是查 DB / 调 API）。
MOCK_DB = {
    "C1": [{"name": "稳盈货币A", "expected_return": "2.1%"}, {"name": "国债逆回购30天", "expected_return": "1.9%"}],
    "C2": [{"name": "短债精选C", "expected_return": "3.4%"}, {"name": "同业存单指数基金", "expected_return": "2.8%"}],
    "C3": [{"name": "稳健配置FOF", "expected_return": "5.0%"}, {"name": "二级债基优选", "expected_return": "4.6%"}],
    "C4": [{"name": "成长精选混合", "expected_return": "8.5%"}, {"name": "科技行业ETF", "expected_return": "11.2%"}],
    "C5": [{"name": "高弹性成长股基", "expected_return": "15%+"}, {"name": "行业主题杠杆基金", "expected_return": "20%+"}],
}

VALID_PRODUCT_NAMES = [item["name"] for value in MOCK_DB.values() for item in value]

SYSTEM = (
    "你是理财产品推荐助手。你不知道有哪些产品，必须先调 search_products 按客户风险等级查询候选，"
    "拿到候选列表后，从中挑最合适的一款，调 recommend 给出产品名和推荐理由并结束。"
    "每一步只调用一个工具。"
)

MAX_STEPS = 5


def execute_tool(name: str, tool_input: dict) -> str:
    """执行可执行工具，返回结果字符串（会被回喂给模型）。"""
    if name == "search_products":
        products = MOCK_DB.get(tool_input["risk_level"], [])
        return json.dumps(products, ensure_ascii=False)
    raise ValueError(f"未知可执行工具: {name}")


async def run_agent(client, task: str) -> None:
    section(f"任务: {task}")
    messages: list[dict] = [{"role": "user", "content": task}]

    # ============================================================
    # 👇 这里是 B 的核心：agent loop 由你从零写。规格如下（参照 s3_01 但自己实现）：
    #
    # for step in range(1, MAX_STEPS + 1):
    #   1) 调 call_tool(client, system=SYSTEM, messages=messages, tools=TOOLS) 拿到 blocks
    #      取 blocks[0]，读出 name / tool_input，打印这一步调了什么
    #   2) 显式分流（用 TERMINAL / EXECUTABLE 两个集合）：
    #        - name in TERMINAL      → 打印最终推荐（product_name + reason），return
    #        - name not in EXECUTABLE → 未知工具，打印告警并 return（防御）
    #   3) 可执行工具 → result = execute_tool(name, tool_input)，打印结果
    #   4) 结果回喂：把 assistant 的 tool_use 和 user 的 tool_result 追加进 messages
    #      （tool_use_id 用个 f"toolu_{step}" 占位即可）
    # 5) 循环正常结束（没 return）→ 打印「到达 MAX_STEPS 兜底终止」
    # ============================================================
    # raise NotImplementedError("👉 在这里写你的 agent loop（删掉这行）")
    search_results= []
    for step in range(1, MAX_STEPS + 1):
        print(f"第 {step} 步提示词 {messages}")
        blocks = await call_tool(client, system=SYSTEM, messages=messages, tools=TOOLS)
        block = blocks[0]
        name = block["name"]
        tool_input = block["input"]
        print(f"第 {step} 步调用工具: {name}，输入: {tool_input}")

        if name in TERMINAL:
            product = tool_input.get('product_name')
            # if product not in VALID_PRODUCT_NAMES:
            if product not in search_results:
                print(f"❌ 推荐产品 {product} 不存在")
                return
            print(f"✅ 完成，推荐产品 = {product} 推荐理由 = {tool_input.get('reason')}")
            return

        if name not in EXECUTABLE:
            print(f"第 {step} 步调用未知工具: {name}，输入: {tool_input}")
            return

        result = execute_tool(name, tool_input)
        print(f"输出: {result} （回喂给模型）")
        if name == "search_products":
            search_results.extend([item["name"] for item in json.loads(result)])
        tu_id = f"toolu_{step}"

        # ★ tool_use 的 id 与 tool_result 的 tool_use_id 必须【同值配对】——这是「调用↔结果」的钥匙。
        #   为什么要：真实 API 一轮可并行调多个工具（parallel tool use），全靠 tool_use_id 把每个
        #   结果对应回它那次调用（否则多个结果分不清谁是谁、甚至配反）；且 API 强制校验配对、缺了就 400。
        #   真实场景里 id 不是自己编的，而是从模型响应的 tool_use 块里拿到的(API 分配)，原样回填。
        #   bridge 单工具 + 渲染 tool_result 时只取 content、忽略 id，所以这里不写也能跑——写上是为了
        #   真实 API 的正确形状 + 养成习惯。（另注意：tool_result 的数据键是 "content"，不是 "result"！
        #   之前写成 "result" → bridge 取 content 取不到 → 回喂成空 → 模型幻觉出不存在的产品。）
        messages.append({"role": "assistant", "content": [{"type": "tool_use", "id": tu_id, "name": name, "input": tool_input}]})
        messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": tu_id, "content": result}]})

    print("❌ 到达 MAX_STEPS 兜底终止")

async def main() -> None:
    client = make_client()
    await run_agent(client, "客户的风险偏好评估结果是 C4，请为他推荐一款合适的理财产品。")


asyncio.run(main())
