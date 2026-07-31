"""阶段四 · s4_02：最小 RAG 的「生成」半段——检索到的产品塞进 prompt 让模型作答

s4_01 做了【检索】（query → top-k 产品）。这里接上【生成】：把检索到的产品作为
「上下文」塞进 prompt，让模型**基于这些产品**回答用户问题——这才是完整的
RAG（Retrieval-Augmented Generation，检索增强生成）。

复用 s4_01 的检索（直接 import 它的 EmbeddingEncoder / CORPUS / retrieve_top_k），
本脚本只新增两件 RAG 特有的事，正是你的两个 TODO：
  ① build_context：把 top-k 产品拼成给模型看的「上下文」文本
  ② SYSTEM_PROMPT：让模型【只用上下文作答、不许编造】——即 grounding（接地）

★ 关键学习点：grounding。RAG 防幻觉的核心 = 强制模型"只根据我给的资料回答，
  没有就说没有"，而不是用它自己的先验瞎编。脚本最后一个 query 故意问一个语料里
  没有的东西（房贷），用来检验模型会不会老实说"没有"。

前置：另开一个终端启动 bridge（本地 claude CLI，无需 API key）：
    bash backend/scratch/run_bridge.sh
运行：
    cd backend && .venv/bin/python scratch/s4_02_rag_generate.py
"""
from __future__ import annotations

import asyncio

import httpx
from anthropic import AsyncAnthropic

# 复用共享 bridge 配置（导入即把 backend 加进 sys.path）
from _bridge import BRIDGE_BASE_URL, DUMMY_KEY, MODEL, section

# ★ 复用 s4_01 的检索，不重复造轮子（import 不会触发它的 main，被 __main__ 守卫住）
from s4_01_rag_embedding import CORPUS, EmbeddingEncoder, retrieve_top_k


QUERIES = [
    "有没有适合养老、能放很多年的产品？",
    "我想要能随时取出来、基本不会亏的",
    "能接受大波动，想博一把高收益",
    "有没有能贷款买房的产品？",   # ← 语料里没有！用来检验 grounding：模型该说"没有"
]


# ========================= 你的两个 TODO =========================

def build_context(hits: list[tuple[int, float]]) -> str:
    """TODO#1：把检索到的 top-k 产品拼成一段「上下文」文本，供塞进 prompt。

    hits 是 retrieve_top_k 的返回，形如 [(doc_index, score), ...]。
    要用 doc_index 去 CORPUS 里取产品，拼成模型好读的清单。建议每个产品一行，
    带上 name 和 text（可选带 code）。例如：
        - 稳盈货币A：货币市场基金，随时申购赎回……
        - 安心养老目标2040：养老目标日期基金……
    返回这段多行字符串即可。
    """
    return "\n".join([f"{CORPUS[idx]['name']}：{CORPUS[idx]['text']}" for idx, _score in hits])


# TODO#2：写 grounding 系统提示词——让模型【只依据下面提供的产品清单作答】：
#   - 只能用「产品清单」里的信息回答，不得编造清单里没有的产品或数据；
#   - 若清单里没有能满足用户需求的产品，如实说明「暂无合适产品」，不要硬凑；
#   - 语气专业亲和，简洁。
SYSTEM_PROMPT = """只能用「产品清单」里的信息回答，不得编造清单里没有的产品或数据；
若清单里没有能满足用户需求的产品，如实说明「暂无合适产品」，不要硬凑；
语气专业亲和，简洁。"""

# ===============================================================


# ---- LLM 调用（bridge 要求每次带 tool，故用一个 provide_answer 工具收回答）----
ANSWER_TOOL = {
    "name": "provide_answer",
    "description": "把给用户的最终回答用这个工具返回。",
    "input_schema": {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    },
}


async def answer_with_llm(client: AsyncAnthropic, question: str, context: str) -> str:
    """把「上下文 + 问题」发给模型，取回它调用 provide_answer 给出的回答文本。"""
    user_content = f"产品清单：\n{context}\n\n用户问题：{question}"
    async with client.messages.stream(
        model=MODEL,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        tools=[ANSWER_TOOL],
        tool_choice={"type": "tool", "name": "provide_answer"},
        max_tokens=1024,
    ) as stream:
        final = await stream.get_final_message()
    for block in final.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "provide_answer":
            return block.input.get("answer", "")
    return "(模型未返回 answer)"


async def main() -> None:
    encoder = EmbeddingEncoder()
    # 语料只需编码一次（真实系统里离线预计算存起来）
    doc_vecs = encoder.encode_docs([d["text"] for d in CORPUS])

    client = AsyncAnthropic(
        base_url=BRIDGE_BASE_URL, api_key=DUMMY_KEY,
        http_client=httpx.AsyncClient(trust_env=False),  # 绕开本机 HTTP_PROXY 对 localhost 的劫持
    )

    import numpy as np
    for q in QUERIES:
        section(f"用户：{q}")
        # 1) 检索（复用 s4_01）
        hits = retrieve_top_k(encoder.encode_query(q), np.asarray(doc_vecs), k=3)
        print("〔检索到的候选〕")
        for idx, score in hits:
            print(f"    {score:.3f}  {CORPUS[idx]['name']}")
        # 2) 拼上下文 → 3) 让模型基于上下文作答
        context = build_context(hits)
        answer = await answer_with_llm(client, q, context)
        print("\n〔模型回答〕", answer)


if __name__ == "__main__":
    asyncio.run(main())
