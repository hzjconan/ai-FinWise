"""s4_05 配套测试：验证 build_collection / search / search_by_risk / 持久化。

用「假 encoder」（固定向量、不加载真模型）→ 快、确定、只测向量库机制本身。
    cd backend && .venv/bin/python -m pytest scratch/test_s4_05_vector_db_chroma.py -v
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s4_05_vector_db_chroma as m  # noqa: E402
import chromadb  # noqa: E402


# ---- 假语料 + 假 encoder：每条文本映射到一个固定向量，语义关系由我们掌控 ----
PROD = [
    {"code": "A", "name": "货币", "risk_level": "C2", "category": "货币", "text": "活钱货币"},
    {"code": "B", "name": "养老", "risk_level": "C3", "category": "养老", "text": "养老退休"},
    {"code": "D", "name": "短债", "risk_level": "C3", "category": "债券", "text": "短债流动"},
    {"code": "C", "name": "股票", "risk_level": "C5", "category": "股票", "text": "高风险股票"},
]
VEC = {
    "活钱货币":   [1.0, 0.0, 0.0],
    "养老退休":   [0.0, 1.0, 0.0],
    "短债流动":   [0.0, 0.9, 0.1],   # 和「养老」同轴、略偏 → C3 过滤后排 B 之后
    "高风险股票": [0.0, 0.0, 1.0],
    "我要养老":   [0.0, 1.0, 0.0],   # query：和 B 完全同向 → 应 top1=B
    "适中风险":   [0.0, 1.0, 0.0],
}


class FakeEncoder(m.Encoder):
    def encode_docs(self, texts):
        return np.array([VEC[t] for t in texts], dtype=float)

    def encode_query(self, text):
        return np.array(VEC[text], dtype=float)


@pytest.fixture
def collection(tmp_path):
    client = chromadb.PersistentClient(path=str(tmp_path / "db"))
    return m.build_collection(client, FakeEncoder(), PROD, name="products")


def test_build_writes_all_rows(collection):
    assert collection.count() == len(PROD)


def test_search_returns_most_similar_first(collection):
    hits = m.search(collection, FakeEncoder(), "我要养老", k=1)
    assert hits[0]["code"] == "B"           # 与 query 同向，最近
    assert hits[0]["distance"] == pytest.approx(0.0, abs=1e-5)  # cosine 空间，同向 dist≈0


def test_metadata_filter_restricts_to_risk_level(collection):
    hits = m.search_by_risk(collection, FakeEncoder(), "适中风险", risk_level="C3", k=10)
    codes = {h["code"] for h in hits}
    assert codes == {"B", "D"}              # 只返回 C3 的，A(C2)/C(C5) 被过滤掉


def test_filter_then_rank_order(collection):
    # C3 子集里，B 与 query 同向应排在 D 前面
    hits = m.search_by_risk(collection, FakeEncoder(), "适中风险", risk_level="C3", k=10)
    assert [h["code"] for h in hits] == ["B", "D"]


def test_persistence_survives_reopen(tmp_path):
    path = str(tmp_path / "db2")
    client = chromadb.PersistentClient(path=path)
    m.build_collection(client, FakeEncoder(), PROD, name="products")

    # 另开一个 client 指向同一磁盘路径：数据还在，无需重新写入
    reopened = chromadb.PersistentClient(path=path).get_collection("products")
    assert reopened.count() == len(PROD)
