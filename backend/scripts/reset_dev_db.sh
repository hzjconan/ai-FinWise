#!/usr/bin/env bash
# 重置 dev SQLite 数据库：删库 → 跑迁移。
# 用于 schema/迁移混乱时一键救援。不要对生产数据库使用。
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  echo "[reset_dev_db.sh] .venv 不存在" >&2
  exit 1
fi

source .venv/bin/activate

DB_FILE="finwise.db"
if [ -f "$DB_FILE" ]; then
  echo "[reset_dev_db.sh] removing $DB_FILE"
  rm -f "$DB_FILE"
fi

echo "[reset_dev_db.sh] alembic upgrade head ..."
alembic upgrade head
echo "[reset_dev_db.sh] done. 启动后 seed_default_admin 会补回默认管理员。"
