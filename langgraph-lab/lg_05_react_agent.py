"""LangGraph 进阶 · lg_05：create_react_agent —— 一行造出完整 ReAct agent

到目前你所有 agent loop 都是【你控制】的：手写(B#3–B#7) / tool_runner(s6_01) /
LangGraph 节点自己连(lg_01–04)。这里用 LangGraph 预制件 **create_react_agent**：
【一行】就造出一个完整 ReAct agent——它内部自带 "agent(调模型) ⇄ tools(执行工具)"
的循环图，连节点、连边你都不用写。

★ 核心对照（框架把 loop 又藏回去了，但你看得穿）：
  B#3–B#7   你手写了整套 loop（几十行 for + tool_use 判断 + 回喂 + MAX_STEPS）
  s6_01     tool_runner 封装了它
  lg_01–04  你用 LangGraph 节点+边【显式】搭 agent
  lg_05     create_react_agent 把这一切压成【一行】——loop/工具执行/消息管理全藏进去
  但你手写过、也用节点搭过，所以这一行背后是什么，你一清二楚（= 你搭过的那个 ReAct 图）。

ReAct（见 concepts-basics）：模型调工具(Act) → 框架执行、结果回喂(Observe) →
  模型看着结果继续(Reason) → 不再调工具 → 收尾。★ 关键：工具得【真能执行、返回有用结果】，
  框架会真调它、把返回值喂回模型（不像 lg_04 的桩 return "ok"）。

前置：mock bridge(ReAct 版) 起在 :8788 —— cd langgraph-lab && .venv/bin/uvicorn mock_bridge:app --port 8788
运行：cd langgraph-lab && .venv/bin/python lg_05_react_agent.py
"""
from __future__ import annotations

import os

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("ANTHROPIC_API_KEY", "x")

from langchain_anthropic import ChatAnthropic              # noqa: E402
from langchain_core.tools import tool                      # noqa: E402
from langgraph.prebuilt import create_react_agent          # noqa: E402


llm = ChatAnthropic(model="claude-haiku-4-5-20251001",
                    anthropic_api_url="http://localhost:8788", max_tokens=1024)


# ---- 真能执行的工具（★ 不是桩！框架会真调它、把返回值作为 Observation 回喂模型）----
MATCH_RULES = {"C1": ["R1"], "C2": ["R2"], "C3": ["R3"], "C4": ["R4"], "C5": ["R5"]}
FAKE_DB = {"R1": [{"code": "P-R1", "name": "稳盈货币A"}], "R2": [{"code": "P-R2", "name": "短债精选C"}],
           "R3": [{"code": "P-R3", "name": "稳健配置FOF"}], "R4": [{"code": "P-R4", "name": "成长精选混合"}],
           "R5": [{"code": "P-R5", "name": "高弹性成长股基"}]}


@tool
def search_products(risk_level: str) -> str:
    """按风险等级(C1–C5)查询可推荐的理财产品清单。"""
    r_levels = MATCH_RULES.get(risk_level, [])
    products = [p for r in r_levels for p in FAKE_DB.get(r, [])]
    print(f"    〔工具真执行〕search_products({risk_level}) → {[p['code'] for p in products]}")
    return str(products)   # ← 这个返回值会被框架作为 Observation 回喂给模型


# ========================= 你的 TODO：一行造 agent =========================

def build_agent():
    """TODO：用 create_react_agent 造一个 ReAct agent，返回它。

      agent = create_react_agent(llm, tools=[search_products])
      return agent

    就这么一行——对比你手写的几十行 loop。framework 内部会自动跑：
      模型调 search_products → 框架真执行工具 → 结果回喂 → 模型继续 → 不再调工具 → 收尾。
    """
    return create_react_agent(llm, tools=[search_products])



# =========================================================================


def main() -> None:
    agent = build_agent()

    # 先把 agent 内部的图画出来——看它就是你手搭过的 ReAct 循环（agent ⇄ tools）
    print("=== create_react_agent 内部的图（= 你手搭过的 ReAct 结构）===")
    print(agent.get_graph().draw_mermaid())

    print("\n=== 跑一次（ReAct loop 自动转）===")
    # 输入是消息列表；agent 自己跑 loop 直到收尾
    result = agent.invoke({"messages": [("user", "我风险 C4，帮我查产品并推荐。")]})
    print("\n  最终消息数:", len(result["messages"]))
    print("  最后一条（收尾文本）:", result["messages"][-1].content)


if __name__ == "__main__":
    main()
