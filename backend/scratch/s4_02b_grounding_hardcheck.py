"""阶段四 · s4_02b：给 RAG 的 grounding 加「服务端硬校验」——软约束之外的第 3 层

背景（你的质疑，非常对）：s4_02 只靠 SYSTEM_PROMPT 让模型"别编产品"——但那是
**软约束**（恳求模型自律），不是硬保证。换模型/换刁钻问法时，模型仍可能张冠李戴或
编一个清单里没有的产品。关键系统要分层加固，越往下越硬（见 concepts-basics
「Grounding 与分层防御」）：
  1. prompt grounding（软，s4_02 已做）
  2. 结构化 + 引用约束：让模型必须输出它推荐的 product_code
  3. ★ 服务端硬校验（本练习）：模型给的 code 必须 ∈ 检索候选集，否则判定为幻觉、拦下
  4. 兜底：拦下后返回安全话术，不把可疑答案给用户

这正是 [[03-agent-loop-lessons]] 那套"别信模型"（B#6/B#7 硬校验、定级去模型化）
迁移到 RAG——不信模型"answer 里的产品真来自清单"，用代码核对。

做法变化 vs s4_02：
- 让模型用工具返回**结构化**结果：recommended_code（推荐的产品代码）+ answer（话术）；
  "无合适产品"时 code 传空串。
- 服务端拿到 recommended_code 后，**核对它在不在这次检索的候选集里**：
  · 在 → 放行；· 不在（且非空）→ 判定幻觉，拦下换成安全话术。

前置：另开终端 `bash backend/scratch/run_bridge.sh`
运行：`cd backend && .venv/bin/python scratch/s4_02b_grounding_hardcheck.py`
"""
from __future__ import annotations

import asyncio

import httpx
import numpy as np
from anthropic import AsyncAnthropic

from _bridge import BRIDGE_BASE_URL, DUMMY_KEY, MODEL, section
from s4_01_rag_embedding import CORPUS, EmbeddingEncoder, retrieve_top_k

QUERIES = [
    "有没有适合养老、能放很多年的产品？",
    "能接受大波动，想博一把高收益",
    "有没有能贷款买房的产品？",   # 语料没有 → 期望模型传空 code；即便它硬编，硬校验也能拦
]


# 让模型返回「结构化」结果：推荐哪个 code + 话术。code 必须来自候选，否则留空。
RECOMMEND_TOOL = {
    "name": "recommend",
    "description": "根据产品清单给出推荐。只能推荐清单中的产品。",
    "input_schema": {
        "type": "object",
        "properties": {
            "recommended_code": {
                "type": "string",
                "description": "推荐产品的 code，必须来自产品清单；若无合适产品则传空字符串。",
            },
            "answer": {"type": "string", "description": "给用户的回答话术。"},
        },
        "required": ["recommended_code", "answer"],
    },
}

SYSTEM_PROMPT = (
    "你是理财推荐助手。只能依据「产品清单」推荐，recommended_code 必须是清单中某个产品的 code；"
    "若清单里没有能满足用户需求的产品，recommended_code 传空字符串、并在 answer 里说明暂无合适产品。"
    "不得编造清单外的产品。语气专业亲和、简洁。"
)


def build_context(hits: list[tuple[int, float]]) -> str:
    """把候选拼成带 code 的清单（模型需要看到 code 才能引用）。"""
    return "\n".join(f"[{CORPUS[i]['code']}] {CORPUS[i]['name']}：{CORPUS[i]['text']}" for i, _ in hits)


async def recommend_with_llm(client: AsyncAnthropic, question: str, context: str) -> dict:
    """调模型，取回 {recommended_code, answer}。"""
    user_content = f"产品清单：\n{context}\n\n用户问题：{question}"
    async with client.messages.stream(
        model=MODEL, system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        tools=[RECOMMEND_TOOL], tool_choice={"type": "tool", "name": "recommend"},
        max_tokens=1024,
    ) as stream:
        final = await stream.get_final_message()
    for block in final.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "recommend":
            return dict(block.input)
    return {"recommended_code": "", "answer": "(模型未返回)"}


# ========================= 你的 TODO：服务端硬校验 =========================

def verify_recommendation(result: dict, candidate_codes: set[str]) -> tuple[bool, str]:
    """TODO：核对模型推荐的 code 是否真来自本次检索候选集——防幻觉的第 3 层（硬）。

    入参：
      - result：模型返回的 {"recommended_code": str, "answer": str}
      - candidate_codes：本次检索候选的 code 集合（模型只被允许在这里面选）
    规则：
      1) recommended_code 为空串 → 视为"模型自称无合适产品"，放行（合法结果）：
         返回 (True, result["answer"])
      2) recommended_code ∈ candidate_codes → 引用真实，放行：返回 (True, result["answer"])
      3) recommended_code 非空但 ∉ candidate_codes → ★判定为幻觉（模型编了个清单外的 code），
         拦下：返回 (False, 一句安全兜底话术，如"暂无合适产品，请调整需求或咨询人工")
    提示：这就是 B#6/B#7 的"别信模型的值"在 RAG 的版本——不信它给的 code，拿候选集核对。
    """
    if result["recommended_code"] == "":
        return True, result["answer"]
    if result["recommended_code"] in candidate_codes:
        return True, result["answer"]
    return False, "暂无合适产品，请调整需求或咨询人工"




# =========================================================================


async def main() -> None:
    encoder = EmbeddingEncoder()
    doc_vecs = encoder.encode_docs([d["text"] for d in CORPUS])
    client = AsyncAnthropic(
        base_url=BRIDGE_BASE_URL, api_key=DUMMY_KEY,
        http_client=httpx.AsyncClient(trust_env=False),
    )

    for q in QUERIES:
        section(f"用户：{q}")
        hits = retrieve_top_k(encoder.encode_query(q), np.asarray(doc_vecs), k=3)
        candidate_codes = {CORPUS[i]["code"] for i, _ in hits}
        print("〔候选 code〕", candidate_codes)

        result = await recommend_with_llm(client, q, build_context(hits))
        print(f"〔模型原始返回〕 code={result['recommended_code']!r}")

        ok, final_answer = verify_recommendation(result, candidate_codes)
        flag = "✅ 放行" if ok else "🛑 拦下（疑似幻觉）"
        print(f"〔硬校验〕 {flag}")
        print(f"〔最终回答〕 {final_answer}")

def _selftest_hardcheck():
    """不依赖 LLM，直接验证三条规则——尤其规则3（幻觉拦下）这条真机难触发的。"""
    cands = {"P-MMF", "P-TECH"}
    # 规则1：空 code → 放行
    ok, _ = verify_recommendation({"recommended_code": "", "answer": "暂无"}, cands)
    assert ok is True
    # 规则2：命中候选 → 放行
    ok, ans = verify_recommendation({"recommended_code": "P-TECH", "answer": "推荐科技股"}, cands)
    assert ok is True and ans == "推荐科技股"
    # 规则3：★编了个清单外的 code → 必须拦下
    ok, ans = verify_recommendation({"recommended_code": "P-HOUSE-LOAN", "answer": "给您推荐房贷产品X"}, cands)
    assert ok is False and "暂无" in ans        # 假答案被换成安全话术，没漏给用户
    print("✅ 硬校验自测通过（含幻觉拦下）")

if __name__ == "__main__":
    _selftest_hardcheck()
    asyncio.run(main())
