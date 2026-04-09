# 理财产品推荐系统 — 系统规格说明书 v1.0

## 1. 系统架构

```
┌─────────────────────────────────────────────────────┐
│                    客户端 (React)                      │
│  ┌──────────────────┐  ┌──────────────────────────┐  │
│  │   管理端 (Admin)   │  │     客户端 (Customer)     │  │
│  │   Ant Design      │  │   Ant Design Mobile      │  │
│  │   /admin/*        │  │   /*                     │  │
│  └────────┬─────────┘  └────────────┬─────────────┘  │
│           │                         │                 │
└───────────┼─────────────────────────┼─────────────────┘
            │         HTTP/REST       │
            ▼                         ▼
┌─────────────────────────────────────────────────────┐
│                  API Gateway (FastAPI)                │
│                                                      │
│  ┌────────────┐ ┌────────────┐ ┌──────────────────┐ │
│  │ 产品模块    │ │ 问卷模块    │ │  评估 & 推荐模块  │ │
│  │ /api/v1/   │ │ /api/v1/   │ │  /api/v1/        │ │
│  │ products   │ │ questions  │ │  assessments     │ │
│  └─────┬──────┘ └─────┬──────┘ └───────┬──────────┘ │
│        │              │                │             │
│  ┌─────┴──────────────┴────────────────┴───────────┐ │
│  │              Service Layer                       │ │
│  │  ┌──────────┐ ┌───────────┐ ┌────────────────┐  │ │
│  │  │产品服务   │ │问卷服务    │ │风险计算引擎     │  │ │
│  │  └──────────┘ └───────────┘ └────────────────┘  │ │
│  └──────────────────────┬──────────────────────────┘ │
│                         │                            │
│  ┌──────────────────────┴──────────────────────────┐ │
│  │           SQLAlchemy ORM Layer                   │ │
│  └──────────────────────┬──────────────────────────┘ │
└─────────────────────────┼────────────────────────────┘
                          │
                          ▼
                ┌──────────────────┐
                │  SQLite / PgSQL  │
                └──────────────────┘
```

---

## 2. 数据模型

### 2.1 ER 关系图

```
┌──────────────┐       ┌───────────────────────┐
│    Admin     │       │       Product         │
├──────────────┤       ├───────────────────────┤
│ id (PK,auto) │       │ id (PK,auto)          │
│ username     │  1:N  │ product_code (UQ)     │ ◀── 管理员录入，对外标识
│ password_hash│──────▶│ name                  │
│ created_at   │       │ type                  │
│              │       │ investment_direction   │
│              │       │ min_investment         │
│              │       │ investment_period      │
│              │       │ description            │
│              │       │ status                 │
│              │       │ expected_return        │ ◀── 自动计算
│              │       │ risk_level (R1-R5)     │ ◀── 自动计算
│              │       │ created_by (FK)        │
│              │       │ created_at / updated_at│
└──────────────┘       └───────────┬───────────┘
                                   │ 1:N
                                   ▼
                          ┌───────────────────┐
                          │  ReturnHistory    │
                          ├───────────────────┤
                          │ id (PK,auto)      │
                          │ product_id (FK)   │
                          │ period_label      │
                          │ return_rate       │
                          │ recorded_at       │
                          └───────────────────┘

┌──────────────────┐
│    Question      │
├──────────────────┤
│ id (PK,auto)     │       ┌───────────────────┐
│ content          │  1:N  │  QuestionOption   │
│ sort_order       │──────▶├───────────────────┤
│ is_active        │       │ id (PK,auto)      │
│ created_at       │       │ question_id (FK)  │
│ updated_at       │       │ content           │
└──────────────────┘       │ score             │
                           └───────────────────┘

┌──────────────────────┐
│      Customer        │
├──────────────────────┤
│ id (PK,auto)         │    ┌───────────────────────┐
│ code (UQ)            │    │    Assessment         │
│ username (UQ,NULL)   │1:N ├───────────────────────┤
│ password_hash (NULL) │───▶│ id (PK,auto)          │
│ is_registered        │    │ code (UQ)             │ ◀── 系统生成，对外标识
│ nickname             │
│ avatar_url           │
│ created_at           │
└──────────────────┘       │ customer_id (FK)      │
       │                   │ source (questionnaire │
       │                   │         / ai_chat)    │
       │                   │ total_score           │
       │                   │ normalized_score      │
       │                   │ risk_preference (C1-5)│
       │                   │ ai_summary            │
       │                   │ ai_dimensions (JSON)  │
       │                   │ created_at            │
       │ 1:N               └───────────┬───────────┘
       │                               │ 1:N
       ▼                               ▼
┌──────────────────┐       ┌───────────────────────┐
│   Favorite       │       │  AssessmentAnswer     │
├──────────────────┤       ├───────────────────────┤
│ id (PK,auto)     │       │ id (PK,auto)          │
│ customer_id (FK) │       │ assessment_id (FK)    │
│ product_id (FK)  │       │ question_id (FK)      │
│ created_at       │       │ option_id (FK)        │
└──────────────────┘       └───────────────────────┘
```

