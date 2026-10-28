"""s6_03 配套测试：令牌桶用传入的时间点，确定性；Semaphore / 超时用很短的 sleep。

    cd backend && .venv/bin/python -m pytest scratch/test_s6_03_concurrency_limits.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s6_03_concurrency_limits as m  # noqa: E402


# ---------- TODO 6a ----------

def test_bucket_allows_burst_up_to_capacity_then_rejects():
    b = m.TokenBucket(rate=2, capacity=3, now=0.0)
    assert [b.try_acquire(0.0) for _ in range(4)] == [True, True, True, False]


def test_bucket_refills_at_rate():
    b = m.TokenBucket(rate=2, capacity=3, now=0.0)
    for _ in range(3):
        b.try_acquire(0.0)
    assert b.try_acquire(0.5) is True       # 0.5 秒补 1 个
    assert b.try_acquire(0.5) is False      # 刚用掉，没有了


def test_bucket_never_exceeds_capacity():
    b = m.TokenBucket(rate=2, capacity=3, now=0.0)
    b.try_acquire(0.0)
    # 过了 100 秒，按速率能补 200 个，但桶最多 3 个
    assert [b.try_acquire(100.0) for _ in range(4)] == [True, True, True, False]


def test_rejected_request_does_not_consume_token():
    b = m.TokenBucket(rate=1, capacity=1, now=0.0)
    assert b.try_acquire(0.0) is True
    assert b.try_acquire(0.2) is False
    assert b.tokens == pytest.approx(0.2)   # 被拒绝时没扣成负数
    assert b.try_acquire(1.0) is True


# ---------- TODO 6b ----------

def test_run_all_respects_max_concurrency_and_keeps_order():
    tracker = {"running": 0, "peak": 0}
    calls = [m.make_fake_llm_call(f"r{i}", 0.05, tracker) for i in range(8)]
    results = asyncio.run(m.run_all(calls, max_concurrency=3))
    assert tracker["peak"] == 3
    assert results == [f"r{i} 完成" for i in range(8)]


def test_run_all_actually_runs_in_parallel():
    calls = [m.make_fake_llm_call(f"r{i}", 0.1) for i in range(4)]
    start = time.perf_counter()
    asyncio.run(m.run_all(calls, max_concurrency=4))
    assert time.perf_counter() - start < 0.3   # 串行要 0.4 秒


# ---------- TODO 6c ----------

def test_call_with_timeout_returns_result_when_fast():
    assert asyncio.run(m.call_with_timeout(m.make_fake_llm_call("快", 0.01), 0.5)) == "快 完成"


def test_call_with_timeout_returns_timeout_when_slow():
    start = time.perf_counter()
    assert asyncio.run(m.call_with_timeout(m.make_fake_llm_call("慢", 2.0), 0.05)) == "timeout"
    assert time.perf_counter() - start < 0.5   # 到点就放弃，不会等满 2 秒
