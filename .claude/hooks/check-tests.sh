#!/usr/bin/env bash
# Stop hook: 强制校验源码改动有对应测试。memory/feedback_testing_required.md 硬约束的 harness 抓手。
#
# 规则：
#   - frontend-admin/src 或 frontend-customer/src 有改动 → 必须有对应 cypress/e2e 改动
#   - backend/app 有改动 → 必须有对应 backend/tests 改动
# 豁免：
#   - 白名单路径（文档/样式/config）不触发
#   - 紧急绕过：环境变量 CLAUDE_SKIP_TEST_CHECK=1
# 兼容 bash 3.2（macOS 自带）。

set -u
set -o pipefail 2>/dev/null || true

input=$(cat || true)
case "$input" in
  *'"stop_hook_active"'*true*) exit 0 ;;
esac

cd "$(dirname "$0")/../.." || exit 0

git rev-parse --git-dir >/dev/null 2>&1 || exit 0

changed=$({
  git diff --name-only HEAD 2>/dev/null
  git ls-files --others --exclude-standard 2>/dev/null
} | sort -u | sed '/^$/d')

[ -z "$changed" ] && exit 0

is_exempt() {
  case "$1" in
    *.md|*.json|*.lock|*.yml|*.yaml|*.toml|*.cfg|*.ini|*.env*) return 0 ;;
    *.css|*.scss|*.svg|*.png|*.jpg|*.jpeg|*.ico|*.gif) return 0 ;;
    .claude/*|.github/*|.gitignore|.dockerignore) return 0 ;;
    docs/*|README*|CLAUDE.md) return 0 ;;
    scripts/*) return 0 ;;
    backend/alembic/versions/*) return 0 ;;
    */constants.ts|*/constants.tsx) return 0 ;;
  esac
  return 1
}

frontend_src=0
backend_src=0
frontend_test=0
backend_test=0
src_list=""

while IFS= read -r f; do
  [ -z "$f" ] && continue
  if is_exempt "$f"; then continue; fi
  case "$f" in
    frontend-admin/src/*|frontend-customer/src/*)
      frontend_src=1
      src_list="$src_list  - $f
"
      ;;
    backend/app/*)
      backend_src=1
      src_list="$src_list  - $f
"
      ;;
    frontend-admin/cypress/e2e/*|frontend-customer/cypress/e2e/*)
      frontend_test=1
      ;;
    backend/tests/*)
      backend_test=1
      ;;
  esac
done <<EOF
$changed
EOF

missing=""
if [ $frontend_src -eq 1 ] && [ $frontend_test -eq 0 ]; then
  missing="$missing  - 前端 src 有改动但未见 cypress/e2e/ 的新增或修改
"
fi
if [ $backend_src -eq 1 ] && [ $backend_test -eq 0 ]; then
  missing="$missing  - 后端 app 有改动但未见 backend/tests/ 的新增或修改
"
fi

alembic_drift=""
if [ $backend_src -eq 1 ] && [ -f backend/.venv/bin/alembic ]; then
  if ! drift_out=$(cd backend && ./.venv/bin/alembic check 2>&1); then
    alembic_drift=$(printf '%s' "$drift_out" | tail -3)
  fi
fi

if [ -z "$missing" ] && [ -z "$alembic_drift" ]; then
  exit 0
fi

if [ "${CLAUDE_SKIP_TEST_CHECK:-}" = "1" ]; then
  echo "[check-tests] CLAUDE_SKIP_TEST_CHECK=1 跳过强制校验" >&2
  exit 0
fi

{
  echo "❌ Stop hook 拦截 — memory: feedback_testing_required"
  echo
  echo "改动源文件："
  printf '%s' "$src_list"
  if [ -n "$missing" ]; then
    echo "缺测试项："
    printf '%s' "$missing"
  fi
  if [ -n "$alembic_drift" ]; then
    echo "模型与迁移不一致（alembic check 失败）："
    printf '%s\n' "$alembic_drift" | sed 's/^/  /'
    echo "  → 在 backend/ 下跑 alembic revision --autogenerate -m \"...\"，或把模型改回与迁移一致。"
  fi
  echo "请修复后重新结束本轮。紧急绕过：CLAUDE_SKIP_TEST_CHECK=1。"
} >&2

exit 2
