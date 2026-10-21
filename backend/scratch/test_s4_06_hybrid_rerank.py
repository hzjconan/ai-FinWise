"""s4_06 配套测试：用讲义里手算过的数字校验 BM25 / RRF / 重排。

不加载任何真模型（重排用假模型）→ 快、确定。
    cd backend && .venv/bin/python -m pytest scratch/test_s4_06_hybrid_rerank.py -v
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s4_06_hybrid_rerank as m  # noqa: E402


# ---------- 7a：bm25_term_score（讲义第 1 步的手算例子）----------

def test_bm25_short_doc_matches_lesson_example_a():
    # A：20 字简介，avgdl=200，tf=1 → 讲义算出 ≈1.58
    assert m.bm25_term_score(tf=1, idf=1.0, doc_len=20, avgdl=200) == pytest.approx(1.583, abs=1e-3)


def test_bm25_long_doc_matches_lesson_example_b():
    # B：2000 字合同 → ≈0.21，长文档被打折
    assert m.bm25_term_score(tf=1, idf=1.0, doc_len=2000, avgdl=200) == pytest.approx(0.214, abs=1e-3)


def test_bm25_tf_saturates_at_k1_plus_1():
    # 长度 = 平均时，tf 很大也封顶 k1+1 = 2.2（TF 饱和）
    assert m.bm25_term_score(tf=10_000, idf=1.0, doc_len=200, avgdl=200) == pytest.approx(2.2, abs=1e-3)


def test_bm25_tf_zero_scores_zero():
    assert m.bm25_term_score(tf=0, idf=3.0, doc_len=50, avgdl=50) == 0


def test_bm25_idf_scales_linearly():
    one = m.bm25_term_score(tf=2, idf=1.0, doc_len=100, avgdl=100)
    assert m.bm25_term_score(tf=2, idf=2.5, doc_len=100, avgdl=100) == pytest.approx(2.5 * one)


def test_bm25_index_finds_exact_number():
    # 精确数字只出现在一篇里 → BM25 把它排第一，另一篇一个词都对不上 → 不召回
    idx = m.BM25Index(["养老目标2040基金", "货币基金活钱"])
    assert idx.search("2040那只", n=5) == [0]


# ---------- 7b：rrf_fuse（讲义第 4 步的 X / Y）----------

def test_rrf_prefers_consensus_over_single_first():
    # 9 两路都排第 3（Y），1 和 3 各只在一路排第 1（X）→ 9 排第一
    fused = m.rrf_fuse([[1, 2, 9], [3, 4, 9]])
    assert fused[0] == 9


def test_rrf_with_k0_prefers_single_first():
    # k=0 时名次差距放大 → 单路第 1 胜过两路第 3（讲义 k 的作用表）
    fused = m.rrf_fuse([[1, 2, 9], [3, 4, 9]], k=0)
    assert fused[0] in (1, 3)
    assert fused.index(9) > fused.index(1)


def test_rrf_returns_union_without_duplicates():
    fused = m.rrf_fuse([[0, 1], [1, 2]])
    assert sorted(fused) == [0, 1, 2]
    assert fused[0] == 1                      # 两路都有


def test_rrf_handles_empty_route():
    # BM25 一个都没召回时，结果就是另一路的顺序
    assert m.rrf_fuse([[5, 2, 7], []]) == [5, 2, 7]


# ---------- 7c：rerank（假模型：分数 = 文档里含 query 字符的个数）----------

class FakeCrossEncoder:
    def __init__(self):
        self.calls = 0

    def predict(self, pairs):
        self.calls += 1
        return np.array([sum(ch in doc for ch in q) for q, doc in pairs], dtype=float)


def test_rerank_orders_candidates_by_model_score():
    texts = ["货币基金", "养老基金长期", "养老"]
    out = m.rerank("养老长期", candidates=[0, 2, 1], texts=texts, model=FakeCrossEncoder())
    assert out == [1, 2, 0]                   # 4 个字全中 > 2 个字 > 0 个字


def test_rerank_only_scores_given_candidates_in_one_batch():
    texts = ["养老", "养老", "养老"]
    model = FakeCrossEncoder()
    out = m.rerank("养老", candidates=[2, 0], texts=texts, model=model)
    assert sorted(out) == [0, 2]              # 不会冒出候选外的文档 1
    assert model.calls == 1                   # 一次 predict 批量打分
