# mcp-lab — MCP 学习隔离环境

L03（MCP 协议与 Skills）动手部分的**独立环境**，隔离于 `backend/`（和 `langgraph-lab/` 同样做法）。

- **独立 venv**：`mcp-lab/.venv`（不提交，已 gitignore）。依赖清单在 **`requirements.txt`**（版本钉死）：`mcp` 2.3.0（官方 Python SDK）+ FinWise 后端查询所需的 SQLAlchemy / pydantic-settings / pyyaml / anthropic + pytest。**没装 torch**。
- **SDK 版本注意**：mcp 2.x 里 `FastMCP` 改名为 `MCPServer`（`from mcp.server.mcpserver import MCPServer`），网上很多 1.x 教程的写法不能直接用。
- **协议版本**：SDK 默认用 2026-07-28 无状态协议（没有 `initialize`，每个请求在 `_meta` 自带版本等），同时兼容老客户端的握手。
- **数据**：只读 `backend/finwise.db`（开发库）。变量名是 `FINWISE_DATABASE_URL`（FinWise 配置带 `FINWISE_` 前缀）。
- **讲义**：`docs/ai-agent-learning/lessons/L03-mcp-and-skills.md`。

## 文件
- `finwise_mcp_server.py` — 把 FinWise 的 `search_products` 包成 stdio MCP server，直接复用 `chat_service._execute_tool`（工具只实现一次）。
- `raw_jsonrpc_demo.py` — 不用客户端库，亲手发 JSON-RPC（无状态版 + 握手版各演示一遍），打印每条原始消息。
- `test_finwise_mcp_server.py` — 用官方 `Client` 在进程内连 server 测试，内存 SQLite，不碰开发库；另含 HTTP 模式、Bearer 鉴权（401）测试。
- `mcp_config.yaml` — 5e-3 线上 Host 的配置（= 线上的"注册"）：server 白名单、URL、`token_env`（只写环境变量名）、重试参数、agent → server 分配。
- `online_host.py` — 5e-3 模拟线上 Host（`McpHost`：startup / answer / shutdown）：读 token 注入请求头、共享 HTTP 客户端 + 工具缓存、每请求一个 MCP 会话跑 agent loop、审计 token 不进模型、重试 / 冷却 / 降级。
- `test_online_host.py` — Host 测试（假 LLM，不调真模型），含"server 中途挂掉 → 冷却 → 自动重连"。

## 运行模式
- stdio（默认，Claude Code 当子进程启动）：`.venv/bin/python finwise_mcp_server.py`
- HTTP：`.venv/bin/python finwise_mcp_server.py --http [--port 8765]`（默认 8765，避开后端的 8000）
- HTTP + 鉴权：`FINWISE_MCP_TOKEN=<token> .venv/bin/python finwise_mcp_server.py --http`
- 线上 Host 演示（需 bridge）：`FINWISE_MCP_TOKEN=<同一个 token> .venv/bin/python online_host.py`

## 跑
```
cd mcp-lab
.venv/bin/python -m pytest test_finwise_mcp_server.py -v
.venv/bin/python raw_jsonrpc_demo.py
```

## 建环境（依赖见 requirements.txt，版本已钉死）
```
cd mcp-lab
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
