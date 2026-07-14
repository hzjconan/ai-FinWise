#!/usr/bin/env bash
# 启动本地 claude-cli-bridge（端口 8787），供 scratch 学习脚本使用。
# 用法：bash backend/scratch/run_bridge.sh
# 停止：Ctrl-C
set -euo pipefail

BRIDGE_DIR="$(cd "$(dirname "$0")/../../tools/claude-cli-bridge" && pwd)"
cd "$BRIDGE_DIR"

echo "启动 claude-cli-bridge → http://localhost:8787 （背后走本地 claude CLI）"
exec .venv/bin/uvicorn claude_cli_bridge.main:app --port 8787
