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
    content_block_delta_count = 0
    async with client.messages.stream(
        model=MODEL,
        system="你是简洁的技术助手。",
        messages=messages,
        tools=[ANSWER_TOOL],
        max_tokens=1024,
        # max_tokens=20,
    ) as stream:
        async for event in stream:
            etype = event.type
            if etype == "content_block_delta":       # ← 按事件类型数，场景无关
                content_block_delta_count += 1
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
    print("stop_reason  :", final.stop_reason)
    print("content_block_delta_count :", content_block_delta_count)

    # ---- 练习 TODO ----
    # 1. 把 max_tokens 改成 20，观察长回答是否被截断（stop_reason 会变）。
    #    ⚠️ 注意：本地 bridge 会「吞掉」max_tokens（从不转发给 CLI），所以在 bridge 上
    #       改这个值看不到任何变化——回答照样完整，stop_reason 恒为 "tool_use"。
    #       真实 API（需 ANTHROPIC_API_KEY）上把 max_tokens 调到 20 会看到：
    #       - 输出被硬截断：本例走 answer 工具，answer 字段的 JSON 会在 ~20 token 处
    #         中途切断（半句话 / 甚至是不完整、无法解析的 JSON）；不带 tool 的纯文本
    #         则是回答只写了个开头就没了。
    #       - stop_reason 从正常结束的 "tool_use"（或纯文本时的 "end_turn"）
    #         变成 "max_tokens" —— 这就是「我把你的输出掐断了」的信号，
    #         提示你要么调大 max_tokens，要么用流式接更长的输出。
    #       （这条属「需真 key」练习，见 backend/scratch/README.md。）
    # 2. 数一下 content_block_delta 事件出现了多少次——这就是「流」的颗粒度。
    # 3. 思考：为什么前端要处理这些增量事件，而不是等最终结果？（答案：首字延迟/体验）


asyncio.run(main())

# ============================================================
# 复习笔记：stop_reason（这一轮为什么停下来）
# ============================================================
# 在哪看：final.stop_reason（final = stream.get_final_message() 的汇总对象）；
#         也可在流里抓 message_delta 事件的 event.delta.stop_reason。
#
# 真实 API 上它不一定是 "tool_use"！取决于模型怎么选 + 过程发生了什么：
#   - tool_use     模型决定调用某个工具
#   - end_turn     模型自然答完（纯文本回答，没调工具）
#   - max_tokens   输出被 max_tokens 截断
#   - stop_sequence命中自定义停止序列
#   - refusal      安全拒答
#   - pause_turn   服务端工具（如联网搜索）跑到迭代上限暂停
#
# 关键：tool_choice 决定「是否一定走工具」——
#   - {"type": "auto"}（默认，本脚本就是）→ 用不用工具随模型 → 可能 tool_use 也可能 end_turn
#   - {"type": "tool", "name": "answer"}  → 强制调指定工具 → 基本锁定 tool_use
#   - {"type": "any"}                     → 强制调某个工具 → tool_use
#   - {"type": "none"}                    → 禁用工具 → 必是 end_turn
#
# ⚠️ bridge 陷阱：本地 bridge 把模型硬逼成只输出工具 JSON，stop_reason 恒为 "tool_use"，
#    是写死的假象，看不到 end_turn/refusal 等。真实 API + auto 下才会有区别。
#
# 联系阶段三：agent loop 正是靠判断 stop_reason == "tool_use" 决定
#    「要不要执行工具、继续循环」，还是「end_turn 了、可以收尾」。
# ============================================================

# ============================================================
# 复习笔记：流式事件的「三层 type + 两个来源」
# ============================================================
# 你在 `async for event in stream` 里拿到的 event.type，来自两个来源：
#
# A) 原始协议事件（SSE，网络线上真实传来的骨架）：
#    message_start → content_block_start → content_block_delta(可多次)
#    → content_block_stop → message_delta(带 stop_reason) → message_stop
# B) SDK 便利事件（仅高层 client.messages.stream() 会额外合成；底层 stream=True 没有）：
#    text / input_json / citation / thinking / signature
#    —— 这就是为什么每个 [content_block_delta] 后面还跟一个 [input_json]。
#
# ★ 三个「type」是三个层次，名字像但别混：
#   event.type == "content_block_delta"            ① 顶层：哪种事件
#       └ event.delta.type == "input_json_delta"   ② 增量层：这段增量是哪种内容
#   event.type == "content_block_start"
#       └ event.content_block.type == "tool_use"   ③ 内容块层：这个块是哪种块
#
# ② 增量层 delta.type → 各自固定的载荷字段（API schema 定死，字段名跟着类型走）：
#   text_delta       → delta.text           纯文本增量
#   input_json_delta → delta.partial_json    工具入参 JSON 的碎片   ← 本脚本 L50-52 用的
#   thinking_delta   → delta.thinking
#   signature_delta  → delta.signature
#   citations_delta  → delta.citation
#
# 「input」指谁？= 工具的 input = 模型要传给工具的「参数」（方向：模型 → 工具）。
#   如 s1_01 里 tool_use 块的 block.input == {"answer": "..."}。
#   input_json_delta = 那个参数对象序列化成 JSON 后、正在流式传来的一小块；
#   L52 的 accumulated += piece 就是把这些碎片拼回完整 {"answer": "..."} 再解析。
#
# 计数陷阱（TODO#2）：数「流的颗粒度」要按 event.type == "content_block_delta"（①顶层）
#   来数，而非按 delta.type（②增量层）——两者只在 tool_use 场景恰好相等。
#
# async for（L44）：stream 是「异步可迭代对象」，每取一个事件都隐含一次
#   await stream.__anext__()（等下一段网络数据），故须用 async for、且只能在 async 函数里。
# ============================================================
