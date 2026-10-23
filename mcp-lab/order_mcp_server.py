"""L03 · 第 6 步 · 6b：模拟"下单"MCP server——用幂等键让非幂等操作可以安全重试

讲义：docs/ai-agent-learning/lessons/L03-mcp-and-skills.md（第 6 步"超时 ≠ 没执行 → 幂等"）

为什么单独一个 server，不加进 finwise_mcp_server.py：
  - 按业务领域拆 server（第 2 步）：理财顾问 agent 只连产品查询，根本拿不到下单工具（最小权限）
  - 下单是"有破坏性、会产生副作用"的操作，和只读查询的风险等级完全不同

⚠️ 只是练习：订单存在【内存】里（进程重启就没了），不写数据库、不碰 FinWise 的真实数据。

幂等键怎么传（关键设计）：
  - 【不】放在工具参数里——参数是模型填的，模型重试时可能给出另一个 key（讲义：幂等键不交给模型）
  - 放在 tools/call 请求的 _meta 里：由 Host 的代码按"业务操作"生成并附上，模型看不到也改不了
      client.call_tool("place_order", {"product_code": ..., "amount": ...},
                       meta={"finwise/idempotency_key": "<Host 生成的 UUID>"})
  - server 端通过 ctx.request_context.meta 读取

运行（stdio）：mcp-lab/.venv/bin/python mcp-lab/order_mcp_server.py
测试：cd mcp-lab && .venv/bin/python -m pytest test_order_mcp_server.py -v
"""
from __future__ import annotations

import logging
import sys
from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[order-mcp] %(message)s")
log = logging.getLogger("order-mcp")

IDEMPOTENCY_META_KEY = "finwise/idempotency_key"

server = MCPServer("finwise-order", instructions="FinWise 下单（模拟，订单只存在内存里）。")

# 内存里的"订单库"：幂等键 → 订单。真实系统里是数据库表，幂等键列上建唯一索引。
ORDERS: dict[str, dict] = {}


# ========================= TODO 6b：按幂等键记录订单 =========================

def record_order(key: str, product_code: str, amount: int) -> dict:
    """TODO 6b：按幂等键下单。同一个 key 无论来几次，只产生一笔订单。

    规则：
      1. key 没见过 → 新建订单：
            {"order_id": f"ORD-{len(ORDERS) + 1:04d}", "product_code": ..., "amount": ..., "duplicate": False}
         存进 ORDERS[key]（存的时候 duplicate 字段用 False），并返回它
      2. key 见过、且 product_code 和 amount 都和第一次一样 → 这是一次重试：
         不新建，返回之前那笔订单的副本，但 "duplicate" 改成 True（告诉调用方"这单之前已经下过了"）
      3. key 见过、但 product_code 或 amount 不一样 → 同一个 key 被用在了另一笔订单上，属于调用方的错误：
         raise ToolError("幂等键已被另一笔订单使用")   ← 用 ToolError：预料之中的错误，完整信息会给到调用方（5c）
    提示：返回副本可以用 {**old, "duplicate": True}（🔁 python-syntax-notes 解包操作符 **）
    """
    if key not in ORDERS:
        order = {"order_id": f"ORD-{len(ORDERS) + 1:04d}",
                 "product_code": product_code, "amount": amount, "duplicate": False}
        ORDERS[key] = order
        return order
    existing = ORDERS[key]
    if existing["product_code"] == product_code and existing["amount"] == amount:
        return {**existing, "duplicate": True}
    raise ToolError("幂等键已被另一笔订单使用")

# =============================================================================


@server.tool(
    description=(
        "为客户下单购买一个理财产品（模拟）。只有在客户明确确认要购买、产品和金额都已确定后才调用。"
        "返回订单号；duplicate=true 表示这笔订单之前已经下过（重试被识别），不会重复扣款。"
    ),
    annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True),
)
def place_order(
    product_code: Annotated[str, Field(description="要购买的产品代码，如 REC-001")],
    amount: Annotated[int, Field(gt=0, description="购买金额（元），必须大于 0")],
    ctx: Context,                    # SDK 自动注入，不会出现在工具的参数 schema 里，模型看不到
) -> dict:
    meta = ctx.request_context.meta or {}
    key = meta.get(IDEMPOTENCY_META_KEY)
    if not key:
        # 没有幂等键就拒绝：下单是非幂等操作，没有 key 就无法安全重试
        raise ToolError(f"缺少幂等键（请求 _meta 里要带 {IDEMPOTENCY_META_KEY}）")
    order = record_order(key, product_code, amount)
    log.info("place_order key=%s → %s%s", key, order["order_id"], "（重复请求，未重复下单）" if order["duplicate"] else "")
    return order


if __name__ == "__main__":
    server.run("stdio")
