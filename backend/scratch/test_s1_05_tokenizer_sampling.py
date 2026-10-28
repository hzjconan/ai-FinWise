"""s1_05 配套测试：验证三个 TODO。tokenizer 相关的测试需要本地缓存的 e5，没有就跳过。

    cd backend && .venv/bin/python -m pytest scratch/test_s1_05_tokenizer_sampling.py -v
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s1_05_tokenizer_sampling as m  # noqa: E402


# ---------- TODO 8b ----------

def test_real_token_counts_ignores_padding():
    assert m.real_token_counts([[1, 1, 1, 0, 0], [1, 1, 1, 1, 1]]) == [3, 5]


def test_real_token_counts_matches_real_tokenizer():
    try:
        tok = m.load_tokenizer()
    except Exception:
        pytest.skip("本地没有缓存 multilingual-e5-small")
    texts = ["养老", "我想给爸妈存一笔养老钱"]
    batch = tok(texts, padding=True)
    expected = [len(tok(t)["input_ids"]) for t in texts]   # 单独编码、不补齐时的长度
    assert m.real_token_counts(batch["attention_mask"]) == expected


# ---------- TODO 8d-1 ----------

def test_softmax_t1_matches_class_numbers():
    np.testing.assert_allclose(m.softmax_with_temperature(m.LOGITS, 1.0), [0.609, 0.224, 0.136, 0.030], atol=1e-3)


def test_low_temperature_sharpens_high_flattens():
    low = m.softmax_with_temperature(m.LOGITS, 0.5)
    high = m.softmax_with_temperature(m.LOGITS, 2.0)
    np.testing.assert_allclose(low, [0.842, 0.114, 0.042, 0.002], atol=1e-3)
    np.testing.assert_allclose(high, [0.434, 0.263, 0.205, 0.097], atol=1e-3)
    for probs in (low, high):
        assert probs.sum() == pytest.approx(1.0)


def test_softmax_handles_large_logits():
    """可选的"减最大值"技巧：logits 很大时也不应该出现 nan。"""
    probs = m.softmax_with_temperature(np.array([1000.0, 999.0]), 1.0)
    if np.isnan(probs).any():
        pytest.xfail("没有做减最大值的数值稳定处理（可选）")
    np.testing.assert_allclose(probs, [0.731, 0.269], atol=1e-3)


# ---------- TODO 8d-2 ----------

def test_top_p_keeps_the_crossing_candidate_and_renormalizes():
    probs = m.softmax_with_temperature(m.LOGITS, 1.0)
    np.testing.assert_allclose(m.top_p_filter(probs, 0.8), [0.731, 0.269, 0.0, 0.0], atol=1e-3)


def test_top_p_keeps_original_order_for_unsorted_input():
    np.testing.assert_allclose(m.top_p_filter(np.array([0.1, 0.6, 0.3]), 0.7), [0.0, 0.667, 0.333], atol=1e-3)


def test_top_p_one_keeps_everything():
    probs = np.array([0.5, 0.3, 0.2])
    np.testing.assert_allclose(m.top_p_filter(probs, 1.0), probs)


def test_top_p_small_keeps_only_top():
    np.testing.assert_allclose(m.top_p_filter(np.array([0.5, 0.3, 0.2]), 0.1), [1.0, 0.0, 0.0])


def test_top_p_one_keeps_everything_despite_rounding():
    """p = 1.0 时，累加到最后可能是 0.9999999999999999 < 1.0（浮点舍入），也必须全部保留。"""
    probs = np.full(10, 0.1)                                  # 10 个 0.1，累加 = 0.9999999999999999
    assert np.cumsum(probs)[-1] < 1.0                         # 确认确实踩中了舍入
    assert np.count_nonzero(m.top_p_filter(probs, 1.0)) == 10
