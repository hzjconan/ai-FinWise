# FinWise 智财通

智能理财产品推荐系统，包含管理后台和客户端两个界面。管理员可管理理财产品和风险评估问卷，客户可浏览产品、完成风险评估并获取个性化产品推荐。

## 技术栈

- **前端**：React + TypeScript + Ant Design + Vite
- **后端**：Python + FastAPI + SQLAlchemy + SQLite
- **测试**：后端 pytest / 前端 Cypress E2E

## 项目结构

```
├── backend/          # FastAPI 后端
│   ├── app/          # 应用代码（models, routers, services, utils）
│   ├── alembic/      # 数据库迁移
│   └── tests/        # pytest 测试
├── frontend/         # React 前端
│   ├── src/          # 应用代码（pages, components, api, stores）
│   └── cypress/      # Cypress E2E 测试
└── docs/             # 产品与系统规格文档
```

## 本地启动

### 环境要求

- Python 3.12+
- Node.js 18+

### 1. 启动后端

```bash
cd backend

# 首次使用：创建虚拟环境并安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 启动服务（dev 模式会自动建表并创建默认管理员 admin/admin123）
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

后端启动后可访问 API 文档：http://127.0.0.1:8000/docs

### 2. 启动前端

```bash
cd frontend

# 首次使用：安装依赖
npm install

# 启动开发服务器（自动代理 /api 请求到后端）
npm run dev
```

前端启动后访问：http://localhost:5173

- 客户端首页：http://localhost:5173
- 管理后台：http://localhost:5173/admin/login（默认账号 `admin` / `admin123`）

## 运行测试

### 后端测试（pytest）

```bash
cd backend
source .venv/bin/activate
pytest
```

共 66 个测试用例，覆盖风险计算、认证、产品管理、问卷管理、评估、推荐、客户功能。

### 前端测试（Cypress E2E）

运行前需先启动后端和前端服务（见上方），然后：

```bash
cd frontend

# 命令行模式（无头浏览器）
npx cypress run --browser chrome

# 图形界面模式（可交互调试）
npx cypress open
```

共 30 个 E2E 测试用例，覆盖：

| 测试文件 | 覆盖范围 |
|---------|---------|
| admin-login | 管理员登录、认证保护 |
| admin-products | 产品 CRUD、状态管理 |
| admin-questions | 问卷题目 CRUD |
| customer-assessment | 风险评估完整流程 |
| customer-home | 首页展示、匿名客户创建 |
| customer-products | 产品浏览、收藏 |
| customer-profile | 个人中心、评估记录、收藏列表 |
