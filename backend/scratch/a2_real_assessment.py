"""阶段 3 · A#2：真机跑一次评估——观察真实模型会不会主动调 search_products。

和单测(test_conclude_after_search 用 mock 脚本)不同，这里用【真实 bridge LLM】驱动
【真实 chat_service 评估流程】，套一层日志包装记录模型每轮调了什么工具。

关注点：search_products 已经在 TOOLS_SCHEMA 里（模型能调），但评估的 system prompt
只讲了 ask/conclude、没引导它查产品——模型到底会不会主动去调 search_products？

前置：另开终端 bash backend/scratch/run_bridge.sh

运行（两组对比）：
  1) 默认业务 prompt（不引导查产品）——预期：全程 ask→conclude，不调 search_products
     cd backend && .venv/bin/python scratch/a2_real_assessment.py
  2) 自定义「引导查产品」prompt——预期：conclude 前先调 search_products，且结论引用真实产品
     用环境变量 FINWISE_SYSTEM_PROMPT_FILE 指向 scratch/a2_experiment_prompt.md（load_system_prompt
     支持该 env 覆盖，见 app/services/llm/prompts.py），不改业务 prompt / 本脚本：
     cd backend && FINWISE_SYSTEM_PROMPT_FILE="$(pwd)/scratch/a2_experiment_prompt.md" \
         .venv/bin/python scratch/a2_real_assessment.py

  对比结论：工具在 TOOLS_SCHEMA 里 ≠ 模型会用它——是否调 search 由 prompt 引导决定。
"""
from __future__ import annotations

import asyncio

import httpx
from anthropic import AsyncAnthropic

from _bridge import BRIDGE_BASE_URL, MODEL, section  # 导入即把 backend 加进 sys.path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.customer import Customer
from app.models.product import Product
from app.services import chat_service
from app.services.llm.anthropic_client import AnthropicLLMClient
from app.services.llm.events import ToolResult


# ---- 日志包装：记录模型每轮调了什么工具（search 是内部的、不吐事件，只能这样看） ----
class ToolLoggingLLM:
    def __init__(self, inner):
        self.inner = inner
        self.tool_calls: list[str] = []

    async def stream_chat(self, *, system, messages, tools):
        async for ev in self.inner.stream_chat(system=system, messages=messages, tools=tools):
            if isinstance(ev, ToolResult):
                self.tool_calls.append(ev.name)
                print(f"      〔模型调用工具〕{ev.name}  input={ev.input}")
            yield ev


def _setup_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    # 客户
    db.add(Customer(code="CUS-A2", nickname="A2 测试客户"))
    # 各等级各放一个 active 产品，便于 search_products 若被调用能返回东西
    for lvl, name, ret in [
        ("C1", "稳盈货币A", "0.021"), ("C2", "短债精选C", "0.034"),
        ("C3", "稳健配置FOF", "0.05"), ("C4", "成长精选混合", "0.085"),
        ("C5", "高弹性成长股基", "0.15"),
    ]:
        db.add(Product(product_code=f"P-{lvl}", name=name, type="基金",
                       status="active", risk_level=lvl, expected_return=ret))
    db.commit()
    return db


async def main() -> None:
    db = _setup_db()
    # 真实 bridge-backed LLM（trust_env=False 绕开本机 HTTP_PROXY 对 localhost 的劫持）
    raw = AnthropicLLMClient(
        client=AsyncAnthropic(base_url=BRIDGE_BASE_URL, api_key="dummy",
                              http_client=httpx.AsyncClient(trust_env=False)),
        model=MODEL, max_tokens=1024,
    )
    llm = ToolLoggingLLM(raw)

    customer = chat_service.find_customer(db, "CUS-A2")
    session = chat_service.create_session(db, customer.id)

    section("开场白（generate_opening）")
    opening = await chat_service.generate_opening(db, session, llm)
    print("助手:", opening.content)

    # 一个固定人设，按序喂给模型（覆盖 5 维度）；模型问够了就会 conclude
    answers = [
        "我炒股 5 年了，能接受一定波动，但接受不了本金腰斩。",
        "跌 20% 我扛不住，10% 左右还能接受。",
        "这笔钱打算放 3 到 5 年。",
        "我有稳定工资收入，也有一些存款。",
        "账户短期跌了我一般先观望，不会马上割。",
        "差不多了，你直接给我评估结论吧。",
    ]

    for i, ans in enumerate(answers, 1):
        section(f"第 {i} 轮 · 用户: {ans}")
        parts: list[str] = []
        phase = None
        assessment = None
        async for ev in chat_service.handle_user_message(db, session, ans, llm):
            if ev["event"] == "delta":
                parts.append(ev["data"]["content"])
            elif ev["event"] == "completed":
                phase = ev["data"]["phase"]
                assessment = ev["data"].get("assessment")
            elif ev["event"] == "error":
                print("  ✗ error:", ev["data"])
                phase = "error"
        print("助手:", "".join(parts) or "(无文本)")
        if phase == "concluded":
            print(f"  ✅ 评估完成：{assessment['risk_preference']} / {assessment['risk_label']}")
            break
        if phase == "error":
            break

    section("统计")
    print("模型总共调用的工具序列:", llm.tool_calls)
    print("是否主动调用过 search_products:", "是" if "search_products" in llm.tool_calls else "否")


asyncio.run(main())
