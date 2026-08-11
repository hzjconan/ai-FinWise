"""阶段六 · s6_01：用 Anthropic SDK 的 tool_runner 重写手写 agent loop——看穿框架

s3_02 你【亲手】写了 agent loop：for 循环、判断 tool_use、执行工具、把 tool_use+
tool_result 成对回喂 messages、continue、MAX_STEPS 兜底、id 配对……全是你手动拼的管道。

这里用官方 SDK 自带的 **client.beta.messages.tool_runner** 重写【同一个场景】（产品推荐
agent），然后对照：**框架到底替你做了什么？** —— 答案是：它把你手写的那个 for 循环整个
包掉了。你只需要 ①定义工具函数 ②起 runner，剩下的「调模型→执行工具→回喂→续跑→终止」
全自动。

★ 学习点：框架不是魔法。tool_runner 内部做的，就是你在 B#3–B#7 手写的那套：
    while 未终止 and 步数 < max_iterations:
        调模型 → 有 tool_use? → 执行你的函数 → 把结果作为 tool_result 回喂 → 继续
  你手写过一遍，所以现在能一眼看穿它，而不是被"框架"唬住。

手写 vs 框架 对照（读完代码再回看这张表）：
  | 你在 s3_02 手写的            | tool_runner 替你做的                |
  | for _ in range(MAX_STEPS)   | 内部循环 + max_iterations 参数       |
  | if block.type=="tool_use"   | 自动识别 tool_use                   |
  | _execute_tool 分发          | 按名字自动调用你 @beta_tool 的函数    |
  | 手拼 tool_use+tool_result   | 自动拼、自动配 id                    |
  | 手动 append 回 messages     | 自动追加、自动续调                   |
  | 终态工具判断/break           | 没有更多 tool_use = 自动停           |

运行（纯离线，不发请求、不需要 bridge/真 key）：
    cd backend && .venv/bin/python scratch/s6_01_tool_runner.py
（tool_runner 真跑需真 ANTHROPIC_API_KEY——bridge 撑不起它内部的 beta messages.parse；
 本脚本改走「离线看穿」：introspection 拆开框架，证明它替你做了什么。）
"""
from __future__ import annotations

import httpx
from anthropic import Anthropic, beta_tool

from _bridge import BRIDGE_BASE_URL, DUMMY_KEY, MODEL, section


# ---- 假产品库（和 s3_02 同款，服务端数据，模型不可能凭空知道 → 必须查）----
FAKE_DB = {
    "C1": [{"code": "P-C1", "name": "稳盈货币A", "expected_return": 0.021}],
    "C2": [{"code": "P-C2", "name": "短债精选C", "expected_return": 0.034}],
    "C3": [{"code": "P-C3", "name": "稳健配置FOF", "expected_return": 0.05}],
    "C4": [{"code": "P-C4", "name": "成长精选混合", "expected_return": 0.085}],
    "C5": [{"code": "P-C5", "name": "高弹性成长股基", "expected_return": 0.15}],
}


# ========================= 你的 TODO：用 @beta_tool 定义工具 =========================
# 关键差异：手写时工具是「schema dict + 单独的执行函数」两块；tool_runner 里工具就是
# 【一个带类型注解和 docstring 的普通函数】——@beta_tool 自动从签名生成 schema、
# 函数体就是执行逻辑。schema 和实现合二为一。

# TODO#1：把 search_products 写成一个 @beta_tool 函数。
#   - 用 @beta_tool 装饰；
#   - 函数名 = 工具名（search_products）；
#   - 参数 risk_level: str（类型注解会变成 input_schema）；
#   - docstring 第一行 = 工具 description（模型据此决定调不调）——写清"按风险等级查产品"；
#   - 函数体：从 FAKE_DB 取该等级的产品列表，返回它（可 return list/dict，SDK 会序列化回喂）。
#   参考签名：
#       @beta_tool
#       def search_products(risk_level: str) -> list:
#           """按风险等级(C1–C5)查询可推荐的理财产品列表。"""
#           ...
@beta_tool
def search_products(risk_level: str) -> list:
    """按风险等级(C1–C5)查询可推荐的理财产品列表。"""
    return FAKE_DB.get(risk_level, [])



# =================================================================================


# 注意：本地 bridge 是简化 shim，撑不起 tool_runner 内部用的 beta `messages.parse`
# （会返回 str 而非 Message 对象 → 崩）。tool_runner 是真实 SDK 特性、要真 ANTHROPIC_API_KEY
# 才能真跑。所以这里走「离线看穿」：不发请求，用 introspection 拆开框架，证明它替你做了什么。


def _print_generated_schema() -> None:
    """看穿点①：@beta_tool 把普通函数【自动变成】工具 schema——schema 和实现合二为一。
    手写时你要单独维护一个 input_schema dict；这里它是从函数签名/docstring 自动生成的。"""
    section("① @beta_tool 自动生成的 schema（函数 → schema，你没手写它）")
    t = search_products
    # BetaFunctionTool 暴露 name / description / input_schema
    print("  name        :", t.name)
    print("  description :", t.description, "  ← 来自 docstring")
    print("  input_schema:", t.input_schema, "  ← 来自参数注解 risk_level: str")
    print("  → 对照 s3_02：那一大块手写的 SEARCH_PRODUCTS_TOOL dict，这里一行没写。")


