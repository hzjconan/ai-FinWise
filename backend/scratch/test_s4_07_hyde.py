"""s4_07 配套测试：不调 LLM、不加载真模型，只验证 hyde_search 的接线和 HyDE prompt 已填写。

    cd backend && .venv/bin/python -m pytest scratch/test_s4_07_hyde.py -v
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s4_07_hyde as m  # noqa: E402


class SpyEncoder:
    """记录调用了哪个编码方法；假想文档 "养老文档" 编码成和第 1 篇同向的向量。"""

    def __init__(self):
        self.calls: list[str] = []

    def encode_docs(self, texts):
        self.calls.append("docs")
        return np.array([[0.0, 1.0] if "养老" in t else [1.0, 0.0] for t in texts])

    def encode_query(self, text):
        self.calls.append("query")
        return np.array([0.0, 1.0] if "养老" in text else [1.0, 0.0])


DOC_VECS = np.array([[1.0, 0.0], [0.0, 1.0], [0.6, 0.8]])   # 0 货币 / 1 养老 / 2 偏养老


def test_hyde_search_ranks_by_similarity_to_hypothetical_doc():
    assert m.hyde_search("养老文档", SpyEncoder(), DOC_VECS, n=2) == [1, 2]


def test_hyde_search_encodes_hypothetical_doc_as_passage():
    # 假想文档是"文档"，要和库里文档用同一种编码（e5 的 passage: 前缀）→ 文档对文档
    spy = SpyEncoder()
    m.hyde_search("养老文档", spy, DOC_VECS, n=1)
    assert spy.calls == ["docs"]


def test_hyde_search_respects_n():
    assert len(m.hyde_search("养老文档", SpyEncoder(), DOC_VECS, n=1)) == 1


def test_hyde_prompt_is_filled_in():
    assert "TODO" not in m.HYDE_SYSTEM and len(m.HYDE_SYSTEM.strip()) > 20