### 2.2 表结构详细定义

#### 主键与对外标识策略

- **所有表主键**: BIGINT 自增，仅内部使用，不对外暴露
- **products**: 使用管理员录入的 `product_code` 作为对外标识（如 "WY-2025-001"）
- **customers**: 使用系统生成的 `code` 作为对外标识（格式 "CUS-YYYYMMDD-NNN"）
- **assessments**: 使用系统生成的 `code` 作为对外标识（格式 "ASM-YYYYMMDD-NNN"）
- **其他表**: 仅内部关联使用，不直接对外暴露 ID

API 路径示例：`GET /products/WY-2025-001`，`GET /customers/CUS-20250409-001/assessments`

---

#### admins — 管理员

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键（内部） |
| username | VARCHAR(50) | UNIQUE, NOT NULL | 登录用户名 |
| password_hash | VARCHAR(255) | NOT NULL | bcrypt 哈希密码 |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW | 创建时间 |

#### products — 理财产品

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键（内部） |
| product_code | VARCHAR(50) | UNIQUE, NOT NULL | 产品编号，管理员录入，对外标识 |
| name | VARCHAR(100) | NOT NULL | 产品名称 |
| type | VARCHAR(50) | NOT NULL | 产品类型（货币基金/债券/股票/混合/另类） |
| investment_direction | TEXT | | 投资方向描述 |
| min_investment | DECIMAL(12,2) | NOT NULL, DEFAULT 0 | 起投金额（元） |
| investment_period | INTEGER | | 投资期限（天），NULL 表示活期 |
| description | TEXT | | 产品详细描述 |
| status | VARCHAR(10) | NOT NULL, DEFAULT 'draft' | draft / active / inactive |
| expected_return | DECIMAL(8,4) | | 期望收益率（%），自动计算 |
| return_stddev | DECIMAL(8,4) | | 收益率标准差（%），自动计算 |
| risk_level | VARCHAR(2) | | R1-R5，自动计算 |
| created_by | BIGINT | FK → admins.id | 创建人 |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW | 创建时间 |
| updated_at | TIMESTAMP | NOT NULL, DEFAULT NOW | 更新时间 |

#### return_histories — 历史收益记录

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键（内部） |
| product_id | BIGINT | FK → products.id, NOT NULL | 所属产品 |
| period_label | VARCHAR(20) | NOT NULL | 期次标签（如 "2024-Q1"） |
| return_rate | DECIMAL(8,4) | NOT NULL | 该期收益率（%） |
| recorded_at | DATE | NOT NULL | 记录日期 |

**索引**: (product_id, recorded_at) UNIQUE

#### questions — 评估问题

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键（内部） |
| content | TEXT | NOT NULL | 题目内容 |
| sort_order | INTEGER | NOT NULL, DEFAULT 0 | 排列顺序 |
| is_active | BOOLEAN | NOT NULL, DEFAULT TRUE | 是否启用 |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW | 创建时间 |
| updated_at | TIMESTAMP | NOT NULL, DEFAULT NOW | 更新时间 |

#### question_options — 题目选项

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键（内部） |
| question_id | BIGINT | FK → questions.id, NOT NULL | 所属题目 |
| content | VARCHAR(200) | NOT NULL | 选项内容 |
| score | INTEGER | NOT NULL | 该选项分值（1-5） |

#### customers — 客户

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键（内部） |
| code | VARCHAR(20) | UNIQUE, NOT NULL | 对外标识，系统生成（CUS-YYYYMMDD-NNN） |
| username | VARCHAR(50) | UNIQUE, NULL | 登录用户名（注册后填充） |
| password_hash | VARCHAR(255) | NULL | bcrypt 哈希密码（注册后填充） |
| is_registered | BOOLEAN | NOT NULL, DEFAULT FALSE | 是否已注册 |
| nickname | VARCHAR(50) | | 昵称 |
| avatar_url | VARCHAR(500) | | 头像地址 |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW | 创建时间 |

