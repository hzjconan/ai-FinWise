"""L04 · 第 6 步配套：prompt caching 优化前 vs 优化后

讲义：docs/ai-agent-learning/lessons/L04-llm-inference-internals.md（第 6 步 6.4 + 课堂问答）

场景（就是课上那道题）：
  优化前：system 第一行就是"当前时间 + 客户 ID"，后面才是 3000 token 的固定规则
         → 时间每次都变 → 前缀每次都不同 → cache_read_input_tokens 永远是 0
  优化后："不变在前、常变在后"，分三层：
         [tools][固定规则] ← 断点 1：所有客户共享
         [客户画像]        ← 断点 2：同一客户的会话内共享
         [对话历史][本轮问题 + 当前时间] ← 顶层自动缓存，随对话往后挪

本脚本默认【不调用 API】：只把两种写法拼出来的请求按 Claude 的拼接顺序（tools → system → messages）
展开，找出两个请求"从哪一块开始不一样"——那一块之前的内容就是能复用的前缀。

可选 --live：需要真实 ANTHROPIC_API_KEY（bridge 的 usage 写死为 0，看不到缓存效果），
同一客户、间隔几秒发两次请求，打印 usage 里的缓存字段。会产生少量真实费用。

运行：
    cd backend && .venv/bin/python scratch/s1_04_prompt_caching.py
    cd backend && ANTHROPIC_API_KEY=sk-... .venv/bin/python scratch/s1_04_prompt_caching.py --live
测试：
    cd backend && .venv/bin/python -m pytest scratch/test_s1_04_prompt_caching.py -v
"""
from __future__ import annotations

import json
import sys
from datetime import datetime

MODEL = "claude-opus-5-5"
CACHE = {"type": "ephemeral"}   # 默认 5 分钟 TTL；要 1 小时写 {"type": "ephemeral", "ttl": "1h"}

# 所有客户都一样的大段固定内容（真实场景约 3000 token；这里用 40 条编号规则凑够长度，
# 因为前缀太短不会被缓存，而且不报错——最新模型的最低长度是 512 token）
SHARED_RULES = "你是 FinWise 理财顾问。请遵守以下产品知识与合规规则：\n" + "\n".join(
    f"{i}. 规则 {i}：向客户推荐产品前，必须先确认其风险等级与产品风险等级匹配，"
    f"不得承诺收益，不得诱导客户购买超出其风险承受能力的产品。"
    for i in range(1, 41)
)

TOOLS = [
    {
        "name": "search_products",
        "description": "按关键词和风险等级查询 FinWise 理财产品（只读）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string"},
                "risk_level": {"type": "string", "enum": ["R1", "R2", "R3", "R4", "R5"]},
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_customer_holdings",
        "description": "查询当前客户的持仓（客户身份由服务端认证得出，模型不填）。",
        "input_schema": {"type": "object", "properties": {}},
    },
]


# ============================== 优化前 ==============================

def build_request_before(customer_id: str, now: datetime, history: list[dict], question: str) -> dict:
    """❌ 时间和客户 ID 拼在 system 最前面 → 后面的固定规则永远缓存不上。"""
    system_text = (
        f"当前时间：{now:%Y-%m-%d %H:%M:%S}。客户 ID：{customer_id}。\n"   # ← 每个请求都变，且在最前面
        + SHARED_RULES
    )
    return {
        "model": MODEL,
        "max_tokens": 1024,
        "tools": TOOLS,
        "system": [{"type": "text", "text": system_text, "cache_control": CACHE}],  # 断点加了也没用
        "messages": [*history, {"role": "user", "content": question}],
    }


# ============================== 优化后 ==============================

def build_request_after(customer_id: str, profile: str, now: datetime,
                        history: list[dict], question: str) -> dict:
    """✅ 不变在前、常变在后，用两个显式断点 + 顶层自动缓存分三层。"""
    return {
        "model": MODEL,
        "max_tokens": 1024,
        # 工具排在整个 prompt 的最前面：顺序要固定（按名字排序），且不要按用户动态增减工具
        "tools": sorted(TOOLS, key=lambda t: t["name"]),
        "system": [
            # 第 1 层：所有客户共享。断点放在这里 → 缓存的是 tools + 这段固定规则
            {"type": "text", "text": SHARED_RULES, "cache_control": CACHE},
            # 第 2 层：同一客户的会话内共享。客户换了，只有从这里往后的部分需要重写
            {"type": "text", "text": f"客户 ID：{customer_id}\n客户画像：{profile}", "cache_control": CACHE},
        ],
        # 第 3 层：对话历史只追加不修改；时间放进本轮用户消息（变成历史后不再改动，不影响后续缓存）
        "messages": [
            *history,
            {"role": "user", "content": f"（当前时间：{now:%Y-%m-%d %H:%M}）\n{question}"},
        ],
        # 顶层自动缓存：断点自动放在最后一个块，并随对话增长往后挪（2 个显式 + 1 个自动 = 3，上限 4）
        "cache_control": CACHE,
    }


