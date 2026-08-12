"""LangGraph 基础 · lg_01：把 s6_02 手写 supervisor 用 LangGraph 图重写

s6_02 你【手写】了 supervisor：await assess → retrieve → if 空 → await recommend。
这里用 LangGraph 把同一套编排画成一张【图】，对照"手写编排 → 节点/边/状态"（见 langgraph-notes）。

对照：
  s6_02 手写                          LangGraph
  层层传参的变量                        → State（TypedDict，贯穿全图）
  assessment_agent / retrieve / ...    → Node（吃 state、返回要更新的字段）
  "先 assess 后 retrieve" 的顺序        → Edge
  if not products                      → Conditional edge
  supervisor() 函数                     → 编译后的 graph，app.invoke()

本练习：State / 三个节点 / LLM helper 都给你了；★唯一 TODO = build_graph()（连边）。

环境：隔离 venv。前置：另开终端起 bridge（backend/scratch/run_bridge.sh）。
运行：cd langgraph-lab && .venv/bin/python lg_01_linear_graph.py
"""
from __future__ import annotations

import os
from typing import TypedDict

import httpx
from anthropic import Anthropic
from langgraph.graph import END, START, StateGraph

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")   # 绕本机代理对 localhost 的劫持
MODEL = "claude-haiku-4-5-20251001"

_client = Anthropic(base_url="http://localhost:8787", api_key="x",
                    http_client=httpx.Client(trust_env=False))


def call_bridge_tool(system: str, user: str, tool: dict, retries: int = 2) -> dict:
    """走本地 bridge 调一次 LLM，返回它调用的工具 input（裸 SDK，bridge 兼容——见 langgraph-notes）。

    bridge 偶发失败（claude CLI 返回 1）——重试 retries 次，重试通常就好（同 backend call_tool）。
    注意：LangGraph 默认「节点抛异常 = 整个图崩」，所以容错得自己兜（或用节点 retry_policy，lg_02 学）。
    """
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            with _client.messages.stream(
                model=MODEL, system=system, max_tokens=1024,
                messages=[{"role": "user", "content": user}], tools=[tool],
            ) as stream:
                final = stream.get_final_message()
            for b in final.content:
                if getattr(b, "type", None) == "tool_use":
                    return dict(b.input)
            return {}
        except Exception as e:  # noqa: BLE001  瞬时/bridge 错误 → 重试
            last = e
    raise last  # type: ignore[misc]


# ---- 领域小工具（内联，保持 langgraph-lab 独立、不 import backend）----
MATCH_RULES = {"C1": ["R1"], "C2": ["R2"], "C3": ["R3"], "C4": ["R4"], "C5": ["R5"]}
FAKE_DB = {
    "R1": [{"code": "P-R1", "name": "稳盈货币A"}], "R2": [{"code": "P-R2", "name": "短债精选C"}],
    "R3": [{"code": "P-R3", "name": "稳健配置FOF"}], "R4": [{"code": "P-R4", "name": "成长精选混合"}],
    "R5": [{"code": "P-R5", "name": "高弹性成长股基"}],
}


def level_from_dims(values: list) -> str:
    """5 维分均值 × 20 → 阈值定级（<20 C1 / <40 C2 / <60 C3 / <80 C4 / else C5）。"""
    normalized = sum(values) / len(values) * 20 if values else 0
    for thr, code in [(20, "C1"), (40, "C2"), (60, "C3"), (80, "C4")]:
        if normalized < thr:
            return code
    return "C5"


# ---- State：贯穿全图的共享数据（取代手写编排里层层传的变量）----
class State(TypedDict):
    customer_desc: str            # 输入
    risk_level: str               # assess 节点写
    dimensions: dict              # assess 节点写
    products: list                # retrieve 节点写
    recommendation: dict          # recommend 节点写