#### assessments — 评估记录

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键（内部） |
| code | VARCHAR(20) | UNIQUE, NOT NULL | 对外标识，系统生成（ASM-YYYYMMDD-NNN） |
| customer_id | BIGINT | FK → customers.id, NOT NULL | 所属客户 |
| source | VARCHAR(20) | NOT NULL | questionnaire / ai_chat |
| total_score | INTEGER | | 问卷总分（问卷模式） |
| normalized_score | DECIMAL(5,2) | | 归一化分数 0-100 |
| risk_preference | VARCHAR(2) | NOT NULL | C1-C5 |
| ai_summary | TEXT | | AI 评估摘要（AI 模式） |
| ai_dimensions | JSON | | AI 维度评分（AI 模式） |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW | 创建时间 |

#### assessment_answers — 问卷评估作答记录

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键（内部） |
| assessment_id | BIGINT | FK → assessments.id, NOT NULL | 所属评估 |
| question_id | BIGINT | FK → questions.id, NOT NULL | 题目 |
| option_id | BIGINT | FK → question_options.id, NOT NULL | 所选选项 |

#### favorites — 产品收藏

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键（内部） |
| customer_id | BIGINT | FK → customers.id, NOT NULL | 客户 |
| product_id | BIGINT | FK → products.id, NOT NULL | 产品 |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW | 收藏时间 |

**索引**: (customer_id, product_id) UNIQUE

---

## 3. API 接口规格

### 3.0 通用约定

- **Base URL**: `/api/v1`
- **认证**: 管理端接口使用 JWT Bearer Token；客户端接口暂不认证（阶段一）
- **分页**: `?page=1&page_size=20`，响应包含 `total`, `page`, `page_size`
- **错误格式**:
  ```json
  {
    "detail": {
      "code": "PRODUCT_NOT_FOUND",
      "message": "产品不存在"
    }
  }
  ```

### 3.1 认证模块

#### POST /auth/admin/login
管理员登录，获取 JWT Token。

**Request Body**:
```json
{
  "username": "admin",
  "password": "123456"
}
```

**Response 200**:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

**Error 401**: 用户名或密码错误

#### POST /auth/customer/anonymous
匿名客户初始化，系统自动创建 customer 记录并返回 code。

**Response 201**:
```json
{
  "customer_code": "CUS-20250409-001",
  "is_registered": false
}
```

#### POST /auth/customer/register
匿名客户注册（绑定用户名和密码到已有 customer 记录）。

**Request Body**:
```json
{
  "customer_code": "CUS-20250409-001",
  "username": "zhangsan",
  "password": "secure123",
  "nickname": "张三"
}
```

