"""阶段六 · s6_02：多 agent 协作——supervisor 编排「评估 agent + 推荐 agent」

前面都是【单 agent】：一个模型 + 一堆工具 + 一个 loop。这里学【多 agent】：多个各有专长的
agent 分工，由一个 supervisor（主管）编排。

为什么拆多个：一个任务若有明显不同的子职责、各需不同 prompt/工具/知识，塞进一个 agent 会
prompt 冗长、工具打架、精力分散。拆开则每个 agent 专注、可独立测试/复用。

FinWise 的天然拆分（你 B#3–B#7 / s4 做过的两件事）：
  · 评估 agent：读客户描述 → 打 5 维分 → 定风险等级（关键值确定性算，非模型自报，见 B#7）
  · 推荐 agent：拿等级 → C→R 映射查产品 → grounded 推荐（只推清单内产品，见 s4_02b）

supervisor 模式（本练习）：主管【硬编排】——不干活，只决定"先派谁、把谁的输出喂给谁"：
    supervisor(客户描述)
        → 调 评估 agent，拿到【结构化】{risk_level, dimensions}
        → 用 risk_level 做 C→R 检索，拿到候选产品
        → 调 推荐 agent（喂入等级 + 候选产品）
        → 汇总返回
★ agent 间传【结构化数据】{risk_level,...}（可校验、确定性），而非自然语言（易丢信息/幻觉）——
  延续你学的"关键值别信模型自由发挥"。

前置：另开终端 `bash backend/scratch/run_bridge.sh`
运行：cd backend && .venv/bin/python scratch/s6_02_multi_agent.py
"""
from __future__ import annotations

import asyncio

from _bridge import call_tool, make_client, section

from app.services.risk_calculator import MATCH_RULES, calculate_risk_preference


# ---- 假产品库（R 级！产品是 R1–R5，客户偏好是 C1–C5，靠 MATCH_RULES 桥接，见 B#6）----
FAKE_DB = {
    "R1": [{"code": "P-R1", "name": "稳盈货币A", "expected_return": 0.021}],
    "R2": [{"code": "P-R2", "name": "短债精选C", "expected_return": 0.034}],
    "R3": [{"code": "P-R3", "name": "稳健配置FOF", "expected_return": 0.05}],
    "R4": [{"code": "P-R4", "name": "成长精选混合", "expected_return": 0.085}],
    "R5": [{"code": "P-R5", "name": "高弹性成长股基", "expected_return": 0.15}],
}

CUSTOMERS = [
    "我炒股 5 年了，能接受一定波动但受不了腰斩，钱打算放 3-5 年，有稳定工资。",
    "我完全没理财过，一分本金都不能亏，钱一年内可能就要用。",
]


# ========================= 专职 agent ①：评估（已实现）=========================
ASSESS_TOOL = {
    "name": "assess",
    "description": "根据客户描述给 5 个维度打 1–5 分。",
    "input_schema": {
        "type": "object",
        "properties": {
            "dimensions": {
                "type": "object",
                "description": "键必须是这 5 个：experience/loss_tolerance/income_stability/"
                               "investment_horizon/volatility_tolerance，值为 1–5 整数。",
            }
        },
        "required": ["dimensions"],
    },
}


async def assessment_agent(client, customer_desc: str) -> dict:
    """评估 agent：客户描述 → 5 维分 → 【确定性算】风险等级。返回结构化 {risk_level, dimensions}。
    注意：等级由 calculate_risk_preference 算（B#7 去模型化），不问模型要 risk_preference。"""
    blocks = await call_tool(
        client,
        system="你是风险评估助手。只调用 assess 工具，给 5 个维度各打 1–5 分。",
        messages=[{"role": "user", "content": customer_desc}],
        tools=[ASSESS_TOOL],
    )
    dims = blocks[0]["input"]["dimensions"]
    values = [v for v in dims.values() if isinstance(v, (int, float))]
    _, code, *_ = calculate_risk_preference(sum(values), len(values) * 5)
    return {"risk_level": code, "dimensions": dims}


# ========================= 专职 agent ②：推荐（已实现）=========================
RECOMMEND_TOOL = {
    "name": "recommend",
    "description": "从候选产品里挑一款推荐。recommended_code 必须来自候选清单。",
    "input_schema": {
        "type": "object",
        "properties": {
            "recommended_code": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["recommended_code", "reason"],
    },
}


async def recommendation_agent(client, risk_level: str, products: list[dict]) -> dict:
    """推荐 agent：拿【等级 + 候选产品】→ grounded 推荐（只推清单内的）。"""
    listing = "\n".join(f"[{p['code']}] {p['name']}（预期收益 {p['expected_return']}）" for p in products)
    blocks = await call_tool(
        client,
        system="你是产品推荐助手。只能从给定候选清单里推荐，recommended_code 必须是清单中的 code。",
        messages=[{"role": "user", "content": f"客户风险等级：{risk_level}\n候选产品：\n{listing}\n请推荐一款。"}],
        tools=[RECOMMEND_TOOL],
    )
    return blocks[0]["input"]


# ---- C→R 检索（确定性，非 agent；供 supervisor 在两个 agent 之间调用）----
def retrieve_products(risk_level: str) -> list[dict]:
    """把客户 C 级映射成产品 R 级（MATCH_RULES.exact），查 FAKE_DB 返回候选。"""
    r_levels = MATCH_RULES.get(risk_level, {}).get("exact", [])
    out: list[dict] = []
    for r in r_levels:
        out.extend(FAKE_DB.get(r, []))
    return out


# ========================= 你的 TODO：supervisor 编排 =========================

async def supervisor(client, customer_desc: str) -> dict:
    """TODO：主管编排——把两个 agent + 检索串起来，返回汇总结果。

    步骤（硬编排，你写死顺序）：
      1) 调 assessment_agent(client, customer_desc) → 拿 {risk_level, dimensions}；
      2) 用 risk_level 调 retrieve_products(risk_level) → 拿候选产品列表；
         （若候选为空，说明该等级没产品——可直接返回"暂无产品"，别硬调推荐 agent）
      3) 调 recommendation_agent(client, risk_level, 候选) → 拿 {recommended_code, reason}；
      4) 返回汇总 dict，如 {"risk_level":..., "dimensions":..., "recommendation":...}。
    ★ 观察点：agent 间传的是【结构化 risk_level】，不是让 agent1 写段话给 agent2 猜。
    提示：这是纯 Python 编排（async，记得 await 每个 agent）——多 agent 的"协作"逻辑就在这里，
         supervisor 自己不调 LLM，只当调度员。
    """
    assessment = await assessment_agent(client, customer_desc)
    risk_level = assessment["risk_level"]
    dims = assessment["dimensions"]
    products = retrieve_products(risk_level)
    if not products:
        return {"risk_level": risk_level, "dimensions": dims, "recommendation": "暂无产品"}
    return {"risk_level": risk_level, "dimensions": dims, "recommendation": await recommendation_agent(client, risk_level, products)}

# =============================================================================


async def main() -> None:
    client = make_client()
    for desc in CUSTOMERS:
        section(f"客户：{desc[:24]}…")
        result = await supervisor(client, desc)
        print("  supervisor 汇总：", result)


if __name__ == "__main__":
    asyncio.run(main())
