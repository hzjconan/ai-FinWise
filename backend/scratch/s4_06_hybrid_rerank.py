"""第 1 课 · s4_06：混合检索 + RRF + 重排——把讲义第 1~5 步落到代码上

讲义：docs/ai-agent-learning/lessons/L01-hybrid-retrieval.md

本脚本搭了 4 种检索器，在 3 套 golden set 上用 s5_01 的 Hit@K / MRR 对比：
  ① 纯向量（Bi-Encoder，e5）           —— s4_01 的老朋友
  ② 纯 BM25（关键词）                   —— 讲义第 1 步，TODO 7a
  ③ 混合：向量 + BM25，RRF 融合         —— 讲义第 4 步，TODO 7b
  ④ 混合 + Cross-Encoder 重排           —— 讲义第 5 步，TODO 7c

4 套题：A（字面≈文档）、B（口语，跨字面）沿用 s5_01；
       C（精确匹配：编号/数字/产品名）新增，验证讲义第 2 步"BM25 擅长精确词"；
       C'（同一批 C 题，但库里加入 3 个困难负样本：只差一个数字/字母的"双胞胎"产品）。
         C 里 embedding 也拿满分——因为库里没有长得像的竞争者，"大概像"就够了。
         C' 补上干扰项后，名次可能仍对，所以另打印【分差】：看各路把正确答案和双胞胎拉开多远。

★ 和 s5_01 的一个差别：这里每篇文档的检索文本 = 产品名 + 描述（s5_01 只用描述），
  因为 C 套题会搜"2040""30天"这类只出现在产品名里的词。所以 ① 的分数和 s5_01 不完全相同。
★ 预防针：库里只有 7 篇，top-3 已是全库近一半，重排的提升可能不明显——这本身也是结论。

运行（纯本地，首次会下载 bge-reranker-base ≈1.1GB）：
    cd backend && .venv/bin/python scratch/s4_06_hybrid_rerank.py
测试：
    cd backend && .venv/bin/python -m pytest scratch/test_s4_06_hybrid_rerank.py -v
"""
from __future__ import annotations

import math
import unicodedata
from collections import Counter

import numpy as np

from s4_01_rag_embedding import CORPUS, EmbeddingEncoder, cosine_similarity, retrieve_top_k
from s4_03_tfidf_vs_embedding import _tokenize
from s5_01_retrieval_eval import (
    GOLDEN_KEYWORD_FRIENDLY,
    GOLDEN_REALISTIC,
    hit_at_k,
    reciprocal_rank,
)

CODES = [d["code"] for d in CORPUS]
DOC_TEXTS = [f"{d['name']}：{d['text']}" for d in CORPUS]   # 产品名 + 描述

# C「精确匹配」：query 里的关键信息是编号、数字或产品名里的专有词，几乎没有"语义"可言
GOLDEN_EXACT: list[tuple[str, str]] = [
    ("2040那只还能买吗", "P-PENSION"),      # 只有产品名里有"2040"
    ("30天持有的那个", "P-SHORTBOND"),      # "30天"
    ("ETF联接怎么样", "P-GOLD"),            # 英文缩写 + 专有词
    ("稳盈A", "P-MMF"),                     # 产品简称
    ("灵活配置那只", "P-MIX"),
    ("纯债那个", "P-BOND"),
]