**Response 200**:
```json
{
  "customer_code": "CUS-20250409-001",
  "username": "zhangsan",
  "is_registered": true,
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

**Error 409**: 用户名已存在

#### POST /auth/customer/login
已注册客户登录。

**Request Body**:
```json
{
  "username": "zhangsan",
  "password": "secure123"
}
```

**Response 200**:
```json
{
  "customer_code": "CUS-20250409-001",
  "username": "zhangsan",
  "nickname": "张三",
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 86400
}
```

**Error 401**: 用户名或密码错误

---

### 3.2 产品模块（管理端）

#### GET /admin/products
获取产品列表（分页，支持筛选）。

**Query Params**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | int | 否 | 页码，默认 1 |
| page_size | int | 否 | 每页条数，默认 20 |
| status | string | 否 | draft / active / inactive |
| risk_level | string | 否 | R1-R5 |
| type | string | 否 | 产品类型 |

**Response 200**:
```json
{
  "total": 42,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "product_code": "WY-2025-001",
      "name": "稳健增值1号",
      "type": "债券",
      "investment_direction": "国债、企业债",
      "min_investment": 10000.00,
      "investment_period": 365,
      "status": "active",
      "expected_return": 4.25,
      "return_stddev": 1.80,
      "risk_level": "R2",
      "created_at": "2025-01-15T10:30:00Z"
    }
  ]
}
```

#### POST /admin/products
创建产品。

**Request Body**:
```json
{
  "product_code": "WY-2025-001",
  "name": "稳健增值1号",
  "type": "债券",
  "investment_direction": "国债、企业债",
  "min_investment": 10000.00,
  "investment_period": 365,
  "description": "以固定收益类资产为主的稳健型产品"
}
```

**Response 201**: 返回创建的产品对象（含 product_code）

#### GET /admin/products/{product_code}
获取单个产品详情（含历史收益数据）。

**Response 200**:
```json
{
  "product_code": "WY-2025-001",
  "name": "稳健增值1号",
  "type": "债券",
  "investment_direction": "国债、企业债",
  "min_investment": 10000.00,
  "investment_period": 365,
  "description": "...",
  "status": "active",
  "expected_return": 4.25,
  "return_stddev": 1.80,
  "risk_level": "R2",
  "created_at": "2025-01-15T10:30:00Z",
  "updated_at": "2025-01-15T10:30:00Z",
  "return_histories": [
    { "period_label": "2024-Q1", "return_rate": 4.10, "recorded_at": "2024-03-31" },
    { "period_label": "2024-Q2", "return_rate": 4.35, "recorded_at": "2024-06-30" }
  ]
}
```

#### PUT /admin/products/{product_code}
更新产品基本信息。

**Request Body**: 同 POST（不含 product_code），所有字段可选（部分更新）。

**Response 200**: 返回更新后的产品对象

#### PATCH /admin/products/{product_code}/status
变更产品状态。

**Request Body**:
```json
{
  "status": "active"
}
```

**Response 200**: 返回更新后的产品对象

#### POST /admin/products/{product_code}/returns
为产品添加历史收益记录。添加后自动重新计算 expected_return、return_stddev、risk_level。

**Request Body**:
```json
{
  "period_label": "2024-Q3",
  "return_rate": 4.50,
  "recorded_at": "2024-09-30"
}
```

**Response 201**: 返回创建的收益记录 + 更新后的产品风险指标

```json
{
  "return_history": {
    "period_label": "2024-Q3",
    "return_rate": 4.50,
    "recorded_at": "2024-09-30"
  },
  "product_metrics": {
    "expected_return": 4.32,
    "return_stddev": 2.10,
    "risk_level": "R2"
  }
}
```

#### DELETE /admin/products/{product_code}/returns/{return_id}
删除一条历史收益记录（return_id 为内部 ID，从产品详情的 return_histories 中获取），自动重新计算风险指标。

**Response 200**: 返回更新后的产品风险指标

---

### 3.3 问卷模块（管理端）

#### GET /admin/questions
获取所有题目（含选项，按 sort_order 排序）。

**Response 200**:
```json
{
  "items": [
    {
      "id": 1,
      "content": "您的年龄段是？",
      "sort_order": 1,
      "is_active": true,
      "options": [
        { "id": 1, "content": "25岁以下", "score": 5 },
        { "id": 1, "content": "25-35岁", "score": 4 },
        { "id": 1, "content": "35-50岁", "score": 3 },
        { "id": 1, "content": "50-60岁", "score": 2 },
        { "id": 1, "content": "60岁以上", "score": 1 }
      ]
    }
  ]
}
```

#### POST /admin/questions
创建题目（含选项）。

**Request Body**:
```json
{
  "content": "您的年龄段是？",
  "sort_order": 1,
  "options": [
    { "content": "25岁以下", "score": 5 },
    { "content": "25-35岁", "score": 4 },
    { "content": "35-50岁", "score": 3 },
    { "content": "50-60岁", "score": 2 },
    { "content": "60岁以上", "score": 1 }
  ]
}
```

**Response 201**: 返回创建的题目（含选项 id）

#### PUT /admin/questions/{id}
更新题目内容和选项。

**Request Body**: 同 POST，完整替换选项列表。

**Response 200**: 返回更新后的题目

#### DELETE /admin/questions/{id}
删除题目（级联删除选项）。

**Response 204**

#### PUT /admin/questions/sort
批量更新题目排序。

**Request Body**:
```json
{
  "orders": [
    { "id": 1, "sort_order": 1 },
    { "id": 2, "sort_order": 2 },
    { "id": 3, "sort_order": 3 }
  ]
}
```

**Response 200**

---

### 3.4 客户端 — 产品浏览

#### GET /products
获取上架产品列表（仅 status=active）。

**Query Params**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | int | 否 | 页码，默认 1 |
| page_size | int | 否 | 每页条数，默认 20 |
| risk_level | string | 否 | R1-R5 |
| type | string | 否 | 产品类型 |
| sort_by | string | 否 | expected_return / risk_level，默认 expected_return |
| sort_order | string | 否 | asc / desc，默认 desc |

**Response 200**: 同管理端产品列表结构（不含 status 和 created_by）

#### GET /products/{product_code}
获取产品详情（含历史收益数据，用于画收益走势图）。

**Response 200**: 同管理端产品详情结构（不含 status 和 created_by）

---

### 3.5 客户端 — 风险评估

#### GET /assessment/questions
获取当前启用的所有题目（含选项，按 sort_order 排序）。

**Response 200**: 同管理端 GET /admin/questions，但仅返回 is_active=true 的题目

#### POST /assessment/submit
提交问卷评估结果。

**Request Body**:
```json
{
  "customer_code": "CUS-20250409-001",
  "answers": [
    { "question_id": 1, "option_id": 3 },
    { "question_id": 2, "option_id": 7 },
    { "question_id": 3, "option_id": 12 }
  ]
}
```

**Response 200**:
```json
{
  "assessment_code": "ASM-20250409-001",
  "source": "questionnaire",
  "total_score": 28,
  "normalized_score": 56.0,
  "risk_preference": "C3",
  "risk_label": "平衡型",
  "description": "您属于平衡型投资者，愿意承担适度风险以获得合理回报。"
}
```

---

### 3.6 客户端 — AI 对话评估（阶段二）

#### POST /assessment/chat/start
创建 AI 评估会话。

**Request Body**:
```json
{
  "customer_code": "CUS-20250409-001"
}
```

**Response 200**:
```json
{
  "session_id": "ASM-20250409-002",
  "message": {
    "role": "assistant",
    "content": "您好！我是您的理财风险评估助手。接下来我会问您几个问题，帮您了解自己的投资风格。请放轻松，没有标准答案。\n\n首先想请问，您之前有过投资理财的经验吗？比如购买过基金、股票或其他理财产品？"
  }
}
```

#### POST /assessment/chat/{assessment_code}/message
发送用户消息，获取 AI 回复。

**Request Body**:
```json
{
  "content": "买过一些基金，但大部分是货币基金"
}
```

**Response 200**（对话中）:
```json
{
  "message": {
    "role": "assistant",
    "content": "了解，货币基金确实是比较稳健的选择。那请问..."
  },
  "is_complete": false
}
```

**Response 200**（评估完成）:
```json
{
  "message": {
    "role": "assistant",
    "content": "感谢您的耐心回答！根据我们的对话，我对您的投资风格有了比较清晰的了解..."
  },
  "is_complete": true,
  "assessment": {
    "assessment_code": "ASM-20250409-002",
    "source": "ai_chat",
    "risk_preference": "C2",
    "risk_label": "稳健型",
    "ai_summary": "基于对话分析，您投资经验较少，偏好稳定收益...",
    "ai_dimensions": {
      "experience": 2,
      "loss_tolerance": 2,
      "income_stability": 4,
      "investment_horizon": 3,
      "volatility_tolerance": 2
    }
  }
}
```

---

### 3.7 客户端 — 产品推荐

#### GET /recommendations
根据客户最新评估结果获取推荐产品。

**Query Params**:
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| customer_code | string | 是 | 客户编码（如 CUS-20250409-001） |

**Response 200**:
```json
{
  "risk_preference": "C3",
  "risk_label": "平衡型",
  "exact_matches": [
    {
      "product_code": "HH-2025-003",
      "name": "平衡优选3号",
      "type": "混合",
      "expected_return": 6.80,
      "risk_level": "R3",
      "match_type": "exact"
    }
  ],
  "adjacent_matches": [
    {
      "product_code": "WY-2025-001",
      "name": "稳健增值1号",
      "type": "债券",
      "expected_return": 4.25,
      "risk_level": "R2",
      "match_type": "conservative"
    },
    {
      "product_code": "GP-2025-005",
      "name": "成长先锋5号",
      "type": "股票",
      "expected_return": 12.50,
      "risk_level": "R4",
      "match_type": "aggressive"
    }
  ]
}
```

**Error 404**: 客户未完成风险评估

---

### 3.8 客户端 — 收藏

#### GET /customers/{customer_code}/favorites
获取客户收藏的产品列表。

**Response 200**: 产品列表数组（含 product_code、name、type、expected_return、risk_level）

#### POST /customers/{customer_code}/favorites
收藏产品。

**Request Body**:
```json
{
  "product_code": "WY-2025-001"
}
```

**Response 201**

#### DELETE /customers/{customer_code}/favorites/{product_code}
取消收藏。

**Response 204**

---

### 3.9 客户端 — 评估历史

#### GET /customers/{customer_code}/assessments
获取客户历史评估记录。

**Response 200**:
```json
{
  "items": [
    {
      "code": "ASM-20250310-001",
      "source": "questionnaire",
      "risk_preference": "C3",
      "risk_label": "平衡型",
      "created_at": "2025-03-10T14:30:00Z"
    },
    {
      "code": "ASM-20250315-001",
      "source": "ai_chat",
      "risk_preference": "C2",
      "risk_label": "稳健型",
      "ai_summary": "基于对话分析...",
      "created_at": "2025-03-15T09:20:00Z"
    }
  ]
}
```

---

## 4. 后端项目结构

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI 入口，注册路由
│   ├── config.py                # 配置（数据库 URL、JWT 密钥等）
│   ├── database.py              # SQLAlchemy 引擎 & Session
│   │
│   ├── models/                  # SQLAlchemy 数据模型
│   │   ├── __init__.py
│   │   ├── admin.py
│   │   ├── product.py
│   │   ├── question.py
│   │   ├── customer.py
│   │   └── assessment.py
│   │
│   ├── schemas/                 # Pydantic 请求/响应模型
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── product.py
│   │   ├── question.py
│   │   ├── customer.py
│   │   └── assessment.py
│   │
│   ├── routers/                 # API 路由
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── admin_products.py
│   │   ├── admin_questions.py
│   │   ├── products.py
│   │   ├── assessment.py
│   │   ├── recommendations.py
│   │   └── customers.py
│   │
│   ├── services/                # 业务逻辑
│   │   ├── __init__.py
│   │   ├── product_service.py
│   │   ├── question_service.py
│   │   ├── risk_calculator.py   # 风险计算引擎
│   │   ├── assessment_service.py
│   │   └── recommendation_service.py
│   │
│   └── utils/                   # 工具函数
│       ├── __init__.py
│       ├── auth.py              # JWT 工具
│       └── pagination.py        # 分页工具
│
├── alembic/                     # 数据库迁移
│   └── versions/
├── alembic.ini
├── requirements.txt
└── pyproject.toml
```

