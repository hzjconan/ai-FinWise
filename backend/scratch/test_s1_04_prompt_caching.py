"""s1_04 配套测试：不调 API，只验证两种写法拼出的请求"从哪里开始不一样"。

    cd backend && .venv/bin/python -m pytest scratch/test_s1_04_prompt_caching.py -v
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s1_04_prompt_caching as m  # noqa: E402

T1 = datetime(2026, 10, 26, 14, 32, 5)
T2 = datetime(2026, 10, 26, 14, 33, 40)
HISTORY = [
    {"role": "user", "content": "我想给爸妈存一笔养老钱"},
    {"role": "assistant", "content": "请问预计存多久？"},
]
Q = "三年左右"


def test_before_breaks_at_first_system_block():
    """优化前：时间在 system 开头，同一客户隔一分钟再问，system 第一块就不同 → 固定规则缓存不上。"""
    a = m.build_request_before("u123", T1, HISTORY, Q)
    b = m.build_request_before("u123", T2, HISTORY, Q)
    assert m.first_difference(a, b) == "system[0]"


def test_after_same_customer_reuses_everything_but_new_turn():
    """优化后：同一客户不同时间，只有本轮用户消息不同，tools、两段 system、历史都能复用。"""
    a = m.build_request_after("u123", "C2", T1, HISTORY, Q)
    b = m.build_request_after("u123", "C2", T2, HISTORY, Q)
    assert m.first_difference(a, b) == f"messages[{len(HISTORY)}]"


def test_after_different_customers_share_tools_and_rules():
    """优化后：不同客户从客户画像那块开始不同，tools + 固定规则跨客户共享。"""
    a = m.build_request_after("u123", "C2", T1, HISTORY, Q)
    b = m.build_request_after("u456", "C4", T1, HISTORY, Q)
    assert m.first_difference(a, b) == "system[1]"
    assert a["system"][0]["text"] == m.SHARED_RULES
    assert "cache_control" in a["system"][0]


def test_after_keeps_volatile_values_out_of_shared_block():
    req = m.build_request_after("u123", "C2", T1, HISTORY, Q)
    assert "14:32" not in req["system"][0]["text"] + req["system"][1]["text"]
    assert "u123" not in req["system"][0]["text"]
    assert "14:32" in req["messages"][-1]["content"]


def test_after_tools_sorted_and_breakpoints_within_limit():
    req = m.build_request_after("u123", "C2", T1, HISTORY, Q)
    names = [t["name"] for t in req["tools"]]
    assert names == sorted(names)
    assert m.count_breakpoints(req) == 3   # 2 个显式 + 1 个顶层自动，上限 4


def test_render_order_is_tools_system_messages():
    labels = [label for label, _ in m.render_blocks(m.build_request_after("u123", "C2", T1, HISTORY, Q))]
    assert labels[0].startswith("tools") and labels[-1].startswith("messages")
    first_system = next(i for i, l in enumerate(labels) if l.startswith("system"))
    first_message = next(i for i, l in enumerate(labels) if l.startswith("messages"))
    assert max(i for i, l in enumerate(labels) if l.startswith("tools")) < first_system < first_message


def test_identical_requests_have_no_difference():
    a = m.build_request_after("u123", "C2", T1, HISTORY, Q)
    assert m.first_difference(a, a) is None