# 困难负样本（Hard Negative）：和正确答案"长得像但不是它"——描述完全相同，只有名字差一个数字/字母
HARD_NEGATIVES: list[dict] = [
    {"code": "P-PENSION35", "name": "安心养老目标2035",          # vs 2040
     "text": "养老目标日期基金，长期持有，权益仓位随临近退休逐年下降，为退休储备而设计。"},
    {"code": "P-SHORTBOND60", "name": "短债60天持有",            # vs 30 天
     "text": "短期债券基金，收益略高于货币基金，最短持有60天，兼顾一定流动性与收益。"},
    {"code": "P-MMF-B", "name": "稳盈货币B",                     # vs 稳盈货币A
     "text": "货币市场基金，随时申购赎回，几乎无波动，适合放随时可能用到的活钱和应急备用金。"},
]
HARD_CORPUS = CORPUS + HARD_NEGATIVES
HARD_CODES = [d["code"] for d in HARD_CORPUS]
HARD_TEXTS = [f"{d['name']}：{d['text']}" for d in HARD_CORPUS]
# 正确答案 → 它的双胞胎干扰项
TWIN = {"P-PENSION": "P-PENSION35", "P-SHORTBOND": "P-SHORTBOND60", "P-MMF": "P-MMF-B"}
# C' 只评有双胞胎的 3 题（2040 / 30天 / 稳盈A）；其余 3 题在 HARD_CORPUS 里没有对手，结果和 C 一样
GOLDEN_EXACT_HARD = [(q, code) for q, code in GOLDEN_EXACT if code in TWIN]

K = 3              # 评 top-K（与 s5_01 一致）
CANDIDATES = 5     # 每一路召回多少篇进入融合 / 重排（讲义第 5 步的"漏斗"第一层）


# ========================= TODO 7a：BM25 单个词的得分 =========================

def bm25_term_score(tf: int, idf: float, doc_len: int, avgdl: float,
                    k1: float = 1.2, b: float = 0.75) -> float:
    """TODO 7a：返回【一个词】对【一篇文档】的 BM25 得分（讲义第 1 步公式，Σ 里面那一项）。

                     idf × tf × (k1 + 1)
        得分 = ─────────────────────────────────────
               tf + k1 × (1 − b + b × doc_len / avgdl)

    参数（对照讲义符号表）：
      tf      —— 该词在这篇文档里出现的次数（当前文档）
      idf     —— 该词的 IDF（全库统计，BM25Index 已替你算好传进来）
      doc_len —— 这篇文档的词数 |d|（当前文档）
      avgdl   —— 全库平均文档词数（全库统计）
      k1, b   —— 人工常数，默认 1.2 / 0.75
    提示：tf == 0 时得分就是 0（分子为 0），公式自然成立，不用特判。
    自检：tf=1, idf=1, doc_len=20, avgdl=200 → ≈1.58（讲义里的 A）
    """
    return idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * doc_len / avgdl))

# =============================================================================


