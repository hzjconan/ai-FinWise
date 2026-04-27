#!/usr/bin/env bash
# 端到端冒烟：bridge ↔ 真实 Claude CLI ↔ Anthropic SDK
#
# 跑时机：bridge 改动后 / PR merge 前手动验证。CI 不跑（需登录态 + 真实 CLI）。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRIDGE_DIR="$REPO_ROOT/tools/claude-cli-bridge"
PORT=8787

cleanup() {
    [ -n "${BRIDGE_PID:-}" ] && kill "$BRIDGE_PID" 2>/dev/null || true
}
trap cleanup EXIT

# 1) 前置检查
command -v claude >/dev/null || { echo "ERROR: 未安装 claude CLI" >&2; exit 1; }
if lsof -ti :"$PORT" >/dev/null 2>&1; then
    echo "ERROR: 端口 $PORT 被占用" >&2
    exit 1
fi
[ -d "$BRIDGE_DIR/.venv" ] || {
    echo "ERROR: bridge venv 不存在，先 cd $BRIDGE_DIR && python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
    exit 1
}

# 2) 启动 bridge
echo "[smoke] starting bridge on :$PORT ..."
cd "$BRIDGE_DIR"
.venv/bin/uvicorn claude_cli_bridge.main:app --port "$PORT" >/tmp/bridge-smoke.log 2>&1 &
BRIDGE_PID=$!

for i in $(seq 1 20); do
    if curl -sf "http://localhost:$PORT/healthz" >/dev/null; then
        echo "[smoke] bridge ready"
        break
    fi
    [ "$i" -eq 20 ] && { echo "ERROR: bridge 启动超时" >&2; cat /tmp/bridge-smoke.log >&2; exit 1; }
    sleep 0.5
done

# 3) 用 Anthropic SDK 走一轮（依赖 backend venv 已装 anthropic）
echo "[smoke] running 1-round chat through SDK ..."
"$REPO_ROOT/backend/.venv/bin/python" - <<PYEOF
import asyncio, os, sys
os.environ["ANTHROPIC_BASE_URL"] = "http://localhost:$PORT/v1"
os.environ["ANTHROPIC_API_KEY"] = "fake"
from anthropic import AsyncAnthropic

async def main():
    client = AsyncAnthropic()
    tool = {
        "name": "ask_next_question",
        "description": "ask one question",
        "input_schema": {
            "type": "object",
            "properties": {"content": {"type": "string"}},
            "required": ["content"],
        },
    }
    saw_message_start = False
    saw_tool_use = None
    async with client.messages.stream(
        model="claude-haiku-4-5-20251001",
        system="你是 FinWise 风险评估助手。请输出一个开场白问题。",
        messages=[],
        tools=[tool],
        max_tokens=512,
    ) as stream:
        async for event in stream:
            if event.type == "message_start":
                saw_message_start = True
        final = await stream.get_final_message()
        for block in final.content:
            if getattr(block, "type", None) == "tool_use":
                saw_tool_use = (block.name, dict(block.input))
                break
    if not saw_message_start:
        print("FAIL: 未收到 message_start")
        sys.exit(1)
    if not saw_tool_use:
        print("FAIL: 未解析到 tool_use")
        sys.exit(1)
    name, inp = saw_tool_use
    print(f"OK: tool={name}, content={inp.get('content', '')[:60]}...")

asyncio.run(main())
PYEOF

echo "[smoke] passed."
