"""LangGraph 基础 · lg_02：循环图（回边）——LangGraph 相对手写最核心的价值

lg_01 是直线：assess→retrieve→recommend→END。真实 agent 常需要【回头重来】。
这里加一个 review 节点给推荐打分：分低（不靠谱）→ 回到 assess 重评；分够 → END。
带重试计数防死循环。

    START → assess → retrieve → recommend → review ──┐
              ▲                                        │ 分低 且 没超次数
              └────────────────────────────────────────┘（★回边：图可以有环）
                                                      │ 分够 或 超次数
                                                      END

★ 为什么体现 LangGraph 价值：这条"review→回 assess"的回边，在图里就是一条【条件边指回前面】。
  手写要用 while 套整个流程 + 手动管计数 + 小心死循环，代码会绕；图里就是"多连一条边"。

学两个特性：① 回边=条件边指向前面的节点（图有环）；② 循环安全=State 计数器 + recursion_limit。

前置：另开终端起 bridge。运行：cd langgraph-lab && .venv/bin/python lg_02_loop_graph.py
"""
from __future__ import annotations

import os
import random
from typing import Literal, TypedDict

import httpx
from anthropic import Anthropic
from langgraph.graph import END, START, StateGraph

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
MODEL = "claude-haiku-4-5-20251001"
_client = Anthropic(base_url="http://localhost:8787", api_key="x",
                    http_client=httpx.Client(trust_env=False))


def call_bridge_tool(system: str, user: str, tool: dict, retries: int = 2) -> dict:
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            with _client.messages.stream(model=MODEL, system=system, max_tokens=1024,
                                         messages=[{"role": "user", "content": user}], tools=[tool]) as s:
                final = s.get_final_message()
            for b in final.content:
                if getattr(b, "type", None) == "tool_use":
                    return dict(b.input)
            return {}
        except Exception as e:  # noqa: BLE001
            last = e
    raise last  # type: ignore[misc]


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


MAX_ATTEMPTS = 3   # 重试上限（对应你手写的 MAX_STEPS）


# ---- State：比 lg_01 多了 review 分数 + 重试计数 ----
class State(TypedDict):
    customer_desc: str
    risk_level: str          # assess 写
    dimensions: dict         # assess 写
    products: list           # retrieve 写
    recommendation: dict     # recommend 写
    review_score: float      # review 写：推荐质量 0–1
    attempts: int            # assess 每进一次 +1，用于防死循环


ASSESS_TOOL = {"name": "assess", "description": "给 5 个维度打 1–5 分。",
               "input_schema": {"type": "object", "properties": {"dimensions": {"type": "object",
                                "description": "键：experience/loss_tolerance/income_stability/"
                                               "investment_horizon/volatility_tolerance，值 1–5。"}},
                                "required": ["dimensions"]}}
RECOMMEND_TOOL = {"name": "recommend", "description": "从候选里挑一款，code 必须来自候选。",
                  "input_schema": {"type": "object", "properties": {"recommended_code": {"type": "string"},
                                   "reason": {"type": "string"}}, "required": ["recommended_code", "reason"]}}


def assess_node(state: State) -> dict:
    out = call_bridge_tool("你是风险评估助手，只调用 assess 给 5 维打分。", state["customer_desc"], ASSESS_TOOL)
    dims = out.get("dimensions", {})
    values = [v for v in dims.values() if isinstance(v, (int, float))]
    level = level_from_dims(values)
    attempts = state.get("attempts", 0) + 1
    print(f"  〔assess 第{attempts}次〕→ 等级={level}")
    return {"risk_level": level, "dimensions": dims, "attempts": attempts}


def retrieve_node(state: State) -> dict:
    products = [p for r in MATCH_RULES.get(state["risk_level"], []) for p in FAKE_DB.get(r, [])]
    return {"products": products}


def recommend_node(state: State) -> dict:
    listing = "\n".join(f"[{p['code']}] {p['name']}" for p in state["products"])
    out = call_bridge_tool("你是推荐助手，只能从候选清单里推荐。",
                           f"等级 {state['risk_level']}，候选：\n{listing}\n推荐一款。", RECOMMEND_TOOL)
    return {"recommendation": out}


def review_node(state: State) -> dict:
    """给推荐质量打分 0–1（这里用随机模拟"有时不靠谱"，好触发回边——真实里会用 LLM-judge/规则）。"""
    score = round(random.uniform(0.4, 0.55), 2)   # 临时压低到恒 < 0.6，必触发回边（看重评循环）
    print(f"  〔review〕推荐={state['recommendation'].get('recommended_code')} 评分={score}")
    return {"review_score": score}


# ========================= 你的 TODO：路由 + 建图（回边）=========================

def route_after_review(state: State) -> Literal["assess", "__end__"]:
    """TODO#1：review 之后的路由——决定"回 assess 重来"还是"结束"。
    规则：
      · 若 review_score < 0.6 且 attempts < MAX_ATTEMPTS → 返回 "assess"（★回边，重新评估）；
      · 否则（分够 或 已达重试上限）→ 返回 END。
    提示：返回字符串 "assess" 或 END。这就是"图可以有环"——条件边指回前面的节点。
    """
    return END if state["review_score"] >= 0.6 or state["attempts"] >= MAX_ATTEMPTS else "assess"


def build_graph():
    """TODO#2：把节点连成【带回边】的图，返回 compile() 后的 app。

    结构：START→assess→retrieve→recommend→review→(条件: 回 assess / END)
      1) g = StateGraph(State)
      2) 四个节点都 add_node（assess/retrieve/recommend/review）
      3) 边：
         START→assess, assess→retrieve, retrieve→recommend, recommend→review （四条普通边）
         g.add_conditional_edges("review", route_after_review)   # ★ 条件边，可能指回 assess
      4) return g.compile()
    """
    g = StateGraph(State)
    g.add_node("assess", assess_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("recommend", recommend_node)
    g.add_node("review", review_node)
    g.add_edge(START, "assess")
    g.add_edge("assess", "retrieve")
    g.add_edge("retrieve", "recommend") 
    g.add_edge("recommend", "review")
    g.add_conditional_edges("review", route_after_review)
    return g.compile()

# =============================================================================


def main() -> None:
    app = build_graph()
    desc = "我炒股 5 年，能扛波动但受不了腰斩，钱放 3-5 年，有稳定工资。"
    print(f"=== 客户：{desc[:22]}… ===")
    # recursion_limit：LangGraph 防无限循环的硬兜底（图跑的总步数上限）——对应手写的 MAX_STEPS。
    result = app.invoke({"customer_desc": desc}, {"recursion_limit": 20})
    print(f"\n  最终：等级={result['risk_level']} 推荐={result['recommendation'].get('recommended_code')} "
          f"评分={result['review_score']} 评估轮数={result['attempts']}")


if __name__ == "__main__":
    main()
