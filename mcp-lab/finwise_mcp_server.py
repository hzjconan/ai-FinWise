"""L03 · 第 5 步：FinWise 产品查询 MCP server（stdio）

讲义：docs/ai-agent-learning/lessons/L03-mcp-and-skills.md（第 5 步）

★ 关键设计：不重写查询逻辑，直接调 FinWise 后端的 `chat_service._execute_tool`。
  FinWise 的理财对话和 Claude Code 用的是【同一份】查询代码——这就是 MCP 要的"工具只实现一次"（第 1 步）。

传输：stdio（第 4 步）——Host 把本脚本当子进程启动，经 stdin / stdout 收发 JSON-RPC。
  ⚠️ stdout 是协议专用通道：本文件里【不许 print】，日志一律走 logging → stderr。

数据：默认只读 backend/finwise.db（开发库）；可用环境变量 FINWISE_DATABASE_URL 覆盖
     （FinWise 的配置带前缀 FINWISE_，见 backend/app/config.py 的 env_prefix）。

SDK：mcp 2.x（2.x 里 FastMCP 改名为 MCPServer：`from mcp.server.mcpserver import MCPServer`）。

运行（一般不用手动跑，由 Host 启动）：
    mcp-lab/.venv/bin/python mcp-lab/finwise_mcp_server.py
测试：
    cd mcp-lab && .venv/bin/python -m pytest test_finwise_mcp_server.py -v
"""
from __future__ import annotations

import argparse
import hmac
import logging
import os
import sys
from typing import Annotated, Literal

from pydantic import Field

# ---- 让本脚本能 import FinWise 后端代码（app.*），并默认连开发库 ----
BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
BACKEND_DIR = os.path.normpath(BACKEND_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
# config.py 默认是相对路径 sqlite:///./finwise.db，跟着"当前目录"走；Host 启动子进程时当前目录不一定是 backend，
# 所以这里给一个绝对路径的默认值（外部设置了就用外部的）。注意变量名带 FINWISE_ 前缀（config.py 的 env_prefix）。
# ⚠️ 踩过的坑：写成 DATABASE_URL 会被忽略，SQLite 会在当前目录【悄悄新建一个空库】，查询报 "no such table"。
os.environ.setdefault("FINWISE_DATABASE_URL", f"sqlite:///{os.path.join(BACKEND_DIR, 'finwise.db')}")

from mcp.server.mcpserver import MCPServer  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.services.chat_service import _execute_tool  # noqa: E402

# 日志写 stderr（不能写 stdout，见文件头）
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[finwise-mcp] %(message)s")
log = logging.getLogger("finwise-mcp")

# 变量名用 server，不用 mcp：避免和 SDK 的包名 mcp 混淆（官方示例常写 mcp = …）
server = MCPServer("finwise", instructions="FinWise 理财产品查询（只读）。")

# 数据库 session 工厂：测试里会替换成内存库，正式运行用开发库
SESSION_FACTORY = SessionLocal


# ========================= TODO 5a：工具的描述和参数 =========================
# 🔁 05「schema 即 prompt」：模型只能靠【工具名 + 描述 + 参数说明】决定"要不要调、什么时候调、参数怎么填"。
#
# ① description：写清这个工具【做什么】、【什么时候该用】、【什么时候不该用】、返回什么。
#    提示：参数 risk_level 是【客户的风险承受等级】C1~C5（不是产品的 R1~R5！）；
#         工具内部会按 MATCH_RULES 换算成匹配的产品等级，只返回在售（active）的产品。
# ② 参数：用 Annotated[类型, Field(description=...)] 给参数加说明——SDK 会把它写进 inputSchema。
#    类型已经用 Literal 限定成 C1~C5（🔁 L02 8a：用 schema 把取值限死）。
SEARCH_DESCRIPTION = """按客户的风险承受等级，查询 FinWise 当前在售的理财产品列表。

什么时候用：
  - 已经知道客户的风险承受等级（C1~C5），需要列出这个等级下可以推荐的具体产品时；
  - 向客户做推荐之前，想先确认有哪些产品可选时。
什么时候不该用：
  - 客户的风险等级还没评估出来 —— 先完成风险评估拿到等级，再来查；
  - 想了解某个已知产品的详情 —— 那是按产品代码查详情的事，不是"有哪些产品"。

注意 risk_level 是【客户】的风险承受等级 C1~C5（C1 最保守、C5 最激进），
不是产品自身的 R1~R5 风险等级。工具内部会按匹配规则换算成对应的产品等级（C1→R1 … C5→R5），
并且只返回在售（active）的产品；已下架和草稿状态的产品不会出现。

返回 {"risk_level": 传入的等级, "products": [...]}，每个产品含
product_code、name、type、expected_return，按预期收益率从高到低排列。
该等级下没有在售产品时 products 为空列表 —— 此时应如实告知客户暂无合适产品，不要编造。"""


@server.tool(description=SEARCH_DESCRIPTION)
def search_products(
    risk_level: Annotated[
        Literal["C1", "C2", "C3", "C4", "C5"],
        Field(description="客户的风险承受等级，C1 最保守、C5 最激进。注意是客户等级，不是产品的 R1~R5；工具会自动换算成匹配的产品等级。"),
    ],
) -> dict:
    # ========================= TODO 5b：工具函数体 =========================
    # 1. 用 SESSION_FACTORY() 打开一个数据库 session
    # 2. 调 _execute_tool(db, "search_products", {"risk_level": risk_level})，把结果返回
    # 3. 无论成功失败都要关闭 session（try / finally）
    # 4. 用 log.info(...) 记一条日志（会写到 stderr）——想想为什么不能用 print
    db = SESSION_FACTORY()
    try:
        result = _execute_tool(db, "search_products", {"risk_level": risk_level})
        log.info("search_products risk_level=%s -> %d 个在售产品",
                 risk_level, len(result.get("products", [])))
        return result
    finally:
        db.close()
    # =====================================================================


# =============================================================================


# ========================= TODO 5e-3a：机器对机器鉴权（Bearer token）=========================
# 5e-3 的线上场景：HTTP 模式下，如果设置了环境变量 FINWISE_MCP_TOKEN，就要求每个请求带上
#     Authorization: Bearer <token>
# 不带或带错 → 直接返回 401，请求根本到不了 MCP 层（工具函数、参数校验都不会执行）。
# 没设置这个环境变量时不校验（保持 5e-1 / 5e-2 的行为，方便本地调试）。
#
# 你来写判断逻辑 is_authorized；ASGI 包装（with_bearer_auth）和启动（run_http）我写好了。

def is_authorized(auth_header: str | None, expected_token: str) -> bool:
    """TODO 5e-3a：请求头 Authorization 的值是否正好是 "Bearer <expected_token>"。

    参数：
      auth_header    —— 请求里 Authorization 头的原始值；没带这个头时是 None
      expected_token —— 服务端配置的正确 token（来自环境变量）
    要求：
      - None、空字符串、不是 "Bearer " 开头 → False
      - 比较 token 时用 hmac.compare_digest(a, b)，不要用 ==   ← 想想为什么（提示：比较所用的时间）
    """
    if not auth_header or not auth_header.startswith("Bearer "):
        return False
    return hmac.compare_digest(auth_header[len("Bearer "):], expected_token)


def with_bearer_auth(app, expected_token: str):
    """把 MCP 的 ASGI 应用包一层：HTTP 请求先过 token 校验，通过才交给 MCP 处理。
    （ASGI 是 Python Web 服务器和应用之间的标准接口；FastAPI / Starlette 都是 ASGI 应用。
     这一层相当于 FastAPI 里的一个中间件。）"""
    async def wrapped(scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])                      # ASGI 里请求头是 [(bytes, bytes), ...]
            auth = headers.get(b"authorization", b"").decode() or None
            if not is_authorized(auth, expected_token):
                log.warning("拒绝未授权请求：%s %s", scope.get("method"), scope.get("path"))
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": b'{"error": "unauthorized"}'})
                return
        await app(scope, receive, send)                           # 非 http（如启动时的 lifespan）直接放行
    return wrapped


