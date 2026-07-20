"""阶段 3 · 练习 01：亲手写一个最小 agent loop（真·工具执行 + 结果回喂）

这是从「结构化输出」跨到「agent」的分水岭。前面 s1/s2 里的工具都只是
「结构化输出」——被调用即终点、从不真执行。这里第一次做真正的 agent loop：
    模型调工具 → 我们**真执行** → 把**结果回喂**给模型 → 模型据此决定下一步 → …直到收尾

学习目标：
- 分清两类工具：**可执行工具**（add/multiply，服务端执行、结果回喂、循环继续）
  vs **终态工具**（final_answer，模型调它=任务完成、循环结束）。
- 手写 while 循环 + **MAX_STEPS** 终止保护（agent loop 必须有，防止无限调工具烧钱）。
- 理解「结果回喂」的消息结构：assistant 的 tool_use + user 的 tool_result。

运行：
    1. 另开终端：bash backend/scratch/run_bridge.sh
    2. cd backend && .venv/bin/python scratch/s3_01_agent_loop.py

⚠️ 为什么需要 final_answer 这个「终态工具」？
   本地 bridge 强制模型**每轮都得调一个工具**（不能用纯文本 end_turn 收尾），
   所以得靠一个终态工具来结束循环——这正是 FinWise 的套路（conclude_assessment）。
   真实 API 里模型可以直接 end_turn 给文本答案，就不必要这个终态工具（见文末 TODO#4）。
"""
from __future__ import annotations

import asyncio

from _bridge import call_tool, make_client, section

# ---- 可执行工具：服务端真执行、结果要回喂给模型 ----
ADD_TOOL = {
    "name": "add",
    "description": "计算两个数之和 a + b。",
    "input_schema": {
        "type": "object",
        "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
        "required": ["a", "b"],
    },
}
MULTIPLY_TOOL = {
    "name": "multiply",
    "description": "计算两个数之积 a * b。",
    "input_schema": {
        "type": "object",
        "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
        "required": ["a", "b"],
    },
}
#TODO 2的练习
MINUS_TOOL = {
    "name": "minus",
    "description": "计算两个数之差 a - b。",
    "input_schema": {
        "type": "object",
        "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
        "required": ["a", "b"],
    },
}
# ---- 终态工具：模型调它 = 任务完成、循环结束（不执行、只收尾）----
FINAL_ANSWER_TOOL = {
    "name": "final_answer",
    "description": "已经算出最终结果时调用，给出最终答案。",
    "input_schema": {
        "type": "object",
        "properties": {"result": {"type": "number"}},
        "required": ["result"],
    },
}

TOOLS = [ADD_TOOL, MULTIPLY_TOOL, MINUS_TOOL, FINAL_ANSWER_TOOL]
EXECUTABLE = {"add", "multiply", "minus"}   # 这些要执行 + 回喂（loop 里用它做显式分流）
TERMINAL = {"final_answer"}          # 这个收尾

# 注意：下面「自己不能心算」是**软约束**——不保证模型一定照办。
#   实测（含删掉这句、或换成极简 3+5）3/3 仍乖乖用了工具，但这只说明「通常有效」，
#   不等于「保证」：软约束不保证 ≠ 经常失败——好模型多数时候遵守，危险在不可预测的尾部
#   （换模型/措辞/某次采样就可能破例），而这里没有任何硬机制拦住那一次。要可靠就上硬机制
#   （tool_choice 强制 / client 校验 / strict 模式），别靠「prompt 说了 + 测几次都过」。
# ★ 设计原则：给 agent 的工具，应该是模型**真正需要、自己办不到**的
#   （查库 search_products / 调 API / 有副作用的操作）——这类工具模型别无选择只能调，不用逼。
#   算术是模型自己就会的，所以本 demo 才得人为加「不能心算」把用工具的场景硬造出来（教学拐杖）；
#   实测删掉它照样用工具，反证「好工具无需强制」。真实 agent 应给「模型需要」的工具，而非逼它用会的。
SYSTEM = (
    "你是一个只会通过工具做算术的助手，自己不能心算。"
    "每一步只调用一个工具：需要计算就调 add 或 multiply；"
    "拿到工具返回的中间结果后，再决定下一步；"
    "当最终结果已经算出来时，调用 final_answer 给出答案并结束。"
)

# TODO 3的练习
MAX_STEPS = 6  # ★ 终止保护：agent loop 必须有硬上限，防止模型无限调工具
# MAX_STEPS = 1


def execute_tool(name: str, tool_input: dict) -> float:
    """真正执行可执行工具，返回结果（会被回喂给模型）。"""
    if name == "add":
        return tool_input["a"] + tool_input["b"]
    if name == "multiply":
        return tool_input["a"] * tool_input["b"]
    #TODO 2的练习
    if name == "minus":
        return tool_input["a"] - tool_input["b"]
    raise ValueError(f"未知可执行工具: {name}")


