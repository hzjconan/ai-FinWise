---
name: run-tests
description: 执行测试用例，支持运行全部测试、仅后端 pytest 测试或仅前端 Cypress E2E 测试
allowed-tools: Bash
---

执行项目的测试用例。支持运行全部测试，也可以通过参数指定只运行后端或前端的测试。

## 后端测试（pytest）

```
cd backend && source .venv/bin/activate && python -m pytest tests/ -v
```

## 前端测试（Cypress E2E）

前端 Cypress 测试使用独立的测试数据库（`finwise_test.db`），不会影响开发数据库。
脚本会自动启动服务器、运行测试、清理测试数据库。

```
bash scripts/e2e-test.sh admin      # 只运行管理端测试
bash scripts/e2e-test.sh customer   # 只运行客户端测试
bash scripts/e2e-test.sh            # 运行全部前端测试（默认 all）
```

如果只想运行特定的测试文件：
```
bash scripts/e2e-test.sh admin --spec cypress/e2e/admin-login.cy.ts
```

**注意**：不需要提前启动 dev-server，脚本会自动管理服务器生命周期。

## 参数

- `$ARGUMENTS` 可以是：`frontend-admin`、`frontend-customer`、`frontend`、`backend` 或 `all`（默认为 `all`）
  - `frontend-admin` - 只运行管理端 Cypress E2E 测试
  - `frontend-customer` - 只运行客户端 Cypress E2E 测试
  - `frontend` - 运行全部前端 E2E 测试（管理端 + 客户端）
  - `backend` - 只运行后端 pytest 测试
  - `all` - 运行全部测试（先后端，再前端）

## 执行顺序（当运行全部测试时）

1. 先运行后端 pytest 测试
2. 如果后端测试通过，再运行前端 Cypress E2E 测试（先管理端，再客户端）
3. 汇总报告两边的测试结果

## 结果报告

测试完成后，向用户报告：
- 通过/失败的测试数量
- 如果有失败的测试，列出失败的测试名称和错误信息