def run_http(port: int) -> None:
    """以 Streamable HTTP 方式运行；设置了 FINWISE_MCP_TOKEN 时加上 Bearer 鉴权。"""
    import uvicorn

    app = server.streamable_http_app(stateless_http=True)        # 和 server.run("streamable-http", …) 同一个应用
    token = os.environ.get("FINWISE_MCP_TOKEN")
    if token:
        app = with_bearer_auth(app, token)
        log.info("已启用 Bearer 鉴权（token 来自环境变量 FINWISE_MCP_TOKEN，日志里不打印它）")
    else:
        log.info("未设置 FINWISE_MCP_TOKEN：不鉴权（仅限本地调试）")
    log.info("以 Streamable HTTP 方式启动，监听 127.0.0.1:%d/mcp（无状态）", port)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")

# =============================================================================


# ========================= TODO 5e-1：支持 HTTP 方式运行 =========================
# 现在只能以 stdio 方式运行（Host 把它当子进程启动，第 4 步）。改成支持两种启动方式：
#
#   python finwise_mcp_server.py                  → stdio（保持不变，Claude Code 现有的 stdio 注册还要用）
#   python finwise_mcp_server.py --http           → Streamable HTTP，监听 127.0.0.1:8765，路径 /mcp
#   python finwise_mcp_server.py --http --port N  → 同上，端口换成 N（测试会用一个随机空闲端口）
#
# SDK 2.x 的写法（已查过源码）：
#   server.run("streamable-http", host="127.0.0.1", port=8765, stateless_http=True)
#   - 路径默认就是 /mcp
#   - stateless_http=True：不发 Mcp-Session-Id（第 4 步：多机部署要无状态）
#   - 默认端口是 8000，但 FinWise 后端开发服务器也常用 8000，所以换成 8765，避免冲突
# 提示：解析命令行参数可以用标准库 argparse（--http 用 action="store_true"，--port 用 type=int）。

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FinWise 产品查询 MCP server")
    parser.add_argument("--http", action="store_true",
                        help="以 Streamable HTTP 方式运行（默认是 stdio，由 Host 当子进程启动）")
    parser.add_argument("--port", type=int, default=8765,
                        help="HTTP 模式监听的端口（默认 8765，避开开发服务器常用的 8000）")
    args = parser.parse_args()

    if args.http:
        run_http(args.port)   # 5e-3 改：原来是 server.run("streamable-http", …)，现在多了可选的 token 校验
    else:
        server.run("stdio")

# =============================================================================
