---
name: dev-server
description: 启动前端和后端开发服务器，如果端口被占用则先杀掉进程再启动
allowed-tools: Bash
---

启动前端（Vite）和后端（FastAPI）开发服务器。如果端口已被占用，先杀掉占用端口的进程再启动。

## 端口

- 管理端前端（Vite）：5174
- 客户端前端（Vite）：5173
- 后端（FastAPI/uvicorn）：8000
- claude-cli-bridge（FastAPI）：8787

## 步骤

1. 使用 `lsof -ti :端口号` 检查相关端口是否被占用
2. 如果被占用，使用 `kill -9 $(lsof -ti :端口号)` 杀掉占用进程
3. 当 `FINWISE_LLM_PROVIDER=api` 时，在后台启动 claude-cli-bridge（默认 mock 跳过此步）：
   ```
   cd tools/claude-cli-bridge && .venv/bin/uvicorn claude_cli_bridge.main:app --port 8787
   ```
   后端环境需配套设置 `ANTHROPIC_BASE_URL=http://localhost:8787`（**不要带 `/v1`**，SDK 自动追加）和
   `ANTHROPIC_API_KEY=fake`。
4. 在后台启动后端服务器（脚本内部会先跑 `alembic upgrade head` 对齐 schema，再起 uvicorn）：
   ```
   bash backend/scripts/dev.sh
   ```
5. 在后台启动管理端前端：
   ```
   cd frontend-admin && npm run dev
   ```
6. 在后台启动客户端前端：
   ```
   cd frontend-customer && npm run dev
   ```
7. 所有服务器都使用 Bash 工具的 `run_in_background: true` 参数在后台启动
8. 向用户报告访问地址：
   - 管理端前端：http://localhost:5174
   - 客户端前端：http://localhost:5173
   - 后端 API：http://localhost:8000
   - bridge（仅当启用 api provider）：http://localhost:8787

## 参数

- `$ARGUMENTS` 可以是：`frontend-admin`、`frontend-customer`、`backend`、`bridge` 或 `all`（默认为 `all`）
  - `frontend-admin` - 只启动管理端前端
  - `frontend-customer` - 只启动客户端前端
  - `backend` - 只启动后端开发服务器
  - `bridge` - 只启动 claude-cli-bridge
  - `all` - 启动全部（bridge 仅在 FINWISE_LLM_PROVIDER=api 时启动）

## 注意

运行 E2E 测试时不要使用此 skill。E2E 测试有专门的脚本 `scripts/e2e-test.sh`，它会使用独立的测试数据库启动服务器。