# ====================== 不调 API：看两个请求从哪里开始不一样 ======================

def render_blocks(request: dict) -> list[tuple[str, str]]:
    """按 Claude 的拼接顺序 tools → system → messages 展开成 (位置标签, 内容) 列表。

    缓存是按字节匹配前缀的：两个请求从第一块不同的地方开始，后面全部不能复用。
    json.dumps 用 sort_keys=True：字典键顺序不固定也会让字节不同（文档里的"隐形失效"之一）。
    """
    blocks = [(f"tools[{i}]", json.dumps(t, sort_keys=True, ensure_ascii=False))
              for i, t in enumerate(request.get("tools", []))]
    blocks += [(f"system[{i}]", b["text"]) for i, b in enumerate(request["system"])]
    for i, m in enumerate(request["messages"]):
        content = m["content"] if isinstance(m["content"], str) else json.dumps(m["content"], ensure_ascii=False)
        blocks.append((f"messages[{i}]", f"{m['role']}: {content}"))
    return blocks


def first_difference(req_a: dict, req_b: dict) -> str | None:
    """返回两个请求第一块不同内容的位置标签；完全相同返回 None。"""
    for (label, a), (_, b) in zip(render_blocks(req_a), render_blocks(req_b)):
        if a != b:
            return label
    return None


def count_breakpoints(request: dict) -> int:
    """显式断点 + 顶层自动断点的总数（每个请求最多 4 个）。"""
    n = sum(1 for b in request["system"] if "cache_control" in b)
    n += sum(1 for m in request["messages"] if isinstance(m["content"], list)
             for b in m["content"] if "cache_control" in b)
    return n + (1 if "cache_control" in request else 0)


def demo() -> None:
    t1 = datetime(2026, 10, 26, 14, 32, 5)
    t2 = datetime(2026, 10, 26, 14, 33, 40)       # 同一客户 1 分半后再问
    history = [
        {"role": "user", "content": "我想给爸妈存一笔养老钱"},
        {"role": "assistant", "content": "好的，请问预计存多久、能接受多大的波动？"},
    ]
    q = "三年左右，不能亏本金"

    cases = [
        ("优化前 · 同一客户、不同时间", build_request_before("u123", t1, history, q),
         build_request_before("u123", t2, history, q)),
        ("优化后 · 同一客户、不同时间", build_request_after("u123", "C2 稳健型", t1, history, q),
         build_request_after("u123", "C2 稳健型", t2, history, q)),
        ("优化后 · 不同客户", build_request_after("u123", "C2 稳健型", t1, history, q),
         build_request_after("u456", "C4 积极型", t1, history, q)),
    ]
    for title, a, b in cases:
        blocks = [label for label, _ in render_blocks(a)]
        diff = first_difference(a, b)
        reusable = blocks[: blocks.index(diff)] if diff else blocks
        print(f"\n== {title} ==")
        print(f"  拼接顺序：{' → '.join(blocks)}")
        print(f"  第一处不同：{diff}")
        # 注意：字节相同 ≠ 一定命中。只有落在【上一个请求写过断点的位置】才能读到缓存
        print(f"  字节相同的前缀：{' + '.join(reusable) if reusable else '（无）'}")


# ============================== 可选：真实 API ==============================

def live() -> None:
    import os
    import time

    import anthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("--live 需要真实 ANTHROPIC_API_KEY（bridge 的 usage 写死为 0，看不到缓存效果）")
    client = anthropic.Anthropic()
    for i in range(2):
        req = build_request_after("u123", "C2 稳健型", datetime.now(), [], "三年左右，不能亏本金，有什么建议？")
        resp = client.messages.create(**req)
        u = resp.usage
        # 总输入 = input_tokens（未缓存部分）+ cache_creation（本次写入）+ cache_read（本次读到）
        print(f"第 {i + 1} 次：input={u.input_tokens}  cache_creation={u.cache_creation_input_tokens}  "
              f"cache_read={u.cache_read_input_tokens}")
        time.sleep(2)   # 缓存要等第一个请求开始返回后才能被读到，所以串行发，不要并发


if __name__ == "__main__":
    live() if "--live" in sys.argv else demo()
