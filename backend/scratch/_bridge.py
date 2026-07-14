"""阶段 1/2 学习脚本共享的客户端工具。

所有 scratch 脚本都通过官方 anthropic SDK 调用，但把 base_url 指向本地
claude-cli-bridge（tools/claude-cli-bridge），后者用你本地的 `claude` CLI
（订阅）应答，无需 ANTHROPIC_API_KEY。

⚠️ bridge 的关键限制（背后是 Claude CLI，不是真实 API）：
- 每次调用**必须带至少一个 tool**，且模型只会以「工具 JSON」形式回答（不吐纯文本）。
- token 用量（usage）被写死成 0，**拿不到真实 token 数**。
- temperature 参数被忽略。
- 只支持 stream=true。

想练真实 token 计数 / temperature，需要真 ANTHROPIC_API_KEY——见 README「需真 key」小节。

前置：先启动 bridge（另开一个终端）：
    bash backend/scratch/run_bridge.sh
或手动：
    cd tools/claude-cli-bridge && .venv/bin/uvicorn claude_cli_bridge.main:app --port 8787
"""
from __future__ import annotations

import os
import sys

import httpx
from anthropic import APIStatusError, AsyncAnthropic

# 让 scratch 脚本能 import 仓库业务代码（app.*），阶段 2 会复用真实 prompt。
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# SDK 会自动在 base_url 后拼 /v1/messages；bridge 的路由正好挂在 /v1 前缀下。
BRIDGE_BASE_URL = os.environ.get("SCRATCH_BASE_URL", "http://localhost:8787")

# bridge 不校验 api_key，但 SDK 要求非空，给个占位值。
DUMMY_KEY = "bridge-no-key-needed"

# 与仓库业务侧一致的默认模型（bridge 里也是这个）。
MODEL = os.environ.get("SCRATCH_MODEL", "claude-haiku-4-5-20251001")


def make_client() -> AsyncAnthropic:
    """构造一个指向本地 bridge 的异步 Anthropic 客户端。

    注意：本机若设了 HTTP_PROXY/HTTPS_PROXY（这里是 127.0.0.1:8002），
    默认会把发往 localhost 的请求也劫持掉，导致 503。用 trust_env=False 的
    httpx 客户端彻底忽略代理环境变量，绕开这个坑。
    """
    http_client = httpx.AsyncClient(trust_env=False)
    return AsyncAnthropic(base_url=BRIDGE_BASE_URL, api_key=DUMMY_KEY, http_client=http_client)


def section(title: str) -> None:
    """打印一个醒目的分节标题，方便看输出。"""
    print(f"\n{'=' * 8} {title} {'=' * 8}")


class BridgeParseError(RuntimeError):
    """bridge 未能把模型输出解析成合法工具 JSON。

    这是 bridge 的已知脆弱点：它让 CLI 输出「纯 JSON」，当内容里带未转义引号等情况时会解析失败。
    真实 API 的原生 tool-use 不会有这个问题——所以这是学习环境的坑，不是 LLM 本身的坑。
    """


async def call_tool(
    client: AsyncAnthropic,
    *,
    system: str,
    messages: list[dict],
    tools: list[dict],
    max_tokens: int = 1024,
    retries: int = 1,
) -> list[dict]:
    """调用一次 LLM，返回 tool_use 块列表：[{"name": ..., "input": {...}}, ...]。

    失败（bridge 解析错误 / 瞬时错误）自动重试 `retries` 次——这正是仓库
    app/services/chat_service._call_llm_with_retry 的思路。最终仍失败则抛 BridgeParseError。
    """
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            async with client.messages.stream(
                model=MODEL, system=system, messages=messages, tools=tools, max_tokens=max_tokens
            ) as stream:
                final = await stream.get_final_message()
            return [
                {"name": b.name, "input": dict(b.input)}
                for b in final.content
                if getattr(b, "type", None) == "tool_use"
            ]
        except APIStatusError as e:
            last = e
    raise BridgeParseError(str(last))
