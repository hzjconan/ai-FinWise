"""LangGraph 进阶 · lg_04：把节点里的裸 SDK 换成 langchain 的 ChatAnthropic

lg_01/02 节点里调 LLM 用的是【裸 anthropic SDK】(call_bridge_tool：手动 stream、手动
从 content 里挑 tool_use 块、手动取 input)。这里换成 langchain 的 **ChatAnthropic**，
对照：langchain 的统一 chat model 接口帮你省了什么、藏了什么。

裸 SDK vs ChatAnthropic：
  | 裸 SDK (call_bridge_tool)                | ChatAnthropic (langchain)              |
  | 传 tools=[{name,input_schema...}] dict   | bind_tools([函数或schema])，接口统一     |
  | client.messages.stream(...)              | llm.invoke(messages)                    |
  | 手动遍历 final.content 挑 tool_use 块      | resp.tool_calls 直接给 [{name,args,id}] |
  | 只能对 Anthropic                          | 换 ChatOpenAI 等即切 provider，代码不动  |
藏起来的：底层还是 messages API + tool_use/tool_result（你裸手做过，看得穿）。

★ ChatAnthropic 走【教学 mock bridge】（真 bridge 只支持 SSE，撑不起它非流式调用）。
前置：cd langgraph-lab && .venv/bin/uvicorn mock_bridge:app --port 8788   （另开终端）
运行：cd langgraph-lab && .venv/bin/python lg_04_chatanthropic.py

★ 唯一 TODO：把 assess_node / recommend_node 里的 LLM 调用改用 llm_with_tools.invoke。
"""
from __future__ import annotations

import os
from typing import Literal, TypedDict

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("ANTHROPIC_API_KEY", "x")   # mock 不校验，占位即可

from langchain_anthropic import ChatAnthropic          # noqa: E402
from langchain_core.tools import tool                  # noqa: E402
from langgraph.graph import END, START, StateGraph     # noqa: E402


# ---- 用 ChatAnthropic 建 LLM，指向教学 mock bridge（:8788，非真 bridge :8787）----
llm = ChatAnthropic(model="claude-haiku-4-5-20251001",
                    anthropic_api_url="http://localhost:8788", max_tokens=1024)


# ---- 工具：langchain 用 @tool 装饰普通函数（对照裸 SDK 手写 schema dict）----
@tool
def assess(dimensions: dict) -> str:
    """给 5 个维度打 1–5 分：experience/loss_tolerance/income_stability/
    investment_horizon/volatility_tolerance。"""
    return "ok"


@tool
def recommend(recommended_code: str, reason: str) -> str:
    """从候选产品里挑一款推荐，recommended_code 必须来自候选清单。"""
    return "ok"


# 绑定工具 + 强制用工具（bridge/mock 约定：以工具形式作答）
assess_llm = llm.bind_tools([assess], tool_choice="assess")
recommend_llm = llm.bind_tools([recommend], tool_choice="recommend")


# ---- 领域小工具（同 lg_01）----
MATCH_RULES = {"C1": ["R1"], "C2": ["R2"], "C3": ["R3"], "C4": ["R4"], "C5": ["R5"]}
FAKE_DB = {"R1": [{"code": "P-R1", "name": "稳盈货币A"}], "R2": [{"code": "P-R2", "name": "短债精选C"}],
           "R3": [{"code": "P-R3", "name": "稳健配置FOF"}], "R4": [{"code": "P-R4", "name": "成长精选混合"}],
           "R5": [{"code": "P-R5", "name": "高弹性成长股基"}]}


def level_from_dims(values: list) -> str:
    n = sum(values) / len(values) * 20 if values else 0
    for thr, code in [(20, "C1"), (40, "C2"), (60, "C3"), (80, "C4")]:
        if n < thr:
            return code
    return "C5"


class State(TypedDict):
    customer_desc: str
    risk_level: str
    dimensions: dict
    products: list
    recommendation: dict


# ========================= 你的 TODO：用 ChatAnthropic 调 LLM =========================

def assess_node(state: State) -> dict:
    """TODO#1：用 assess_llm.invoke(...) 调 LLM，从返回里取维度分。

    对照裸 SDK：以前是 call_bridge_tool(...) 返回 tool_input dict；这里是——
      resp = assess_llm.invoke(state["customer_desc"])   # 传字符串或消息列表
      resp.tool_calls  → [{"name":"assess", "args":{"dimensions":{...}}, "id":...}]
    所以维度分在 resp.tool_calls[0]["args"]["dimensions"]。取出来，算等级，返回 state 更新。
    提示：dims = resp.tool_calls[0]["args"]["dimensions"]
    """
    resp = assess_llm.invoke(state["customer_desc"])
    dims = resp.tool_calls[0]["args"]["dimensions"]
    risk_level = level_from_dims(dims.values())
    return {"risk_level": risk_level, "dimensions": dims}


def retrieve_node(state: State) -> dict:
    products = [p for r in MATCH_RULES.get(state["risk_level"], []) for p in FAKE_DB.get(r, [])]
    print(f"  〔retrieve〕{state['risk_level']} → {[p['code'] for p in products]}")
    return {"products": products}


def recommend_node(state: State) -> dict:
    """TODO#2：用 recommend_llm.invoke(...) 调 LLM，取推荐结果。

      listing = "\\n".join(f"[{p['code']}] {p['name']}" for p in state["products"])
      resp = recommend_llm.invoke(f"等级 {state['risk_level']}，候选：\\n{listing}\\n推荐一款。")
      rec = resp.tool_calls[0]["args"]   # {"recommended_code":..., "reason":...}
    返回 {"recommendation": rec}。
    """
    listing = "\\n".join(f"[{p['code']}] {p['name']}" for p in state["products"])
    resp = recommend_llm.invoke(f"等级 {state['risk_level']}，候选：\\n{listing}\\n推荐一款。")
    rec = resp.tool_calls[0]["args"]
    return {"recommendation": rec}

# ===================================================================================


def route_after_retrieve(state: State) -> Literal["recommend", "__end__"]:
    return END if not state["products"] else "recommend"


def build_graph():
    g = StateGraph(State)
    g.add_node("assess", assess_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("recommend", recommend_node)
    g.add_edge(START, "assess")
    g.add_edge("assess", "retrieve")
    g.add_conditional_edges("retrieve", route_after_retrieve)
    g.add_edge("recommend", END)
    return g.compile()


def main() -> None:
    app = build_graph()
    desc = "我炒股 5 年，能扛波动但受不了腰斩，钱放 3-5 年，有稳定工资。"
    print(f"=== 客户：{desc[:22]}… ===")
    result = app.invoke({"customer_desc": desc})
    print(f"\n  最终：等级={result['risk_level']} 推荐={result['recommendation'].get('recommended_code')}")


if __name__ == "__main__":
    main()
