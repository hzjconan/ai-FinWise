#!/usr/bin/env bash
# dev 后端启动：先对齐迁移，再起 uvicorn。
# 由 .claude/skills/dev-server 调用，或本地直接运行。
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  echo "[dev.sh] .venv 不存在，请先：python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'" >&2
  exit 1
fi

source .venv/bin/activate

echo "[dev.sh] alembic upgrade head ..."
alembic upgrade head

echo "[dev.sh] starting uvicorn on :8000 ..."
exec uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
