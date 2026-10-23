"""L03 · 5e-3：模拟线上 agent 的 Host（FinWise 后端风格）

讲义：docs/ai-agent-learning/lessons/L03-mcp-and-skills.md（第 5 步 5e-3）

线上 agent 的 Host 不是 Claude Code，而是你自己写的服务（讲义"5d 之后的追问"）。本脚本把它完整走一遍：

  ① 读配置 mcp_config.yaml                     ← "注册"在线上变成了配置（白名单 + 凭证引用）
  ② 从环境变量读 token，放进 HTTP 请求头       ← 机器对机器鉴权；凭证由代码注入，模型看不到
  ③ 创建 MCP client → tools/list（失败就重试）   ← Host 启动时的初始化；连接失败要自己处理
  ④ 把 MCP 工具定义转成 Claude API 的 tools 格式 ← TODO 5e-3b
  ⑤ agent loop：LLM → tool_use → MCP tools/call → tool_result → …… → final_answer   ← TODO 5e-3c
  ⑥ 审计：检查发给模型的所有内容里，从头到尾没有出现 token
  ⑦ 连不上 server 时降级：告诉用户"暂时查不了"，而不是整个请求报错

★ 按"生命周期"组织（用户 5e-3 时指出：配置、连接不该每个请求做一遍）：
   McpHost.startup()   服务启动时一次：①②③④ —— 读配置、读 token、建共享的 HTTP 客户端、取工具列表并缓存
   McpHost.answer()    每个请求一次：⑤⑥ —— 用共享 HTTP 客户端开一个轻量的 MCP 会话跑 agent loop；
                       不可用时按冷却时间尝试重连，否则 ⑦ 降级
   McpHost.shutdown()  服务关闭时一次：关闭共享 HTTP 客户端
   为什么"HTTP 客户端长期持有、MCP 会话按请求开"：协议是无状态的（第 3、4 步），每个请求自带全部信息，
   开一个 MCP 会话很便宜；而长期持有 MCP Client 时，server 一挂，它内部的任务组会被取消，
   取消信号会窜进正在处理的请求里（实测踩到的坑）。
   🔁 和 FastAPI 的 lifespan 同一思路：数据库引擎、HTTP 客户端这类资源启动时建、关闭时释放，每个请求只是借用。
   启动时连不上 → 服务照常起来，标记"不可用"，后续请求先降级、过了冷却时间再试（第 6 步熔断器的雏形）。

🔁 和 FinWise 的 chat_service（阶段三）是同一个结构，区别只在第 ⑤ 步执行工具的方式：
   chat_service 调本地的 _execute_tool；这里通过 MCP client 调远程 server。

前置：
  1. bridge 已启动（bash backend/scratch/run_bridge.sh）
  2. 另一个终端里，带 token 启动 server：
       cd mcp-lab && FINWISE_MCP_TOKEN=demo-secret-123 .venv/bin/python finwise_mcp_server.py --http
运行（同一个 token）：
  cd mcp-lab && FINWISE_MCP_TOKEN=demo-secret-123 .venv/bin/python online_host.py
测试：
  cd mcp-lab && .venv/bin/python -m pytest test_online_host.py -v
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

import httpx2
import yaml
from anthropic import AsyncAnthropic

from mcp import Client
from mcp.client.streamable_http import streamable_http_client

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[host] %(message)s")
log = logging.getLogger("online-host")

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "mcp_config.yaml")
BRIDGE_URL = os.environ.get("SCRATCH_BASE_URL", "http://localhost:8787")
MODEL = os.environ.get("SCRATCH_MODEL", "claude-haiku-4-5-20251001")
MAX_STEPS = 5

SYSTEM_PROMPT = (
    "你是 FinWise 的理财助手。需要产品数据时调用产品查询工具，只根据工具返回的数据回答，不要编造产品或数字；"
    "工具没有返回数据或调用失败时，如实告诉用户。回答完毕后，调用 final_answer 把给用户的回答交给系统。"
)

# 终态工具：模型调它 = 宣告结束（🔁 03 讲义"终态工具 vs 可执行工具"；bridge 也要求每次调用都带工具）
FINAL_TOOL = {
    "name": "final_answer",
    "description": "把给用户的最终回答交给系统。所有需要的查询都完成后再调用。",
    "input_schema": {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
}

DEGRADED_ANSWER = "抱歉，产品查询服务暂时不可用，我现在没法查到最新的产品信息，请稍后再试。"


class HostUnavailable(Exception):
    """MCP server 连不上（网络不通、未启动、鉴权失败……）。"""


# ---------------- ① 读配置 ----------------

def load_config(path: str = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def server_settings(cfg: dict, server_name: str) -> tuple[str, dict[str, str], dict]:
    """从配置里取出某个 server 的 URL、请求头、连接参数。
    ② token 在这里从环境变量读出、放进请求头——只有 Host 的代码经手，不会进入任何发给模型的内容。"""
    srv = cfg["mcp_servers"][server_name]
    headers: dict[str, str] = {}
    auth = srv.get("auth") or {}
    if auth.get("type") == "bearer":
        token = os.environ.get(auth["token_env"])
        if not token:
            raise HostUnavailable(f"缺少环境变量 {auth['token_env']}（server {server_name} 需要 Bearer token）")
        headers["Authorization"] = f"Bearer {token}"
    return srv["url"], headers, srv.get("connect") or {}


class StatusRecorder:
    """记下最近一次 HTTP 响应的状态码（挂在 HTTP 客户端的响应钩子上）。

    为什么需要它（第 6 步实测）：MCP SDK 把 401 / 429 / 503 等 HTTP 错误统一转成了同一个
    MCPError(-32603, "Server returned an error response")，状态码丢了——光看异常分不出该不该重试。
    所以在 HTTP 这一层自己记下状态码。"""

    def __init__(self) -> None:
        self.last: int | None = None

    async def __call__(self, response) -> None:
        self.last = response.status_code


def make_http_client(headers: dict[str, str], status: StatusRecorder | None = None) -> httpx2.AsyncClient:
    """创建一个长期共用的 HTTP 客户端：请求头（含 token）配在这里，之后每个 MCP 会话都用它。
    httpx 的 AsyncClient 内部自带连接池（复用 TCP 连接、keep-alive），所以共用一个客户端就能避免每次重新握手。"""
    hooks = {"response": [status]} if status else {}
    return httpx2.AsyncClient(headers=headers, trust_env=False,   # trust_env=False：本机有代理，访问 127.0.0.1 别走代理
                              event_hooks=hooks)


def mcp_client(url: str, http: httpx2.AsyncClient) -> Client:
    """用共享的 HTTP 客户端开一个 MCP 会话。SDK 不会关闭我们传进去的 http（实测源码：client_provided 时不 aclose）。"""
    return Client(streamable_http_client(url, http_client=http))


# ========================= TODO 5e-3b：工具定义格式转换 =========================

def mcp_tools_to_anthropic(mcp_tools) -> list[dict]:
    """TODO 5e-3b：把 MCP tools/list 返回的工具，转成 Claude API messages 接口要的 tools 参数格式。

    输入：mcp_tools —— client.list_tools().tools，每个元素有属性 .name / .description / .input_schema
    输出：[{"name": ..., "description": ..., "input_schema": ...}, ...]
          🔁 第 1 步：Anthropic 的工具格式叫 input_schema（OpenAI 叫 function.parameters）——
             这一步就是"Host 把 MCP 的通用格式，翻译成自己所用模型的格式"。MCP 和模型无关，正是靠 Host 做这层翻译。
    注意：description 可能是 None，转成空字符串 ""。
    """
    return [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema} for t in mcp_tools]

# =============================================================================


# ========================= TODO 5e-3c：MCP 结果 → tool_result =========================

def to_tool_result(tool_use_id: str, call_result) -> dict:
    """TODO 5e-3c：把一次 MCP tools/call 的返回，包装成回喂给模型的 tool_result 内容块。

    输入：
      tool_use_id —— 模型这次 tool_use 块的 id（🔁 04 讲义：tool_result 必须按 id 和 tool_use 配对）
      call_result —— client.call_tool(...) 的返回（CallToolResult），有：
                       .content  : 列表，元素是 TextContent，取 .text
                       .is_error : bool（🔁 5c：工具执行错误是 result + isError，不是 JSON-RPC error）
    输出：{"type": "tool_result", "tool_use_id": ..., "content": 所有 text 用换行拼起来的字符串, "is_error": ...}
    """
    return {"type": "tool_result", "tool_use_id": tool_use_id,
            "content": "\n".join(c.text for c in call_result.content),
            "is_error": call_result.is_error}

# =============================================================================


@dataclass
class AuditLog:
    """⑥ 记录发给模型的每一次请求（system + messages + tools），事后检查有没有泄露 token。"""
    payloads: list[str] = field(default_factory=list)

    def record(self, system: str, messages: list, tools: list) -> None:
        self.payloads.append(json.dumps({"system": system, "messages": messages, "tools": tools},
                                        ensure_ascii=False, default=str))

    def contains(self, secret: str) -> bool:
        return any(secret in p for p in self.payloads)


async def call_llm(llm: AsyncAnthropic, system: str, messages: list, tools: list) -> list[dict]:
    """调一次模型，返回内容块（转成普通 dict，方便直接放回 messages）。"""
    async with llm.messages.stream(model=MODEL, max_tokens=1024, system=system,
                                   messages=messages, tools=tools) as stream:
        final = await stream.get_final_message()
    blocks = []
    for b in final.content:
        if b.type == "tool_use":
            blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": dict(b.input)})
        elif b.type == "text":
            blocks.append({"type": "text", "text": b.text})
    return blocks


async def run_agent(question: str, llm_call, mcp, tools: list[dict], audit: AuditLog,
                    on_mcp_error=None) -> str:
    """⑤ agent loop（🔁 阶段三 s3_02 / chat_service 同一套骨架）。

    llm_call(system, messages, tools) -> 内容块列表；测试里会换成假的。
    mcp：已连接的 MCP Client（用它的 call_tool 执行可执行工具）。
    on_mcp_error：可选回调，MCP 调用抛异常（多半是 server 挂了）时通知 Host，让它标记"不可用"。
    """
    all_tools = tools + [FINAL_TOOL]
    messages: list[dict] = [{"role": "user", "content": question}]
    for step in range(1, MAX_STEPS + 1):
        audit.record(SYSTEM_PROMPT, messages, all_tools)
        blocks = await llm_call(SYSTEM_PROMPT, messages, all_tools)
        tool_uses = [b for b in blocks if b["type"] == "tool_use"]
        log.info("第 %d 轮：模型输出 %s", step, [(b["name"], b["input"]) for b in tool_uses] or "纯文本")

        final = next((b for b in tool_uses if b["name"] == FINAL_TOOL["name"]), None)
        if final:                                                    # 终态工具 → 结束
            return final["input"].get("answer", "")
        if not tool_uses:                                            # 没调工具也算结束（兜底）
            return "".join(b.get("text", "") for b in blocks)

        messages.append({"role": "assistant", "content": blocks})
        results = []
        for tu in tool_uses:                                         # 可执行工具 → 经 MCP 执行
            try:
                r = await mcp.call_tool(tu["name"], tu["input"])
                results.append(to_tool_result(tu["id"], r))
            except Exception as exc:                                 # 调用途中 server 挂了 → 当作工具错误喂回模型
                log.warning("MCP 调用失败：%s", _root_cause(exc))
                if on_mcp_error:
                    on_mcp_error(exc)
                results.append({"type": "tool_result", "tool_use_id": tu["id"],
                                "content": "产品查询服务暂时不可用", "is_error": True})
        messages.append({"role": "user", "content": results})
    return "抱歉，这个问题我没能在限定步数内处理完。"                  # 🔁 MAX_STEPS 兜底


# ========================= TODO 6a：哪些错误值得重试 =========================

def is_retryable(exc: BaseException, http_status: int | None) -> bool:
    """TODO 6a：这次失败是不是"暂时性错误"（值得退避后重试）。

    参数：
      exc         —— 捕获到的异常，可能被包在 ExceptionGroup 里（用 _root_cause_exc(exc) 取最里面那个）
      http_status —— 这次请求收到的 HTTP 状态码；连接都没建立起来时是 None
    规则（讲义第 6 步）：
      - 根异常是 httpx2.TimeoutException（超时）或 httpx2.NetworkError（连接被拒、网络断开）→ True
      - 否则看状态码：429（限流）或 >= 500（服务端错误）→ True
      - 其他（401 / 403 / 404、参数错误、状态码为 None 的未知错误）→ False
    提示：isinstance(x, (A, B)) 可以一次判断多个类型。
    """
    root = _root_cause_exc(exc)
    if isinstance(root, (httpx2.TimeoutException, httpx2.NetworkError)):
        return True
    if http_status is None:
        return False
    return http_status == 429 or http_status >= 500

# =============================================================================


async def list_tools_with_retry(url: str, http: httpx2.AsyncClient, connect: dict,
                                status: StatusRecorder | None = None) -> list:
    """连接 server、拿一次工具列表。只对暂时性错误按指数退避重试；永久性错误立刻放弃（第 6 步）。
    （🔁 5e-2：Claude Code 有 /mcp 让人手动重连；线上没人做这件事，Host 得自己重试。）"""
    attempts = int(connect.get("attempts", 3))
    delay = float(connect.get("backoff_seconds", 0.5))
    last = None
    for i in range(1, attempts + 1):
        if status:
            status.last = None                   # 每次尝试前清空，避免读到上一次的状态码
        try:
            async with mcp_client(url, http) as c:
                return (await c.list_tools()).tools
        except BaseException as exc:            # SDK 把底层错误包在 ExceptionGroup 里抛出，这里统一接住
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            last = exc
            code = status.last if status else None
            log.warning("连接 MCP server 失败（第 %d/%d 次，HTTP %s）：%s", i, attempts, code, _root_cause(exc))
            if not is_retryable(exc, code):
                raise HostUnavailable(f"不可重试的错误（HTTP {code}）：{_root_cause(exc)}") from None
            if i < attempts:
                await asyncio.sleep(delay)
                delay *= 2                       # 指数退避（🔁 阶段七 R1）
    raise HostUnavailable(f"连不上 {url}：{_root_cause(last)}")


def _root_cause_exc(exc: BaseException | None) -> BaseException | None:
    """把 ExceptionGroup 层层拆开，取最里面那个真正的异常。"""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _root_cause(exc: BaseException | None) -> str:
    """同上，转成"类型: 信息"字符串，方便看日志。"""
    exc = _root_cause_exc(exc)
    return f"{type(exc).__name__}: {exc}"


class McpHost:
    """线上 Host：按服务生命周期管理 MCP 连接（startup / answer / shutdown）。

    长期持有：共享的 HTTP 客户端（含 token 请求头，内部自带连接池）+ 缓存的工具列表。
    按请求：用它开一个 MCP 会话、跑 agent loop、关闭会话——会话的进入和退出都在同一个请求里，
           server 中途挂了也只影响这一次请求。
    （真实 Web 服务里，startup / shutdown 放进应用的 lifespan；这里不展开并发控制。）
    """

    def __init__(self, config: dict, agent: str = "wealth_advisor", llm_call=None,
                 retry_cooldown: float = 30.0):
        self.config = config
        self.server_name = config["agents"][agent]["mcp_servers"][0]   # 本 agent 被允许使用的 server（白名单）
        self.llm_call = llm_call
        self.retry_cooldown = retry_cooldown      # 不可用后，至少隔多久才再试一次（别每个请求都去撞）
        self.tools: list[dict] = []               # 缓存的工具定义（Claude API 格式）
        self.available = False
        self.unavailable_reason = "尚未启动"
        self._last_attempt = float("-inf")
        self._http: httpx2.AsyncClient | None = None
        self._status = StatusRecorder()            # 记录 HTTP 状态码，用于判断是否值得重试
        self._url = ""
        self._connect: dict = {}

    # ---------- 服务生命周期：启动 / 关闭 ----------

    async def startup(self) -> None:
        """服务启动时调用一次：读 token、建共享 HTTP 客户端、取工具列表。连不上也不抛异常——服务照常起来，先标记不可用。"""
        if self.llm_call is None:
            llm = AsyncAnthropic(base_url=BRIDGE_URL, api_key="bridge-no-key-needed")
            self.llm_call = lambda s, m, t: call_llm(llm, s, m, t)        # noqa: E731
        try:
            self._url, headers, self._connect = server_settings(self.config, self.server_name)  # ② 读 token
        except HostUnavailable as exc:
            self._mark_unavailable(str(exc))
            return
        self._http = make_http_client(headers, self._status)
        await self._try_connect()

    async def shutdown(self) -> None:
        """服务关闭时调用一次：关闭共享 HTTP 客户端。"""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ---------- 每个请求 ----------

    async def answer(self, question: str) -> tuple[str, AuditLog]:
        """处理一个用户请求：开一个 MCP 会话跑 agent loop。不可用时，过了冷却时间才尝试重连；连不上就降级（⑦）。"""
        audit = AuditLog()
        if not self.available and not await self._maybe_reconnect():
            log.info("降级：%s", self.unavailable_reason)
            return DEGRADED_ANSWER, audit
        try:
            async with mcp_client(self._url, self._http) as mcp:
                reply = await run_agent(question, self.llm_call, mcp, self.tools, audit,
                                        on_mcp_error=lambda exc: self._mark_unavailable(_root_cause(exc)))
            return reply, audit
        except BaseException as exc:              # 会话中途断开：SDK 可能抛 ExceptionGroup / 取消，这里统一接住
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            self._mark_unavailable(_root_cause(exc))
            log.info("本次请求降级：%s", self.unavailable_reason)
            return DEGRADED_ANSWER, audit

    async def refresh_tools(self) -> None:
        """重新拉一次工具列表。server 发 notifications/tools/list_changed 时、或按 TTL 定期调用。
        （本练习没有接收通知，只留这个入口。）"""
        await self._try_connect()

    # ---------- 内部 ----------

    async def _try_connect(self) -> bool:
        self._last_attempt = time.monotonic()
        try:
            mcp_tools = await list_tools_with_retry(self._url, self._http, self._connect, self._status)  # ③
        except HostUnavailable as exc:
            self._mark_unavailable(str(exc))
            return False
        self.tools = mcp_tools_to_anthropic(mcp_tools)                                  # ④ 缓存
        self.available, self.unavailable_reason = True, ""
        log.info("已连接 %s，缓存工具：%s", self.server_name, [t["name"] for t in self.tools])
        return True

    async def _maybe_reconnect(self) -> bool:
        if self._http is None:                                             # 连配置 / token 都没准备好
            return False
        if time.monotonic() - self._last_attempt < self.retry_cooldown:
            return False                                                   # 冷却中：直接降级，不去撞
        log.info("距上次尝试已超过 %.0fs，尝试重连 %s", self.retry_cooldown, self.server_name)
        return await self._try_connect()

    def _mark_unavailable(self, reason: str) -> None:
        if self.available or self.unavailable_reason != reason:
            log.warning("标记 %s 不可用：%s", self.server_name, reason)
        self.available, self.unavailable_reason = False, reason
        self._last_attempt = time.monotonic()


async def main() -> None:
    token = os.environ.get("FINWISE_MCP_TOKEN", "")
    host = McpHost(load_config())
    await host.startup()                                              # 服务启动：只做一次
    try:
        for q in ["我的风险等级是 C3，有哪些产品适合我？", "那 C5 呢？"]:   # 两个请求，复用同一个连接
            print(f"\n🙋 用户：{q}")
            reply, audit = await host.answer(q)
            print(f"🤖 回答：{reply}")
            if token:
                leaked = audit.contains(token)
                print(f"🔍 审计：本请求发给模型 {len(audit.payloads)} 次，其中{'❌ 出现了' if leaked else '✅ 没有出现'} token")
    finally:
        await host.shutdown()                                         # 服务关闭：只做一次


if __name__ == "__main__":
    asyncio.run(main())