async def run_agent(client, task: str) -> None:
    section(f"任务: {task}")
    messages: list[dict] = [{"role": "user", "content": task}]

    # ★ 这就是 agent loop —— 手写的 while，不用任何框架
    for step in range(1, MAX_STEPS + 1):
        # 1) 问模型下一步做什么（bridge 每次返回一个 tool 调用）
        blocks = await call_tool(client, system=SYSTEM, messages=messages, tools=TOOLS)
        # 只取 blocks[0]：bridge 每轮只产 1 个工具调用，所以这里安全——但这是「依赖 bridge 特性」的简化。
        # ⚠️ 真实 API 支持并行工具调用（parallel tool use，一轮返回多个 tool_use），那时 blocks 会有多项，
        #   [0] 会悄悄丢掉其余的。健壮写法：遍历所有 blocks 各自执行，并把所有 tool_result 塞进【同一条】
        #   user 消息一起回喂（并行工具硬规定）。（另：真实代码还应先判 blocks 是否为空，防 IndexError。）
        b = blocks[0]
        name, tool_input = b["name"], b["input"]
        print(f"[step {step}] 模型决定调用: {name}({tool_input})")

        # 2) 显式三分流（用 TERMINAL / EXECUTABLE 两个集合）——比"只要不是终态就执行"更健壮：
        #    a. 终态工具 → 收尾、跳出循环
        if name in TERMINAL:
            print(f"✅ 完成，最终答案 = {tool_input.get('result')}")
            return
        #    b. 既不是终态、也不在已知可执行集合 → 防御：别硬塞进 execute_tool 崩掉，优雅终止
        if name not in EXECUTABLE:
            print(f"⚠️ 模型调用了未知工具 {name!r}（不在 EXECUTABLE 也不在 TERMINAL），无法执行，终止。")
            return

        # 3) 可执行工具 → 真执行，拿到结果
        result = execute_tool(name, tool_input)
        print(f"          → 执行结果 = {result}（回喂给模型）")

        # 4) ★ 结果回喂：把「模型的 tool_use」和「工具结果 tool_result」都追加进 messages，
        #    下一轮 call_tool 时模型就能看到自己上一步做了什么、拿到了什么结果，据此继续。
        tuid = f"toolu_{step}"
        messages.append({
            "role": "assistant",
            "content": [{"type": "tool_use", "id": tuid, "name": name, "input": tool_input}],
        })
        messages.append({
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tuid, "content": str(result)}],
        })

    # 5) 兜底：到达 MAX_STEPS 还没 final_answer → 强制终止（防失控）
    print(f"⚠️ 到达 MAX_STEPS={MAX_STEPS} 仍未收尾，兜底终止。")


async def main() -> None:
    client = make_client()
    # 这个任务需要两步：先 add(3,5)=8，再 multiply(8,2)=16，然后 final_answer(16)
    await run_agent(client, "先算 3 加 5，再把结果乘以 2，最后给出答案。")
    #TODO 1的练习
    await run_agent(client, "先算 (3+5)，再算 (2+4)，再把两个结果相乘。")
    #TODO 2的练习
    await run_agent(client, "先算 (3-5)，再算 (7-2)，再把两个结果相乘。")
    #额外练习：任务需要除法，但【没有定义除法工具】——看模型怎么办。
    # 实测两次跑出两种行为（同任务/工具/prompt，非确定性）：
    #   A) minus→minus→final_answer(3)          ← 直接心算了 6÷2，违背了「不能心算」
    #   B) minus→minus→multiply(6, 0.5)→final_answer(3.0)  ← 把 ÷2 改写成 ×0.5 用已有工具绕过
    # ★ 这就是前面「软约束不保证」的尾部失败被实测出来了：缺工具时模型不会干脆报错，
    #   而是「想办法蒙一个答案」——有时心算(A)、有时改写绕过(B)。
    # ★ 真正的危险：这里 6÷2=3 是算术、蒙对了没露馅；但换成模型自己办不到的事
    #   （查真实产品价格/数据库），缺工具就会「静默编一个看似合理的假值」（幻觉），你还看不出来。
    #   防御不是「校验模型编的值」（你没真值、校验不了），而是：给对应工具、让事实从权威来源(DB)出、
    #   由代码而非模型拥有该值；真没 ground truth 时校验「出处/provenance」而非值本身。（→ 阶段四 RAG 的动机）
    await run_agent(client, "先算 (8-2)，再算 (4-2)，再把第一个结果除以第二个结果。")

    # ---- 练习 TODO ----
    # 1. 换个更复杂的任务，如「先算 (3+5)，再算 (2+4)，再把两个结果相乘」——
    #    看模型会不会分多步、正确地把中间结果传给下一步。
    # 2. 加一个 subtract 工具（a-b），让它能算带减法的表达式（记得加进 TOOLS + EXECUTABLE + execute_tool）。
    # 3. 把 MAX_STEPS 改成 1，看「兜底终止」是否触发（模型第一步还没算完就被打断）。
    # 4. 思考：真实 API 里模型可以直接 end_turn 用文本给答案，就不需要 final_answer 终态工具了——
    #    为什么本脚本需要它？（提示：bridge 强制每轮必须调一个工具，见文件头 ⚠️）


asyncio.run(main())
