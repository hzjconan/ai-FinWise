"""L03 · 5c：不用任何 MCP 客户端库，亲手发 JSON-RPC 给 server，看清每一条原始消息

讲义：docs/ai-agent-learning/lessons/L03-mcp-and-skills.md（第 3、4、5 步）

做法：像 Host 那样把 finwise_mcp_server.py 当【子进程】启动（stdio 传输，第 4 步），
     往它的 stdin 写一行 JSON、从它的 stdout 读一行 JSON（第 3 步：一行一条消息）。

演示两种协议版本（第 3 步更正）：
  A. 2026-07-28 无状态版：没有 initialize；每个请求在 params._meta 里自带版本 / 客户端信息 / 能力
  B. 2025-11-25 握手版：先 initialize → notifications/initialized，再调工具（老客户端这样连）

运行：cd mcp-lab && .venv/bin/python raw_jsonrpc_demo.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "finwise_mcp_server.py")

META = {  # 2026-07-28 版：每个请求都带这三项（替代了握手）
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "raw-demo", "version": "0.1"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


def start_server() -> subprocess.Popen:
    # stderr 不接管 → server 的日志直接打到终端（你会看到 [finwise-mcp] 开头的行，那是 stderr，不是协议消息）
    return subprocess.Popen([sys.executable, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)


def send(proc: subprocess.Popen, msg: dict, expect_reply: bool = True) -> dict | None:
    line = json.dumps(msg, ensure_ascii=False)
    print(f"\n📤 C→S  {line}")
    proc.stdin.write(line + "\n")
    proc.stdin.flush()
    if not expect_reply:                       # Notification：没有 id，对方不回（第 3 步）
        print("   （通知，不等回复）")
        return None
    reply = json.loads(proc.stdout.readline())
    text = json.dumps(reply, ensure_ascii=False)
    print(f"📥 S→C  {text[:600]}{' …' if len(text) > 600 else ''}")
    assert reply["id"] == msg["id"], "响应的 id 必须和请求一致"   # 🔁 id 配对
    return reply


def demo_stateless() -> None:
    print("\n" + "=" * 20 + " A. 2026-07-28 无状态版 " + "=" * 20)
    proc = start_server()
    try:
        send(proc, {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": META}})
        send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"_meta": META}})
        send(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "search_products", "arguments": {"risk_level": "C3"}, "_meta": META}})
        send(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",            # 不合法的参数
                    "params": {"name": "search_products", "arguments": {"risk_level": "R3"}, "_meta": META}})
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


def demo_handshake() -> None:
    print("\n" + "=" * 20 + " B. 2025-11-25 握手版 " + "=" * 20)
    proc = start_server()
    try:
        send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                               "clientInfo": {"name": "raw-demo-old", "version": "0.1"}}})
        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False)
        send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "search_products", "arguments": {"risk_level": "C2"}}})
    finally:
        proc.stdin.close()
        proc.wait(timeout=10)


if __name__ == "__main__":
    demo_stateless()
    demo_handshake()
