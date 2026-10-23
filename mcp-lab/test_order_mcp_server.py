"""order_mcp_server 的测试：用官方 Client 在进程内连 server，通过 _meta 传幂等键。

    cd mcp-lab && .venv/bin/python -m pytest test_order_mcp_server.py -v
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import order_mcp_server as o  # noqa: E402

from mcp import Client  # noqa: E402

KEY = o.IDEMPOTENCY_META_KEY


@pytest.fixture(autouse=True)
def clean_orders():
    o.ORDERS.clear()
    yield
    o.ORDERS.clear()


def _run(coro):
    return asyncio.run(coro)


async def _order(client, args, key):
    r = await client.call_tool("place_order", args, meta={KEY: key} if key else None)
    return r.is_error, (r.content[0].text if r.content else "")


# ---------- 6b：record_order 本身 ----------

def test_first_call_creates_order():
    out = o.record_order("k1", "REC-001", 10000)
    assert out == {"order_id": "ORD-0001", "product_code": "REC-001", "amount": 10000, "duplicate": False}
    assert o.ORDERS["k1"]["duplicate"] is False


def test_retry_with_same_key_returns_same_order_without_creating():
    first = o.record_order("k1", "REC-001", 10000)
    again = o.record_order("k1", "REC-001", 10000)
    assert again["order_id"] == first["order_id"] and again["duplicate"] is True
    assert len(o.ORDERS) == 1                                     # 只有一笔订单
    assert o.ORDERS["k1"]["duplicate"] is False                   # 存着的原订单不被改动


def test_different_keys_are_different_orders():
    a = o.record_order("k1", "REC-001", 10000)
    b = o.record_order("k2", "REC-001", 10000)                   # 用户真的又买了一笔 → 新的业务操作、新的 key
    assert a["order_id"] != b["order_id"] and len(o.ORDERS) == 2


def test_same_key_different_params_is_rejected():
    o.record_order("k1", "REC-001", 10000)
    with pytest.raises(o.ToolError, match="幂等键"):
        o.record_order("k1", "REC-001", 20000)


# ---------- 通过 MCP 协议调用 ----------

def test_tool_schema_hides_ctx_and_declares_annotations():
    async def _go():
        async with Client(o.server) as c:
            return (await c.list_tools()).tools[0]
    tool = _run(_go())
    assert set(tool.input_schema["properties"]) == {"product_code", "amount"}   # ctx / 幂等键都不在参数里
    assert tool.annotations.destructive_hint is True and tool.annotations.read_only_hint is False


def test_host_retry_with_same_key_places_one_order():
    """模拟：Host 第一次调用"超时"（其实 server 已经下单了），用同一个 key 重试。"""
    async def _go():
        key = str(uuid.uuid4())                                   # Host 的代码按"这一笔业务操作"生成，不是模型
        async with Client(o.server) as c:
            first = await _order(c, {"product_code": "REC-001", "amount": 10000}, key)
            retry = await _order(c, {"product_code": "REC-001", "amount": 10000}, key)
        return first, retry
    (e1, t1), (e2, t2) = _run(_go())
    assert not e1 and not e2
    assert json.loads(t1)["order_id"] == json.loads(t2)["order_id"]
    assert json.loads(t2)["duplicate"] is True
    assert len(o.ORDERS) == 1


def test_missing_key_is_rejected():
    async def _go():
        async with Client(o.server) as c:
            return await _order(c, {"product_code": "REC-001", "amount": 10000}, None)
    is_error, text = _run(_go())
    assert is_error and "缺少幂等键" in text and o.ORDERS == {}


def test_amount_must_be_positive():
    async def _go():
        async with Client(o.server) as c:
            return await _order(c, {"product_code": "REC-001", "amount": 0}, "k1")
    is_error, _ = _run(_go())
    assert is_error and o.ORDERS == {}                            # schema 校验在函数之前就拦下（5c 控制反转）
