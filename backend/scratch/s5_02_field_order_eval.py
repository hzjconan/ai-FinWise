"""阶段五 · s5_02（B#8）：用 eval 量化"conclude 字段顺序"改动值不值

假设（见 docs/05-field-order-and-schema-as-prompt.md）：tool 的 input_schema 里字段
顺序影响输出质量——模型自回归、按 schema 顺序逐字段吐，**先写的字段成为后写字段的上下文**。
conclude 现状是「结论在前」(content, risk_preference, summary, dimensions)：模型先拍
等级、再补维度分（事后凑）。若把 dimensions 挪到最前，模型先认真打维度分、再据此结论——
理论上维度打分更认真。

★ 但这是纯"质量"改动，单测测不出（没有 assert 能测"打分有没有更认真"）——
  只能用 eval：准备"客户人设→期望等级"的 golden set，两种字段顺序各跑真机，量【定级准确率】。
  这就是把 [[05-field-order]] 的理论假设，变成一个可回归的数字来验证，而非凭理论盲改 schema。

注意 B#7 的影响：定级已去模型化（等级由 calculate_risk_preference(dimensions) 算、不信
模型自报的 risk_preference）。所以字段顺序影响的是 **dimensions 打分质量** → 进而影响
算出的等级。故 A/B 只差 dimensions 的位置（单变量）：
  A = 现状：content, risk_preference, summary, dimensions
  B = 只挪：dimensions, content, risk_preference, summary

前置：另开终端 `bash backend/scratch/run_bridge.sh`
运行：cd backend && .venv/bin/python scratch/s5_02_field_order_eval.py
（真机多轮 × 多人设 × 2 变体，较慢；temperature 被 bridge 忽略，结果有噪声——见文末讨论）
"""
from __future__ import annotations

import asyncio
import copy

import httpx
from anthropic import AsyncAnthropic

from _bridge import BRIDGE_BASE_URL, MODEL, section

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.customer import Customer
from app.models.product import Product
from app.services import chat_service
from app.services.llm.anthropic_client import AnthropicLLMClient


# ========================= 你的 TODO：eval 的地基 =========================

# TODO#1：golden set —— 一批"客户人设"，每个含 6 轮固定答话 + 期望等级 expected。
#   这是 eval 的灵魂（回忆 s5_01：结论完全取决于 golden set，要先质疑题）。出题要点：
#     · 覆盖不同真实风险画像（保守→激进都要有），别全挤在中间；
#     · answers 是模拟用户逐轮回答，尽量口语、别直接报等级（"我是C4"这种作弊）；
#     · expected 是你判断这个画像"应该"落哪个 C 级——这判断本身要经得起质疑；
#     · 边界画像（维度分算出来正好卡档，如均值 3.6→72→C4）最能考验字段顺序的作用。
#   下面给了 1 个示例，照着再补 3~4 个（覆盖 C1/C2 保守、C4/C5 激进）。
PERSONAS: list[dict] = [
    {
        "name": "稳健有经验",
        "answers": [
            "我炒股 5 年了，能接受一定波动，但接受不了本金腰斩。",
            "跌 20% 我扛不住，10% 左右还能接受。",
            "这笔钱打算放 3 到 5 年。",
            "我有稳定工资收入，也有一些存款。",
            "账户短期跌了我一般先观望，不会马上割。",
            "差不多了，你直接给我评估结论吧。",
        ],
        "expected": "C4",   # 你判断的期望等级（可质疑：均值≈3.6→72→C4，边界画像）
    },
    # TODO: 再补 3~4 个人设，覆盖 C1/C2（保守：怕亏、短期、无经验）和 C5（激进：年轻能扛、追高收益）
    {
        "name": "理财新人保守型",
        "answers": [
            "我之前没有做过任何理财",
            "我不希望有任何本金亏损",
            "我打算把这笔钱存1-2年",
            "我目前没有收入，只有一些存款",
            "如果亏损了我希望马上赎回",
            "差不多了，你直接给我评估结论吧。",
        ],
        "expected": "C2",
    },
    {
        "name": "理财新人稳健型",
        "answers": [
            "我之前没有做过任何理财",
            "我可以接受20%以内的亏损",
            "我打算把这笔钱存3年",
            "我目前有收入并且有一些存款",
            "如果亏损在10%一下我会观望，在10——20%会考虑赎回，一旦亏损大于20%立即赎回",
            "差不多了，你直接给我评估结论吧。",
        ],
        "expected": "C3",
    },
        {
        "name": "理财老手激进型",
        "answers": [
            "我之前有过多年的股票经验",
            "我可以接受30%以内的亏损",
            "我打算把这笔钱存5年",
            "我目前有收入并且有一些存款足以应对5年内的开支",
            "只有亏损超过10%才考虑赎回",
            "差不多了，你直接给我评估结论吧。",
        ],
        "expected": "C5",
    }
]

