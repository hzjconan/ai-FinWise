"""finwise_mcp_server 的测试：不经过 LLM，用官方 Client 在进程内连 server，走真实的 MCP 协议。

数据库用内存 SQLite（和 backend/tests/conftest.py 同样做法），不碰开发库。
    cd mcp-lab && .venv/bin/python -m pytest test_finwise_mcp_server.py -v
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finwise_mcp_server as m  # noqa: E402

from mcp import Client  # noqa: E402

from app import models  # noqa: E402,F401  —— 注册全部表，create_all 才建得出外键引用的表
from app.database import Base  # noqa: E402
from app.models.product import Product  # noqa: E402

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=engine)


class _TrackingSession:
    """包一层，记录 session 有没有被关闭。"""

    def __init__(self):
        self.closed = 0

    def __call__(self):
        db = TestingSession()
        original_close = db.close

        def close():
            self.closed += 1
            original_close()

        db.close = close
        return db


@pytest.fixture(autouse=True)
def db(monkeypatch):
    Base.metadata.create_all(bind=engine)
    s = TestingSession()
    s.add_all([
        Product(product_code="P-R3", name="平衡混合", type="混合", status="active",
                risk_level="R3", expected_return=Decimal("4.5")),
        Product(product_code="P-R3-DRAFT", name="草稿产品", type="混合", status="draft",
                risk_level="R3", expected_return=Decimal("9.9")),
        Product(product_code="P-R5", name="科技股票", type="股票", status="active",
                risk_level="R5", expected_return=Decimal("12.0")),
    ])
    s.commit()
    s.close()
    tracker = _TrackingSession()
    monkeypatch.setattr(m, "SESSION_FACTORY", tracker)
    yield tracker
    Base.metadata.drop_all(bind=engine)


def _run(coro):
    return asyncio.run(coro)


async def _list_tools():
    async with Client(m.server) as c:
        return (await c.list_tools()).tools


async def _call(args):
    async with Client(m.server) as c:
        return await c.call_tool("search_products", args)


# ---------- 5a：tools/list 里模型能看到什么 ----------

def test_tool_is_listed():
    assert [t.name for t in _run(_list_tools())] == ["search_products"]


def test_tool_description_filled_in():
    desc = _run(_list_tools())[0].description or ""
    assert "TODO" not in desc and len(desc) > 30


def test_param_has_description_and_enum():
    prop = _run(_list_tools())[0].input_schema["properties"]["risk_level"]
    assert "TODO" not in prop.get("description", "TODO") and len(prop["description"]) > 5
    assert set(prop["enum"]) == {"C1", "C2", "C3", "C4", "C5"}


# ---------- 5b：tools/call ----------

def test_call_returns_matching_active_products():
    r = _run(_call({"risk_level": "C3"}))
    assert r.is_error is False
    # 返回类型是普通 dict → SDK 把它序列化成 JSON 文本放进 content（这也正是模型看到的 tool_result）
    payload = json.loads(r.content[0].text)
    codes = [p["product_code"] for p in payload["products"]]
    assert codes == ["P-R3"]                 # C3 → R3；草稿产品被过滤掉


def test_call_closes_db_session(db):
    _run(_call({"risk_level": "C5"}))
    assert db.closed == 1


def test_invalid_risk_level_rejected_by_schema():
    # "R3" 不在 enum 里 → 协议层就校验失败，返回错误结果（不会进到函数体）
    r = _run(_call({"risk_level": "R3"}))
    assert r.is_error is True


def test_server_never_prints_to_stdout(capsys):
    _run(_call({"risk_level": "C3"}))
    assert capsys.readouterr().out == ""     # stdio 模式下 stdout 是协议通道


# ---------- 5e-1：HTTP 方式运行（真的启动一个子进程，通过网络连接）----------

import socket  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

SERVER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "finwise_mcp_server.py")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


def test_http_mode_serves_tools_over_network():
    port = _free_port()
    proc = subprocess.Popen([sys.executable, SERVER_FILE, "--http", "--port", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert _wait_port(port), "HTTP 模式没有在指定端口上监听"

        async def _list():
            async with Client(f"http://127.0.0.1:{port}/mcp") as c:   # 传 URL → 走 Streamable HTTP
                return [t.name for t in (await c.list_tools()).tools]

        assert _run(_list()) == ["search_products"]
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_default_mode_is_still_stdio():
    # 不带参数时仍是 stdio：给 stdin 一个空输入，进程应读到"输入结束"后正常退出，而不是去监听端口
    proc = subprocess.run([sys.executable, SERVER_FILE], input=b"", capture_output=True, timeout=20)
    assert proc.returncode == 0


# ---------- 5e-3a：is_authorized + HTTP 模式下的 401 ----------

@pytest.mark.parametrize("header, ok", [
    (None, False),                       # 没带 Authorization 头
    ("", False),
    ("Basic demo-secret-123", False),    # 不是 Bearer
    ("Bearer wrong-token", False),
    ("Bearer demo-secret-123x", False),  # 多一个字符也不行
    ("Bearer demo-secret-123", True),
])
def test_is_authorized(header, ok):
    assert m.is_authorized(header, "demo-secret-123") is ok


def test_is_authorized_uses_constant_time_compare(monkeypatch):
    called = {}
    import hmac as _hmac
    real = _hmac.compare_digest

    def spy(a, b):
        called["yes"] = True
        return real(a, b)

    monkeypatch.setattr(m.hmac, "compare_digest", spy)
    m.is_authorized("Bearer demo-secret-123", "demo-secret-123")
    assert called.get("yes"), "比较 token 要用 hmac.compare_digest"


def _post_status(port: int, headers: dict) -> int:
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{port}/mcp", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 不走代理
    try:
        return opener.open(req, timeout=5).status
    except urllib.error.HTTPError as e:
        return e.code


def test_http_mode_with_token_rejects_unauthorized():
    port = _free_port()
    env = {**os.environ, "FINWISE_MCP_TOKEN": "demo-secret-123"}
    proc = subprocess.Popen([sys.executable, SERVER_FILE, "--http", "--port", str(port)],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert _wait_port(port)
        assert _post_status(port, {}) == 401                                         # 不带 token
        assert _post_status(port, {"Authorization": "Bearer wrong"}) == 401          # token 错
        assert _post_status(port, {"Authorization": "Bearer demo-secret-123"}) != 401  # token 对 → 进到 MCP 层
    finally:
        proc.terminate()
        proc.wait(timeout=10)