def _print_runner_anatomy(client: Anthropic) -> None:
    """看穿点②：runner 是个迭代器，内部就是你手写的 while 循环 + MAX_STEPS。"""
    section("② tool_runner 的解剖（不发请求，只看它是什么）")
    runner = client.beta.messages.tool_runner(
        model=MODEL, max_tokens=1024,
        max_iterations=5,                 # ← 你手写的 MAX_AGENT_STEPS，框架化成一个参数
        tools=[search_products],          # ← 传函数本身；框架按 name 自动分发调用
        messages=[{"role": "user", "content": "帮我推荐 C4 的产品"}],
    )
    print("  runner 类型 :", type(runner).__name__)
    print("  可迭代?     :", hasattr(runner, "__iter__"),
          " ← for message in runner: 每摇一下=agent 走一步（见 python-syntax-notes 迭代器）")
    print("  关键方法    :", [m for m in dir(runner) if not m.startswith("_")])
    print("  → until_done() 一路跑到终止；append_messages/generate_tool_call_response 是")
    print("    你手写 loop 里「append 回 messages」「拼 tool_result」的框架版。")


def _print_handwritten_vs_framework() -> None:
    section("③ 手写(s3_02 / B#3–B#7) vs 框架(tool_runner) 逐条对照")
    rows = [
        ("for _ in range(MAX_STEPS)", "内部循环 + max_iterations 参数"),
        ("if block.type=='tool_use'", "自动识别 tool_use"),
        ("_execute_tool 按名分发", "按 name 自动调用你 @beta_tool 的函数"),
        ("手拼 tool_use+tool_result、配 id", "自动拼、自动配 tool_use_id"),
        ("messages.append(...) + continue", "append_messages + 自动续调"),
        ("终态工具判断 / break", "模型不再调工具 = 迭代耗尽 = 自动停"),
        ("工具 schema dict + 执行函数两块", "@beta_tool：一个函数 = schema + 实现"),
    ]
    for hand, fw in rows:
        print(f"  {hand:<34}│ {fw}")
    print("\n  一句话：框架不是魔法——tool_runner 把你亲手写过的 loop 整个包掉了。")
    print("  你手写过一遍，所以能一眼看穿它每一层，而不是被'框架'唬住。")


def run_for_real(client: Anthropic) -> None:
    """【参考，需真 ANTHROPIC_API_KEY 才能跑】真机迭代 runner 的健壮写法。
    bridge 撑不起 beta messages.parse，所以本函数默认不被调用；换真 key 时可启用。

    两个易踩的坑（对应 TODO#2 当初的写法）：
      ① 别依赖「循环泄漏变量」：Python 无块级作用域，循环里定义的 texts 会泄漏到循环外，
         但若 runner 一轮都没迭代，它从未赋值 → NameError。故循环前显式初始化 last_message。
      ② 别用 texts[-1]：最后一轮 message 可能没有 text 块（模型只调工具/bridge 只吐 tool_use）
         → 空列表取 [-1] 会 IndexError。故用 "".join(所有 text 块) + or 兜底。
    """
    runner = client.beta.messages.tool_runner(
        model=MODEL, max_tokens=1024, max_iterations=5,
        tools=[search_products],
        messages=[{"role": "user", "content": "我风险中等偏上（C4），推荐一款产品并说明理由。"}],
    )
    last_message = None
    for i, message in enumerate(runner, 1):     # 每摇一步 = agent 走一轮（框架自动执行工具+回喂）
        last_message = message                  # ① 显式存，不靠循环泄漏
        tool_uses = [b for b in message.content if getattr(b, "type", None) == "tool_use"]
        texts = [b.text for b in message.content if getattr(b, "type", None) == "text"]
        print(f"  〔第{i}轮 stop={message.stop_reason}〕"
              f" 工具={[t.name for t in tool_uses]}  文本={''.join(texts)[:80]!r}")
    if last_message is not None:                # ② 从最终 message 取全部文本、防空
        final_text = "".join(
            b.text for b in last_message.content if getattr(b, "type", None) == "text"
        )
        print(f"  最终推荐：{final_text or '(无文本：模型最后一轮只调了工具)'}")


def main() -> None:
    # 只建 client 对象（不发请求），供 introspection 用
    client = Anthropic(
        base_url=BRIDGE_BASE_URL, api_key=DUMMY_KEY,
        http_client=httpx.Client(trust_env=False),
    )
    _print_generated_schema()
    _print_runner_anatomy(client)
    _print_handwritten_vs_framework()
    # run_for_real(client)   # ← 换真 ANTHROPIC_API_KEY、client 去掉 base_url 后取消注释即可真跑
    print("\n（想看它真的自动跑完 loop：换真 ANTHROPIC_API_KEY、client 去掉 base_url，"
          "\n 启用上面的 run_for_real() —— bridge 撑不起 beta parse。）")


if __name__ == "__main__":
    main()
