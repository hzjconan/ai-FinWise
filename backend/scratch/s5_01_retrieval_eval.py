"""阶段五 · s5_01：检索 eval——把"检索好不好"从眼睛看变成一个可回归的分数

前面 s4_03（embedding vs TF-IDF）、s4_04（chunk 怎么切）都是【眼睛看】结果好坏。
但"哪个更好"不能凭感觉——这正是 eval 要解决的：给一批标准题、自动打分、让质量变成
一个能盯着升降的数字。这就是「AI 功能的测试 = eval」（对应仓库"改动必须有测试"的铁律）。

eval 三件套（记住，后面所有 eval 都是这套骨架）：
  1) golden set：一批 (query, 期望命中的产品 code) ——你定义"什么叫对"，eval 的地基
  2) 指标 metric：把"对不对"聚合成一个数
     · Hit@K：期望产品出现在 top-K 里的比例（召回视角，0~1，越高越好）
     · MRR  ：平均倒数排名 = mean(1/rank)；期望产品排第 1→1.0、第 2→0.5、第 3→0.33、
              没进 top-K→0（排序质量视角，比 Hit 更细，也惩罚"命中但排得靠后"）
  3) 可回归：同一 golden set + 指标，换 encoder（embedding/TF-IDF）分数直接可比

本练习：用同一 golden set，给 embedding 和 TF-IDF 两个检索器各算 Hit@K / MRR，
量化 s4_03 那个"语义 > 关键词"的结论。复用 s4_01 的 CORPUS/检索、s4_03 的 TfidfEncoder。

运行（纯本地）：cd backend && .venv/bin/python scratch/s5_01_retrieval_eval.py
"""
from __future__ import annotations

import numpy as np

from s4_01_rag_embedding import CORPUS, EmbeddingEncoder, retrieve_top_k
from s4_03_tfidf_vs_embedding import TfidfEncoder

# CORPUS 里各产品的 code（下标 → code），用来把检索命中的下标翻译成 code 判对错
CODES = [d["code"] for d in CORPUS]

# ---- 两套 golden set：同一对检索器、同一指标，只换题，看结论会不会翻转 ----
#   ★ 这演示 eval 的头号陷阱：结论完全取决于 golden set。题有偏，结论就有偏。
#   （code 见 s4_01 CORPUS：P-MMF 货币 / P-PENSION 养老 / P-TECH 科技 / P-BOND 纯债 /
#     P-GOLD 黄金 / P-SHORTBOND 短债 / P-MIX 混合）

# A「送分给 TF-IDF」：query 里的词几乎【原样出现在目标文档】——字面高度重合，
#   对靠字面匹配的 TF-IDF 是送分题，测不出真实语义能力。
GOLDEN_KEYWORD_FRIENDLY: list[tuple[str, str]] = [
    ("能接受大波动，想博一把高收益", "P-TECH"),        # 文档写"波动极大…追求高收益"
    ("只求稳稳的、不想亏本金", "P-BOND"),              # 文档写"厌恶本金损失…稳稳收益"
    ("短期理财，收益比货币基金高一点", "P-SHORTBOND"),  # 文档写"收益略高于货币基金"
    ("随时申购赎回的活钱理财", "P-MMF"),               # 文档写"随时申购赎回…活钱"
    ("养老目标、长期退休储备", "P-PENSION"),           # 文档写"养老目标…退休储备"
    ("黄金避险对冲", "P-GOLD"),                        # 文档写"黄金…避险与对冲"
]

# B「更真实」：模拟真实用户口语，【刻意和文档措辞拉开距离】（跨字面）——
#   TF-IDF 的字面优势没了，才真正比"语义 vs 关键词"。
GOLDEN_REALISTIC: list[tuple[str, str]] = [
    ("想给爸妈存养老钱，能放十年八年的", "P-PENSION"),   # 不出现"养老目标/退休储备"原词
    ("这笔钱可能随时要用，别让我亏本", "P-MMF"),
    ("我年轻能扛，想搏一个翻倍的机会", "P-TECH"),        # 不说"高收益/波动"
    ("物价涨得凶，有没有保值抗跌的", "P-GOLD"),           # 不说"黄金/避险/通胀"
    ("胆子小，本金一分都不能少", "P-BOND"),
    ("放几个月就要用，比余额宝强点就行", "P-SHORTBOND"),  # 不说"短债/货币基金"
]

K = 3   # 评 top-K


# ========================= 你的两个 TODO：指标 =========================

def hit_at_k(ranked_codes: list[str], expected: str) -> int:
    """TODO#1：Hit@K —— 期望 code 是否出现在这次检索的 top-K 结果里。
    ranked_codes 是本条 query 检索到的 code 列表（已按相关度降序、长度≤K）。
    命中返回 1，否则返回 0。
    """
    return int(expected in ranked_codes)


def reciprocal_rank(ranked_codes: list[str], expected: str) -> float:
    """TODO#2：倒数排名 —— 期望 code 排第几，就返回 1/名次；没进 top-K 返回 0.0。
    名次从 1 开始：排第 1 → 1.0、第 2 → 0.5、第 3 → 0.333…、不在列表 → 0.0。
    提示：ranked_codes.index(expected) 得到 0-based 下标，名次 = 下标 + 1；
         用 in 先判在不在，避免 index 抛 ValueError。
    """
    if expected not in ranked_codes:
        return 0.0
    return 1.0 / (ranked_codes.index(expected) + 1)

# =====================================================================


def evaluate(name: str, encoder, golden: list[tuple[str, str]]) -> tuple[float, float]:
    """跑一个检索器过给定 golden set，返回 (Hit@K, MRR)。"""
    doc_vecs = np.asarray(encoder.encode_docs([d["text"] for d in CORPUS]))
    hits, rrs = [], []
    for query, expected in golden:
        qv = encoder.encode_query(query)
        top = retrieve_top_k(qv, doc_vecs, k=K)            # [(doc_idx, score), ...]
        ranked_codes = [CODES[i] for i, _ in top]           # 下标 → code
        hits.append(hit_at_k(ranked_codes, expected))
        rrs.append(reciprocal_rank(ranked_codes, expected))
    n = len(golden)
    hit, mrr = sum(hits) / n, sum(rrs) / n
    print(f"  【{name}】 Hit@{K} = {sum(hits)}/{n} = {hit:.2f}    MRR = {mrr:.3f}")
    return hit, mrr


def _run_suite(title: str, golden: list[tuple[str, str]], emb, tfidf) -> None:
    print(f"── {title}（{len(golden)} 条）──")
    evaluate("Embedding", emb, golden)
    evaluate("TF-IDF   ", tfidf, golden)
    print()


def main() -> None:
    emb, tfidf = EmbeddingEncoder(), TfidfEncoder()   # 复用同一 encoder 实例，只换题
    print(f"同一对检索器、同一指标，评 top-{K}，只换 golden set：\n")
    _run_suite("A 送分给 TF-IDF（query 字面≈文档）", GOLDEN_KEYWORD_FRIENDLY, emb, tfidf)
    _run_suite("B 更真实（query 跨字面、贴近口语）", GOLDEN_REALISTIC, emb, tfidf)
    print("→ 同一对检索器，换套题结论就可能翻转：eval 的结论完全取决于 golden set 的质量。"
          "\n  A 里 TF-IDF 靠字面重合拿高分（送分题）；B 里字面优势没了，才见真章。"
          "\n  教训：数字看着客观，却被有偏的 golden set 操纵——要先质疑题，再信分。")


if __name__ == "__main__":
    main()
