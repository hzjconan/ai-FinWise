# AGENTS.md

面向协作 agent（Claude Code / Cursor / 其他）的仓库级硬约束。拉到代码即适用。

## 顶层原则

- **每次代码改动必须有对应测试**，并保证已有测试全绿。
- 不允许"改完先交付，测试以后再补"。如需豁免，必须显式向用户申请并得到确认。

## 测试栈约定

| 层 | 工具 | 路径 |
|---|---|---|
| 后端 | pytest | `backend/tests/` |
| 前端（管理端） | Cypress E2E | `frontend-admin/cypress/e2e/` |
| 前端（客户端） | Cypress E2E | `frontend-customer/cypress/e2e/` |

- 后端测试使用内存 SQLite（`tests/conftest.py`），与开发/生产库隔离。
- 前端 E2E 有独立脚本 `scripts/e2e-test.sh`，启动隔离的测试数据库。请勿用 `/dev-server` skill 跑 E2E。

## 改动 → 测试映射

| 改动类别 | 必须附带的测试 | 建议做法 |
|---|---|---|
| 后端路由 / service | pytest 覆盖成功路径 + 边界/错误 | 参考 `tests/test_admin_products.py` |
| 前端 UI 行为（排序、过滤、跳转、表单提交、条件渲染、API 参数装配） | Cypress E2E | 优先 `cy.intercept` 断言请求参数，解耦种子数据 |
| 前端纯视觉 / 对齐 / 样式 | 可豁免 | DOM 断言价值有限；必须先向用户申请并得到确认 |
| 数据库结构变更（alembic） | 不强制新测试，但需回归已有测试 | — |
| 文档、配置、脚本 | 不强制 | — |

## 豁免机制

1. 纯视觉/样式改动，先向用户解释并申请豁免。
2. 得到确认后，该轮可设置环境变量 `CLAUDE_SKIP_TEST_CHECK=1` 跳过 Stop hook 校验。
3. 豁免不是默认选项——默认必须补测试。

## 自动化抓手（不依赖 agent 自觉）

项目级 Stop hook 已落地：`.claude/hooks/check-tests.sh`（注册于 `.claude/settings.json`）。

规则：
- `frontend-admin/src/**` 或 `frontend-customer/src/**` 有改动 → 必须有对应 `cypress/e2e/**` 改动
- `backend/app/**` 有改动 → 必须有对应 `backend/tests/**` 改动
- 白名单跳过：`*.md`、`*.json`、`*.css/scss`、`scripts/**`、`docs/**`、`backend/alembic/versions/**`、`*/constants.ts`
- 违反时 exit 2，stderr 回注 agent，必须补齐或申请豁免后才能结束本轮
- Loop guard：检测 `stop_hook_active=true` 自动放行，避免循环

手动触发（自测或 CI 复用）：
```bash
echo '{}' | bash .claude/hooks/check-tests.sh
```

## 常见命令

```bash
# 后端单测
cd backend && source .venv/bin/activate && pytest -q

# 前端类型检查
cd frontend-admin && npx tsc --noEmit
cd frontend-customer && npx tsc --noEmit

# 前端 E2E（隔离测试库）
bash scripts/e2e-test.sh
```

## 组合拳回顾

测试硬约束的落地采用 **memory + harness** 双保险：

1. **语义层**（`~/.claude/projects/.../memory/feedback_testing_required.md`）—— agent 的 feedback memory，跨会话持久。
2. **harness 层**（本文件 + `.claude/hooks/check-tests.sh` + `.claude/settings.json`）—— 项目级 Stop hook 在 agent 结束本轮前强制校验，不受 agent 主观判断影响，团队随代码拉通。