## 5. 前端项目结构

```
frontend/
├── public/
├── src/
│   ├── main.tsx                 # 入口
│   ├── App.tsx                  # 路由配置
│   │
│   ├── api/                     # API 请求封装
│   │   ├── client.ts            # Axios 实例
│   │   ├── products.ts
│   │   ├── questions.ts
│   │   ├── assessment.ts
│   │   └── recommendations.ts
│   │
│   ├── stores/                  # Zustand 状态管理
│   │   ├── authStore.ts
│   │   ├── productStore.ts
│   │   └── assessmentStore.ts
│   │
│   ├── pages/
│   │   ├── admin/               # 管理端页面
│   │   │   ├── Login.tsx
│   │   │   ├── Dashboard.tsx
│   │   │   ├── ProductList.tsx
│   │   │   ├── ProductEdit.tsx
│   │   │   ├── QuestionList.tsx
│   │   │   └── QuestionPreview.tsx
│   │   │
│   │   └── customer/            # 客户端页面
│   │       ├── Home.tsx
│   │       ├── ProductList.tsx
│   │       ├── ProductDetail.tsx
│   │       ├── Assessment.tsx
│   │       ├── AssessmentChat.tsx    # 阶段二
│   │       ├── AssessmentResult.tsx
│   │       └── Profile.tsx
│   │
│   ├── components/              # 共享组件
│   │   ├── admin/
│   │   │   └── AdminLayout.tsx
│   │   ├── customer/
│   │   │   └── CustomerLayout.tsx
│   │   └── shared/
│   │       ├── RiskBadge.tsx    # 风险等级标签
│   │       └── ReturnChart.tsx  # 收益走势图
│   │
│   └── utils/
│       ├── constants.ts         # 风险等级映射等常量
│       └── formatters.ts        # 格式化工具
│
├── index.html
├── vite.config.ts
├── tsconfig.json
└── package.json
```
