---
name: dev-server
description: 启动前端和后端开发服务器，如果端口被占用则先杀掉进程再启动
allowed-tools: Bash
---

启动前端（Vite）和后端（FastAPI）开发服务器。如果端口已被占用，先杀掉占用端口的进程再启动。

## 端口

- 前端（Vite）：5173
- 后端（FastAPI/uvicorn）：8000

## 步骤

1. 使用 `lsof -ti :端口号` 检查端口 5173 和 8000 是否被占用
2. 如果被占用，使用 `kill -9 $(lsof -ti :端口号)` 杀掉占用进程
3. 在后台启动后端服务器：
   ```
   cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
4. 在后台启动前端服务器：
   ```
   cd frontend && npm run dev
   ```
5. 两个服务器都使用 Bash 工具的 `run_in_background: true` 参数在后台启动
6. 向用户报告访问地址：
   - 前端：http://localhost:5173
   - 后端 API：http://localhost:8000

## 参数

- `$ARGUMENTS` 可以是：`frontend`、`backend` 或 `all`（默认为 `all`）
  - `frontend` - 只启动前端开发服务器
  - `backend` - 只启动后端开发服务器
  - `all` - 启动前端和后端

## 注意

运行 E2E 测试时不要使用此 skill。E2E 测试有专门的脚本 `scripts/e2e-test.sh`，它会使用独立的测试数据库启动服务器。