# ======================================================================


def _setup_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    db.add(Customer(code="CUS-EVAL", nickname="Eval 客户"))
    for lvl, name, ret in [
        ("R1", "稳盈货币A", "0.021"), ("R2", "短债精选C", "0.034"),
        ("R3", "稳健配置FOF", "0.05"), ("R4", "成长精选混合", "0.085"),
        ("R5", "高弹性成长股基", "0.15"),
    ]:
        db.add(Product(product_code=f"P-{lvl}", name=name, type="基金",
                       status="active", risk_level=lvl, expected_return=ret))
    db.commit()
    return db


def _reorder_conclude(schema: list[dict], order: list[str]) -> list[dict]:
    """返回 TOOLS_SCHEMA 的深拷贝，其中 conclude 工具的 properties 按 order 重排。
    （properties 顺序影响生成质量；required 顺序不影响，不用动。）"""
    out = copy.deepcopy(schema)
    for tool in out:
        if tool["name"] == chat_service.TOOL_CONCLUDE:
            props = tool["input_schema"]["properties"]
            tool["input_schema"]["properties"] = {k: props[k] for k in order}
    return out


# 两种字段顺序（只差 dimensions 的位置）
ORDER_A = ["content", "risk_preference", "summary", "dimensions"]   # 现状：结论在前
ORDER_B = ["dimensions", "content", "risk_preference", "summary"]   # 只挪：dimensions 打头


def _make_llm():
    return AnthropicLLMClient(
        client=AsyncAnthropic(base_url=BRIDGE_BASE_URL, api_key="dummy",
                              http_client=httpx.AsyncClient(trust_env=False)),
        model=MODEL, max_tokens=1024,
    )


async def run_one(persona: dict) -> str | None:
    """跑一个人设走完整评估链路，返回最终定级（C1–C5）或 None（没跑到结论）。
    依赖调用方已把 chat_service.TOOLS_SCHEMA 换成想测的字段顺序。"""
    db = _setup_db()
    llm = _make_llm()
    customer = chat_service.find_customer(db, "CUS-EVAL")
    session = chat_service.create_session(db, customer.id)
    await chat_service.generate_opening(db, session, llm)

    for ans in persona["answers"]:
        assessment = None
        async for ev in chat_service.handle_user_message(db, session, ans, llm):
            if ev["event"] == "completed" and ev["data"]["phase"] == "concluded":
                assessment = ev["data"].get("assessment")
            elif ev["event"] == "error":
                return None
        if assessment:
            return assessment["risk_preference"]
    return None


async def eval_variant(label: str, order: list[str]) -> None:
    """把字段顺序切成 order，跑整个 golden set，打印定级准确率。"""
    original = chat_service.TOOLS_SCHEMA
    chat_service.TOOLS_SCHEMA = _reorder_conclude(original, order)  # 临时替换
    try:
        correct, total = 0, 0
        for p in PERSONAS:
            try:
                got = await run_one(p)          # 真机会偶发失败（claude CLI 返 1）——
            except Exception as e:              # 兜住单点失败，记为 ERR、继续跑，别毁整轮
                got = f"ERR({type(e).__name__})"
            ok = (got == p["expected"])
            correct += int(ok)
            total += 1
            print(f"    {p['name']}: 期望 {p['expected']} / 实得 {got}  {'✓' if ok else '✗'}")
        print(f"  【{label}】定级准确率 = {correct}/{total} = {correct / total:.2f}\n")
    finally:
        chat_service.TOOLS_SCHEMA = original  # 还原，别污染


async def main() -> None:
    if len(PERSONAS) < 2:
        print("⚠️ 先在 PERSONAS 里补齐 golden set（至少 3~4 个覆盖不同等级的人设）再跑。")
        return
    print(f"golden set 共 {len(PERSONAS)} 个人设；A/B 只差 dimensions 位置\n")
    section("A 现状（结论在前）")
    await eval_variant("A 现状", ORDER_A)
    section("B 只挪 dimensions 到最前")
    await eval_variant("B dimensions打头", ORDER_B)
    print("→ 对比 A/B 准确率：字段顺序这个纯质量改动，到底有没有让定级更准？"
          "\n  注意 n 很小、模型有噪声——差异不显著时别急着下结论（真实 eval 要多跑几轮/扩 golden set）。")


if __name__ == "__main__":
    asyncio.run(main())