# ---- 三个节点：吃 state、返回「要 merge 进 state 的字段」（都给你写好了）----
ASSESS_TOOL = {
    "name": "assess", "description": "给 5 个维度打 1–5 分。",
    "input_schema": {"type": "object",
                     "properties": {"dimensions": {"type": "object",
                                    "description": "键：experience/loss_tolerance/income_stability/"
                                                   "investment_horizon/volatility_tolerance，值 1–5。"}},
                     "required": ["dimensions"]},
}
RECOMMEND_TOOL = {
    "name": "recommend", "description": "从候选里挑一款，recommended_code 必须来自候选。",
    "input_schema": {"type": "object",
                     "properties": {"recommended_code": {"type": "string"}, "reason": {"type": "string"}},
                     "required": ["recommended_code", "reason"]},
}


def assess_node(state: State) -> dict:
    out = call_bridge_tool("你是风险评估助手，只调用 assess 给 5 维打分。",
                           state["customer_desc"], ASSESS_TOOL)
    dims = out.get("dimensions", {})
    values = [v for v in dims.values() if isinstance(v, (int, float))]
    print(f"  〔assess 节点〕维度={dims} → 等级={level_from_dims(values)}")
    return {"risk_level": level_from_dims(values), "dimensions": dims}


def retrieve_node(state: State) -> dict:
    r_levels = MATCH_RULES.get(state["risk_level"], [])
    products = [p for r in r_levels for p in FAKE_DB.get(r, [])]
    print(f"  〔retrieve 节点〕{state['risk_level']} → 候选={[p['code'] for p in products]}")
    return {"products": products}


def recommend_node(state: State) -> dict:
    listing = "\n".join(f"[{p['code']}] {p['name']}" for p in state["products"])
    out = call_bridge_tool("你是推荐助手，只能从候选清单里推荐。",
                           f"等级 {state['risk_level']}，候选：\n{listing}\n推荐一款。", RECOMMEND_TOOL)
    print(f"  〔recommend 节点〕→ {out}")
    return {"recommendation": out}


# ========================= 你的 TODO：build_graph（连边）=========================

def route_after_retrieve(state: State) -> str:
    """条件边的路由函数：候选为空 → 直接结束（END）；否则去 recommend 节点。
    （对应 s6_02 手写的 `if not products: return 暂无`。）返回下一个节点名或 END。"""
    return END if not state["products"] else "recommend"


def build_graph():
    """TODO：用 LangGraph 把三个节点连成图，返回 compile() 后的 app。

    要连的结构（就是 s6_02 supervisor 的顺序）：
        START → assess → retrieve →（条件：空 END / 非空 recommend）→ END

    步骤：
      1) g = StateGraph(State)
      2) 加节点：g.add_node("assess", assess_node)  三个都加（retrieve/recommend 同理）
      3) 加边：
         g.add_edge(START, "assess")            # 入口
         g.add_edge("assess", "retrieve")       # 普通边（顺序）
         g.add_conditional_edges("retrieve", route_after_retrieve)   # 条件边（用上面的路由函数）
         g.add_edge("recommend", END)           # recommend 完 → 结束
      4) return g.compile()
    """
    g = StateGraph(State)
    g.add_node("assess", assess_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("recommend", recommend_node)
    g.add_edge(START, "assess")
    g.add_edge("assess", "retrieve")
    g.add_conditional_edges("retrieve", route_after_retrieve)
    g.add_edge("recommend", END)
    return g.compile()

# =============================================================================


def main() -> None:
    app = build_graph()
    for desc in [
        "我炒股 5 年，能扛波动但受不了腰斩，钱放 3-5 年，有稳定工资。",
        "我完全没理财过，一分本金都不能亏，钱一年内可能就要用。",
    ]:
        print(f"\n=== 客户：{desc[:22]}… ===")
        result = app.invoke({"customer_desc": desc})   # ← 跑图 = s6_02 的 supervisor(desc)
        print("  最终 State：", {k: result.get(k) for k in ("risk_level", "recommendation")})


if __name__ == "__main__":
    main()
