"""阶段四 · s4_03：TF-IDF vs embedding 对照——「语义检索 为什么强过 关键词」眼见为实

s4_01 用 embedding 造向量。这里手写 **TF-IDF**（纯词频，字面匹配）造向量，
插进【同一套检索核心】（复用 s4_01 的 cosine_similarity / retrieve_top_k），
在【同一批 query】上和 embedding **并排对比**。

★ 这就是 s4_01 留的可插拔 Encoder 接口的兑现：检索核心一行不改，只换 encoder。
  你会亲眼看到 TF-IDF 在「养老→退休储备」这种**跨字面**需求上**失效**——因为它只认
  字面词、不认意思。这把「语义 > 关键词」从道理变成眼见的对比（阶段四验收）。

TF-IDF 是什么（手写、全过程可见，不用库）：
  - 把文本切成「词」（中文这里用**字符 bigram**：连续两字当一个词，零依赖分词）
  - 一个词对一篇文档的权重 = TF × IDF
      · TF（term frequency）：该词在这篇文档里出现几次——越多越重要
      · IDF（inverse document frequency）：log(N / 含该词的文档数)——
        越"稀有"（只在少数文档出现）越有区分度；到处都有的词权重被压低
  - 每篇文档 → 一个 |vocab| 维稀疏向量（大部分是 0）；query 同样向量化，再算余弦

对比 embedding：TF-IDF 的向量维度 = 词表大小、每维对应一个具体的词（可解释）；
embedding 是 384 维稠密、每维不可解释但含语义。**根本差别：TF-IDF 比字面，embedding 比意思。**

运行（不需要 bridge，纯本地）：
    cd backend && .venv/bin/python scratch/s4_03_tfidf_vs_embedding.py
"""
from __future__ import annotations

import math

import numpy as np

# 复用 s4_01：检索核心（cosine/top-k）、语料、embedding encoder、Encoder 接口
from s4_01_rag_embedding import (
    CORPUS,
    Encoder,
    EmbeddingEncoder,
    cosine_similarity,  # noqa: F401  （retrieve_top_k 内部用；这里显式导入表明复用同一实现）
    retrieve_top_k,
)


QUERIES = [
    "有没有适合养老、能放很多年的产品？",     # 关键：query 说"养老"，文档写"退休储备"——字面不重合
    "我想要能随时取出来、基本不会亏的",
    "能接受大波动，想博一把高收益",
]


def _tokenize(text: str) -> list[str]:
    """中文极简分词：取连续字符 bigram（零依赖）。
    例：'养老储备' → ['养老','老储','储备']。过滤标点/空白。
    单字文本退化为该单字。"""
    chars = [c for c in text if c.strip() and c not in "，。、：；！？…（）「」《》()【】的了吗呢啊呀"]
    if len(chars) < 2:
        return chars
    return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]


# ========================= 你的两个 TODO：TF-IDF 的灵魂 =========================

def compute_idf(docs_tokens: list[list[str]], vocab: dict[str, int]) -> np.ndarray:
    """TODO#1：算每个词的 IDF，返回长度 = len(vocab) 的向量，idf[vocab[词]] = 该词的 idf。

    IDF(词) = log( N / df )
      · N   = 文档总数 = len(docs_tokens)
      · df  = 含该词的文档数（document frequency）——遍历 docs_tokens 数一下几篇里出现过
    含义：df 越大（越多文档都有它）→ idf 越小 → 越是"大路货"、区分度越低。
    提示：vocab 是 {词: 下标}；df≥1（词都来自文档），不用担心 log(N/0)。
    """
    n = len(docs_tokens)
    df = np.zeros(len(vocab), dtype=int)
    for toks in docs_tokens:
        for term in set(toks):
            df[vocab[term]] += 1
    return np.log(n / df)


def vectorize(tokens: list[str], vocab: dict[str, int], idf: np.ndarray) -> np.ndarray:
    """TODO#2：把一段文本的 tokens 变成 TF-IDF 向量（长度 = len(vocab)）。

    做法：
      1) 先数 TF：开一个长度 len(vocab) 的零向量，tokens 里每出现一个"在 vocab 里"的词，
         对应下标 +1（不在 vocab 里的词——如 query 独有的——忽略）；
      2) 再乘 IDF：整个 TF 向量逐位乘以 idf 向量（np 广播：tf * idf）。
    返回这个 tf-idf 向量。（query 和文档都用这个函数；query 用的是【文档集学到的】vocab/idf。）
    """
    tf = np.zeros(len(vocab), dtype=int)
    for term in tokens:
        if term in vocab:
            tf[vocab[term]] += 1
    return tf * idf

# =============================================================================


class TfidfEncoder(Encoder):
    """手写 TF-IDF encoder，实现 s4_01 的 Encoder 接口，drop-in 替换 EmbeddingEncoder。

    注意 fit/transform 的顺序：encode_docs 时【从文档集学出】vocab 和 idf 并记住；
    encode_query 时【复用】它们——这样 query 和文档在同一套词表/权重下才可比。
    """

    def __init__(self) -> None:
        self.vocab: dict[str, int] = {}
        self.idf: np.ndarray | None = None

    def encode_docs(self, texts: list[str]) -> np.ndarray:
        docs_tokens = [_tokenize(t) for t in texts]
        # 从所有文档收集词表（排序保证下标稳定）
        all_terms = sorted({t for toks in docs_tokens for t in toks})
        self.vocab = {term: i for i, term in enumerate(all_terms)}
        self.idf = compute_idf(docs_tokens, self.vocab)          # TODO#1
        return np.array([vectorize(toks, self.vocab, self.idf) for toks in docs_tokens])  # TODO#2

    def encode_query(self, text: str) -> np.ndarray:
        assert self.idf is not None, "先 encode_docs 再 encode_query"
        return vectorize(_tokenize(text), self.vocab, self.idf)  # 复用文档集学到的 vocab/idf


def _run_encoder(name: str, encoder: Encoder) -> dict[str, list[tuple[int, float]]]:
    doc_vecs = np.asarray(encoder.encode_docs([d["text"] for d in CORPUS]))
    print(f"\n【{name}】doc 向量矩阵 {doc_vecs.shape}"
          + (f"（{doc_vecs.shape[1]} 维 = 词表大小）" if name == "TF-IDF" else "（384 维稠密语义）"))
    out = {}
    for q in QUERIES:
        out[q] = retrieve_top_k(encoder.encode_query(q), doc_vecs, k=2)
    return out


def main() -> None:
    emb = _run_encoder("Embedding", EmbeddingEncoder())
    tfidf = _run_encoder("TF-IDF", TfidfEncoder())

    print("\n" + "=" * 72)
    print("并排对比（同一 query、同一检索核心，只换 encoder）")
    print("=" * 72)
    for q in QUERIES:
        print(f"\n❓ {q}")
        print("  embedding →", [f"{CORPUS[i]['name']}({s:.2f})" for i, s in emb[q]])
        print("  TF-IDF    →", [f"{CORPUS[i]['name']}({s:.2f})" for i, s in tfidf[q]])


if __name__ == "__main__":
    main()
