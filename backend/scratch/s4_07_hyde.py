"""L01 · 7e · s4_07：HyDE——先让 LLM 写"假想答案"，再拿它去检索

讲义：docs/ai-agent-learning/lessons/L01-hybrid-retrieval.md（第 6 步 Query 改写、7e）

HyDE = Hypothetical Document Embeddings（假想文档嵌入）：
  用户问句短、口语化；产品说明长、书面化 → 两者"不像"。
  先让 LLM 针对问题写一段【像产品说明一样】的假想答案，用它去检索——
  "文档 vs 文档"比"问句 vs 文档"更像。假答案可能是编的，没关系：只用来检索，不给用户看。

在 B 套口语题（s5_01）上对比 4 种检索：
  ① 原 query 向量              —— 基线（= s4_06 的 ① 纯向量）
  ② HyDE 向量                  —— 只用假想文档检索
  ③ RRF(原 query 向量, HyDE 向量)        —— 原 query 一起检索（第 6 步"最稳的防法"）
  ④ RRF(两个 query × 向量/BM25 共 4 路) —— 第 6 步追问里的"4 次查询"

★ 预防针：库只有 7 篇，基线 Hit@3 已经 0.83，提升空间很小。
  这次的价值主要在【亲眼看到假想文档长什么样】和【流程怎么接】，不在分数。

前置：bridge 已启动（bash backend/scratch/run_bridge.sh）
运行：cd backend && .venv/bin/python scratch/s4_07_hyde.py
测试：cd backend && .venv/bin/python -m pytest scratch/test_s4_07_hyde.py -v
"""
from __future__ import annotations

import asyncio

import numpy as np

from _bridge import call_tool, make_client, section
from s4_01_rag_embedding import EmbeddingEncoder, retrieve_top_k
from s4_06_hybrid_rerank import (
    CANDIDATES,
    CODES,
    DOC_TEXTS,
    K,
    BM25Index,
    _pad,
    evaluate,
    rrf_fuse,
)
from s5_01_retrieval_eval import GOLDEN_REALISTIC

# bridge 要求每次调用都带工具，模型以工具 JSON 返回 → 用一个工具收"假想文档"
HYDE_TOOL = {
    "name": "write_hypothetical_doc",
    "description": "返回针对用户问题写的假想产品说明。",
    "input_schema": {
        "type": "object",
        "properties": {"doc": {"type": "string", "description": "假想的产品说明文本"}},
        "required": ["doc"],
    },
}


# ========================= TODO 7e-1：HyDE 的 prompt =========================
# 写给 LLM 的 system prompt：让它针对用户问题，写一段"像我们库里产品说明那样"的假想文档。
# 想一想要约束哪些点（提示：对照 s4_01 CORPUS 的描述长什么样）：
#   - 写成什么文体？多长？
#   - 要不要写具体产品名 / 代码 / 收益率数字？（写了会怎样？想想 L01 第 2 步 BM25 和精确词）
HYDE_SYSTEM = (
    "针对用户的问题，写一段像基金产品说明那样的文档，依次写清：产品类型、风险和收益特点、适合什么样的投资者。"
    "注意：不要出现任何产品名字、编码，也不要写任何数字（收益率、期限天数、年份等），只根据用户的输入生成产品描述，"
    "控制在 50 字左右。"
)

# =============================================================================


async def generate_hypothetical_doc(client, question: str) -> str:
    """调一次 LLM，返回假想文档文本。"""
    blocks = await call_tool(
        client,
        system=HYDE_SYSTEM,
        messages=[{"role": "user", "content": f"用户问题：{question}"}],
        tools=[HYDE_TOOL],
        max_tokens=512,
        retries=2,
    )
    for b in blocks:
        if b["name"] == "write_hypothetical_doc":
            return b["input"].get("doc", "")
    return ""


# ========================= TODO 7e-2：用假想文档检索 =========================

def hyde_search(hypo_doc: str, encoder, doc_vecs: np.ndarray, n: int) -> list[int]:
    """TODO 7e-2：把假想文档编码成向量，检索最相似的 n 篇，返回文档下标列表（降序）。

    关键决定：假想文档该用 encoder.encode_query 还是 encoder.encode_docs 编码？
      🔁 s4_01：e5 约定文档加 "passage: "、查询加 "query: " 前缀——
         encode_docs 走 passage，encode_query 走 query。
      注意 encode_docs 接收【文本列表】、返回 (N, dim) 矩阵；encode_query 接收一条文本、返回 (dim,)。
    检索部分复用 s4_01 的 retrieve_top_k(query_vec, doc_vecs, k)，它返回 [(下标, 分数), ...]。
    """
    hypo_vec = encoder.encode_docs([hypo_doc])[0]   # 假想文档当"文档"编码：走 passage: 前缀
    return [i for i, _ in retrieve_top_k(hypo_vec, doc_vecs, k=n)]

# =============================================================================


async def main() -> None:
    emb = EmbeddingEncoder()
    doc_vecs = np.asarray(emb.encode_docs(DOC_TEXTS))
    bm25 = BM25Index(DOC_TEXTS)
    client = make_client()

    # 每道题只调一次 LLM，结果缓存下来给 4 种检索器共用
    section("HyDE：LLM 写的假想文档")
    hypo: dict[str, str] = {}
    for question, expected in GOLDEN_REALISTIC:
        hypo[question] = await generate_hypothetical_doc(client, question)
        print(f"\n❓ {question}   （期望 {expected}）\n📝 {hypo[question]}")

    def vec(q: str) -> list[int]:
        return [i for i, _ in retrieve_top_k(emb.encode_query(q), doc_vecs, k=CANDIDATES)]

    def hyde(q: str) -> list[int]:
        return hyde_search(hypo[q], emb, doc_vecs, CANDIDATES)

    retrievers = {
        "① 原 query 向量": vec,
        "② HyDE 向量": hyde,
        "③ RRF(原+HyDE)": lambda q: rrf_fuse([vec(q), hyde(q)]),
        "④ RRF 4 路": lambda q: rrf_fuse([vec(q), hyde(q),
                                         bm25.search(q, CANDIDATES), bm25.search(hypo[q], CANDIDATES)]),
    }

    section(f"B 套口语题（{len(GOLDEN_REALISTIC)} 条），评 top-{K}")
    print(_pad("", 18) + _pad(f"Hit@{K}", 8) + "MRR")
    for name, retrieve in retrievers.items():
        hit, mrr = evaluate(retrieve, GOLDEN_REALISTIC, CODES)
        print(_pad(name, 18) + _pad(f"{hit:.2f}", 8) + f"{mrr:.3f}")

    section("逐题名次（期望产品排第几，- = 没进候选）")
    print(_pad("query", 34) + "".join(_pad(n[:1], 4) for n in retrievers))
    for question, expected in GOLDEN_REALISTIC:
        cells = []
        for retrieve in retrievers.values():
            ranked = [CODES[i] for i in retrieve(question)]
            cells.append(_pad(str(ranked.index(expected) + 1) if expected in ranked else "-", 4))
        print(_pad(question, 34) + "".join(cells))


if __name__ == "__main__":
    asyncio.run(main())
