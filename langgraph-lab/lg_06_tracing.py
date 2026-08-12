"""LangGraph 进阶 · lg_06：接 LangSmith tracing —— 补上"可观测性"（阶段五留的坑）

前面看过：agent 是多步的（ReAct loop：调模型→执行工具→回喂→继续）。出问题时你需要
【看进内部】每一步的输入/输出/耗时。你早就手搓过 tracing——a2 的 ToolLoggingLLM 探针
（包在 LLM 外打印每次工具调用）。这里换成专业工具 **LangSmith**：自动 + 结构化 + 有 UI。

★ 极简接入（LangChain 生态的好处）：【不改任何业务代码】，只设几个环境变量，
  langchain/langgraph 的每次 LLM 调用/每个节点/每个工具执行【自动上报】到 LangSmith，
  网页上看到完整的 span 树（trace）。

本脚本 = lg_05 的 ReAct agent + 打开 tracing。跑完去 https://smith.langchain.com 看这次运行的
trace：一棵树——agent 节点 → LLM 调用 → tools 节点 → search_products 执行 → agent 再调 → 收尾，
每个 span 带输入/输出/耗时。这就是"手搓 ToolLoggingLLM"的自动+可视化版。

前置：
  1) .env 里有 LANGSMITH_API_KEY / LANGSMITH_TRACING=true（已配好）；
  2) mock bridge(ReAct 版) 起在 :8788。
运行：cd langgraph-lab && .venv/bin/python lg_06_tracing.py
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

# ★ 关键就这两步：① 从 .env 加载 LANGSMITH_API_KEY / LANGSMITH_TRACING → ② 之后一切自动上报
load_dotenv()                                   # 读 .env 到环境变量
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("ANTHROPIC_API_KEY", "x")
os.environ.setdefault("LANGSMITH_PROJECT", "finwise-learn-lg06")   # trace 归到这个项目下，好找

from langchain_anthropic import ChatAnthropic          # noqa: E402
from langchain_core.tools import tool                  # noqa: E402
from langgraph.prebuilt import create_react_agent      # noqa: E402


llm = ChatAnthropic(model="claude-haiku-4-5-20251001",
                    anthropic_api_url="http://localhost:8788", max_tokens=1024)

MATCH_RULES = {"C1": ["R1"], "C2": ["R2"], "C3": ["R3"], "C4": ["R4"], "C5": ["R5"]}
FAKE_DB = {"R1": [{"code": "P-R1", "name": "稳盈货币A"}], "R2": [{"code": "P-R2", "name": "短债精选C"}],
           "R3": [{"code": "P-R3", "name": "稳健配置FOF"}], "R4": [{"code": "P-R4", "name": "成长精选混合"}],
           "R5": [{"code": "P-R5", "name": "高弹性成长股基"}]}


@tool
def search_products(risk_level: str) -> str:
    """按风险等级(C1–C5)查询可推荐的理财产品清单。"""
    products = [p for r in MATCH_RULES.get(risk_level, []) for p in FAKE_DB.get(r, [])]
    return str(products)


def main() -> None:
    tracing_on = os.environ.get("LANGSMITH_TRACING", "").lower() in ("true", "1")
    print(f"LangSmith tracing: {'✅ 开启' if tracing_on else '❌ 未开启（检查 .env 的 LANGSMITH_TRACING）'}")
    print(f"项目名: {os.environ.get('LANGSMITH_PROJECT')}\n")

    agent = create_react_agent(llm, tools=[search_products])
    result = agent.invoke({"messages": [("user", "我风险 C4，帮我查产品并推荐。")]})
    print("跑完，最后一条:", result["messages"][-1].content)
    print("\n→ 去 https://smith.langchain.com 打开项目"
          f" '{os.environ.get('LANGSMITH_PROJECT')}'，看这次运行的 trace（span 树）。")


if __name__ == "__main__":
    main()