class BM25Index:
    """BM25 检索器：建库时统计 tf / df / 文档长度 / avgdl（全库统计，算一次），
    查询时对 query 的每个词调用 bm25_term_score 再相加（讲义：打分 = 各词得分相加，不算余弦）。"""

    def __init__(self, texts: list[str], k1: float = 1.2, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs_tf = [Counter(_tokenize(t)) for t in texts]          # 每篇：{词: 次数}
        self.doc_lens = [sum(tf.values()) for tf in self.docs_tf]        # 每篇词数 |d|
        self.avgdl = sum(self.doc_lens) / len(self.doc_lens)             # 全库平均长度
        n = len(texts)
        df = Counter(term for tf in self.docs_tf for term in tf)         # 含该词的文档数
        # BM25 平滑版 IDF（讲义第 1 步毛病③）：永远 > 0
        self.idf = {t: math.log((n - d + 0.5) / (d + 0.5) + 1) for t, d in df.items()}

    def score(self, query: str, doc_idx: int) -> float:
        tf = self.docs_tf[doc_idx]
        return sum(
            bm25_term_score(tf[t], self.idf[t], self.doc_lens[doc_idx], self.avgdl, self.k1, self.b)
            for t in _tokenize(query) if t in self.idf          # 库里没有的词：贡献 0，跳过
        )

    def search(self, query: str, n: int) -> list[int]:
        """返回得分 > 0 的前 n 篇文档下标（得分为 0 = 一个词都没对上 = 没召回）。"""
        scored = [(i, self.score(query, i)) for i in range(len(self.docs_tf))]
        scored = [x for x in scored if x[1] > 0]
        return [i for i, _ in sorted(scored, key=lambda x: x[1], reverse=True)[:n]]


# ========================= TODO 7b：RRF 融合 =========================

def rrf_fuse(rankings: list[list[int]], k: int = 60) -> list[int]:
    """TODO 7b：把多路检索结果按 RRF 合并，返回按 RRF 分数【降序】排列的文档下标列表。

        RRF(d) = Σ  1 / (k + rank_r(d))      （讲义第 4 步）
                 r

    参数：
      rankings —— 每一路的结果，形如 [[3, 0, 5], [3, 6, 1]]：每个内层列表是一路检索器
                  按相关度排好的文档下标（第 0 个元素 = 第 1 名）
      k        —— 平滑常数，默认 60
    提示：
      - 名次从 1 开始：enumerate(ranking, start=1)
      - 用一个 dict 累加 {文档下标: RRF 分数}；某一路没出现的文档，那一路自然不加分（= 记 0）
      - 最后按分数降序排序，只返回下标
    自检：rrf_fuse([[1, 2, 9], [3, 4, 9]]) 里，9 两路都排第 3 → 2/63 ≈ 0.0317，
         比只在一路排第 1 的 1 和 3（1/61 ≈ 0.0164）高 → 9 排第一（讲义的 X / Y）
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking, start=1):
            scores[doc] = scores.get(doc, 0) + 1 / (k + rank)
    return sorted(scores, key=lambda d: scores[d], reverse=True)

# =====================================================================


# ========================= TODO 7c：Cross-Encoder 重排 =========================

def rerank(query: str, candidates: list[int], texts: list[str], model) -> list[int]:
    """TODO 7c：用 Cross-Encoder 给候选重新打分，返回按分数【降序】排列的候选下标。

    参数：
      candidates —— 召回 / 融合后得到的候选文档下标
      texts      —— 全部文档文本（用下标取）
      model      —— sentence_transformers.CrossEncoder 实例（测试里会换成假模型）
    用法：model.predict(pairs) 接收 [(query, 文档文本), ...]，返回等长的分数数组，
         分数越高越相关（讲义第 5 步："query 和文档拼在一起送进模型"就发生在 predict 里）。
    提示：先拼 pairs → 一次 predict 批量打分 → 把 (下标, 分数) 配对后按分数降序 → 只返回下标。

    ⚠️ 练习简化，不是生产设计：传入全库 `texts`、再用下标取候选文本。
      - 传参本身不贵：Python 传的是引用，不会复制列表；函数里也只用到候选那几篇。
      - 真正的问题在前提：要能传 texts，就得先把全库文本整体加载进内存——百万级文档不可行。
      - 生产做法：重排只需要【候选】的文本，按 ID 取，只取几十篇：
          ① 召回时一起返回文本（如 Chroma `query(..., include=["documents"])`）；
          ② 或只拿 ID，再去数据库 / KV 批量取（`SELECT text FROM chunks WHERE id IN (...)`）。
        接口相应地直接收候选文本，不收全库：
          def rerank(query: str, candidates: list[tuple[str, str]], model) -> list[str]:
              # candidates = [(doc_id, text), ...]
      - 这里保留"下标 + 全库列表"，只因库仅 7 篇、本就在内存里，且能和 rrf_fuse 返回的下标直接接上。
    """
    pairs = [(query, texts[c]) for c in candidates]
    scores = model.predict(pairs)
    return [c for c, _ in sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)]

# =============================================================================


def build_retrievers(texts: list[str], emb, reranker):
    """在给定文档集上搭 4 种检索器，每个都是 query -> 排好序的文档下标列表。
    模型由调用方传入：两套文档集（原库 / 加困难负样本的库）共用同一对模型，只加载一次。"""
    doc_vecs = np.asarray(emb.encode_docs(texts))
    bm25 = BM25Index(texts)

    def vector(q: str) -> list[int]:
        return [i for i, _ in retrieve_top_k(emb.encode_query(q), doc_vecs, k=CANDIDATES)]

    def keyword(q: str) -> list[int]:
        return bm25.search(q, CANDIDATES)

    def hybrid(q: str) -> list[int]:
        return rrf_fuse([vector(q), keyword(q)])

    def hybrid_rerank(q: str) -> list[int]:
        return rerank(q, hybrid(q), texts, reranker)

    return {"① 纯向量": vector, "② 纯 BM25": keyword,
            "③ 混合 RRF": hybrid, "④ 混合+重排": hybrid_rerank}


def evaluate(retrieve, golden: list[tuple[str, str]], codes: list[str]) -> tuple[float, float]:
    """复用 s5_01 的指标：取 top-K 算 Hit@K 和 MRR。codes 把下标翻译成产品 code。"""
    hits, rrs = [], []
    for query, expected in golden:
        ranked_codes = [codes[i] for i in retrieve(query)[:K]]
        hits.append(hit_at_k(ranked_codes, expected))
        rrs.append(reciprocal_rank(ranked_codes, expected))
    return sum(hits) / len(golden), sum(rrs) / len(golden)


def print_twin_margins(emb) -> None:
    """C' 的分差：正确答案 vs 它的双胞胎，各路分数差多少。
    名次相同（都排对）时，分差大 = 区分得干脆；分差小 = 险胜，真实库里干扰项一多就可能翻。"""
    doc_vecs = np.asarray(emb.encode_docs(HARD_TEXTS))
    bm25 = BM25Index(HARD_TEXTS)
    print(f"\nC' 分差（正确答案 vs 双胞胎干扰项）")
    print(_pad("query", 20) + _pad("向量 余弦", 22) + "BM25 得分")
    for query, expected in GOLDEN_EXACT_HARD:
        i, j = HARD_CODES.index(expected), HARD_CODES.index(TWIN[expected])
        qv = emb.encode_query(query)
        v_ok, v_twin = cosine_similarity(qv, doc_vecs[i]), cosine_similarity(qv, doc_vecs[j])
        b_ok, b_twin = bm25.score(query, i), bm25.score(query, j)
        print(_pad(query, 20)
              + _pad(f"{v_ok:.3f} vs {v_twin:.3f}", 22)
              + f"{b_ok:.2f} vs {b_twin:.2f}")


def main() -> None:
    from sentence_transformers import CrossEncoder

    emb = EmbeddingEncoder()
    print("[加载模型] BAAI/bge-reranker-base …（首次会下载权重）")
    reranker = CrossEncoder("BAAI/bge-reranker-base")
    base = build_retrievers(DOC_TEXTS, emb, reranker)
    hard = build_retrievers(HARD_TEXTS, emb, reranker)

    # (套题名, golden set, 检索器组, code 表)
    suites = [("A 字面≈文档", GOLDEN_KEYWORD_FRIENDLY, base, CODES),
              ("B 口语跨字面", GOLDEN_REALISTIC, base, CODES),
              ("C 精确匹配", GOLDEN_EXACT, base, CODES),
              ("C' +困难负样本", GOLDEN_EXACT_HARD, hard, HARD_CODES)]
    print(f"\n每路召回 {CANDIDATES} 篇，评 top-{K}。每套题两列：Hit@{K} 和 MRR")
    print(f"（C' = C 里有双胞胎的 3 题，库里加了 3 个只差一个数字/字母的干扰产品）\n")
    print(_pad("", 14) + "".join(_pad(s[0], 20) for s in suites))
    print(_pad("", 14) + "".join(_pad(f"Hit@{K}", 8) + _pad("MRR", 12) for _ in suites))
    for r_name in base:
        cells = []
        for _, golden, retrievers, codes in suites:
            hit, mrr = evaluate(retrievers[r_name], golden, codes)
            cells.append(_pad(f"{hit:.2f}", 8) + _pad(f"{mrr:.3f}", 12))
        print(_pad(r_name, 14) + "".join(cells))

    print_twin_margins(emb)


def _pad(text: str, width: int) -> str:
    """按终端显示宽度左对齐补空格（中文等全角字符占 2 格，f-string 的宽度只按字符数算会错位）。"""
    shown = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
    return text + " " * max(width - shown, 1)


if __name__ == "__main__":
    main()
