# AI 对话风险评估 — 实施设计 v1.0

> 对应产品规格 F-C02 阶段二。本文档落地 AI 对话评估的架构、协议、数据模型、实施计划与关键决策。

---

## 1. 概述

### 1.1 目标
为 F-C02 增加「AI 对话评估」模式，与现有「固定问卷」模式并存。客户在 `/assessment` 自由选择模式；AI 模式通过 5–8 轮自然语言对话收集 5 个维度信息（投资经验、损失承受、收入稳定性、期限预期、波动态度），输出 `risk_preference (C1–C5)` + `ai_summary` + `ai_dimensions`，最终落入与问卷模式同一张 `assessments` 表，差异通过 `source` 字段区分。完成后无缝进入 F-C03 推荐流。

### 1.2 范围
- **包含**：AI 对话评估的端到端实现（后端、前端、bridge dev 工具、测试）
- **包含**：评估完成后复用现有 `AssessmentResult` 页与 F-C03 推荐流
- **不包含**：问卷模式逻辑改动；推荐算法改动；F-C05 注册登录（AI 评估支持匿名客户）

### 1.3 与阶段一的关系
- 数据模型完全复用 `assessments` 表，新增字段 `chat_session_id` 反向关联
- AI 模式的评估结果与问卷模式在下游（推荐、个人中心、首页徽章）等价处理
- 评估历史里通过来源标签 `[问卷] / [AI 对话]` 区分

---

## 2. 整体架构

### 2.1 双路径架构（dev/prod）

```
                                   ┌──────────────────────┐
                                   │  生产环境 (LLM_PROVIDER=api)
                                   │  ANTHROPIC_BASE_URL=  │
                                   │  https://api.anthropic.com │
                                   └──────────┬───────────┘
                                              │
┌──────────────────┐    Anthropic SDK         │
│  FastAPI 后端     │ ───────(HTTP + SSE)──────┴──────▶ 真实 Anthropic API
│  (业务代码)        │
│                  │                          ┌──────────────────────┐
│  统一调用 SDK，   │                          │  本地开发 (LLM_PROVIDER=cli)
│  无分支逻辑       │ ───────(HTTP + SSE)─────▶│  ANTHROPIC_BASE_URL=  │
└──────────────────┘                          │  http://localhost:8787│
                                              │                       │
                                              │  claude-cli-bridge    │
                                              │  (FastAPI 服务)       │
                                              │         │             │
                                              │         ▼ subprocess  │
                                              │  ┌──────────────┐     │
                                              │  │  claude CLI  │     │
                                              │  └──────────────┘     │
                                              └──────────────────────┘
```

### 2.2 Provider 抽象（无 provider 接口层）

业务层**直接使用 Anthropic SDK**，不再实现 `LLMProvider` 抽象接口。两个环境的差异完全收敛在 `ANTHROPIC_BASE_URL` 环境变量：

```python
# 业务代码（dev/prod 一致）
client = anthropic.Anthropic()  # 自动读 ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY
async with client.messages.stream(
    model="claude-haiku-4-5-20251001",
    system=system_prompt,
    messages=messages,
    tools=[ASK_TOOL, CONCLUDE_TOOL],
    max_tokens=1024,
) as stream:
    async for event in stream: ...
```

| 环境 | `ANTHROPIC_BASE_URL` | `ANTHROPIC_API_KEY` | 后端 LLM 流量去向 |
|---|---|---|---|
| dev | `http://localhost:8787` | `fake` | claude-cli-bridge → Claude CLI |
| prod | （默认值，连官方） | 真实 key | api.anthropic.com |

测试环境完全不走真实 SDK：用 `respx` 或类似工具拦截 HTTP，或在更高层 mock `anthropic.Anthropic` 客户端。

---

## 3. 数据模型

### 3.1 新增表

#### chat_sessions — AI 对话会话

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键（内部） |
| code | VARCHAR(20) | UNIQUE, NOT NULL | 对外标识，系统生成（CHAT-YYYYMMDD-NNN） |
| customer_id | BIGINT | FK → customers.id, NOT NULL | 所属客户 |
| status | VARCHAR(20) | NOT NULL, DEFAULT 'active' | active / completed / abandoned |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW | 创建时间 |
| updated_at | TIMESTAMP | NOT NULL, DEFAULT NOW | 最近一次消息时间 |

**索引**: (customer_id, status, created_at DESC) — 支持按客户查最近未完成会话

#### chat_messages — 对话消息

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | BIGINT | PK, AUTO_INCREMENT | 主键（内部） |
| session_id | BIGINT | FK → chat_sessions.id, NOT NULL | 所属会话 |
| role | VARCHAR(20) | NOT NULL | user / assistant |
| content | TEXT | NOT NULL | 消息文本 |
| tool_use | JSON | NULL | assistant 消息的 tool_use 原始结构（含 name + input） |
| tokens_in | INTEGER | NULL | 输入 token 数（assistant 消息可记） |
| tokens_out | INTEGER | NULL | 输出 token 数 |
| latency_ms | INTEGER | NULL | LLM 响应延迟 |
| created_at | TIMESTAMP | NOT NULL, DEFAULT NOW | 创建时间 |

**索引**: (session_id, created_at) — 支持按会话顺序读

### 3.2 现有表扩展

#### assessments — 新增字段

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| chat_session_id | BIGINT | FK → chat_sessions.id, NULL | AI 模式下关联的会话；问卷模式为 NULL |

**用途**：审计追溯——给定一条 AI 评估，可反查当时的完整对话与 prompt 情境。

### 3.3 落盘时机

- **每轮对话完成时**：`chat_messages` 写入两行（user + assistant）；`chat_sessions.updated_at` 刷新
- **conclude_assessment 触发时**：在同一个事务里写入 `assessments` 行 + `chat_sessions.status='completed'` + `assessments.chat_session_id` 关联
- **流式增量过程中不写库**：`assistant` 消息在内存累积完整后再一次性写入，避免高频 IO

---

## 4. API 设计

### 4.1 SSE Endpoint

#### POST /api/v1/assessment/chat/start
创建新会话或恢复未完成会话。

**Request Body**:
```json
{ "customer_code": "CUS-20260423-001" }
```

**Response 200**：
```json
{
  "session_code": "CHAT-20260423-001",
  "resumed": false,
  "messages": [
    {
      "role": "assistant",
      "content": "您好！我是您的理财风险评估助手。接下来我会问您几个问题..."
    }
  ]
}
```

- `resumed=true` 时 `messages` 包含完整历史；客户端按顺序渲染
- 新建会话时后端自动调用一次 LLM 生成开场白，作为第一条 `assistant` 消息落盘

#### POST /api/v1/assessment/chat/{session_code}/message
发送用户消息，流式获取 AI 回复。

**Request Body**:
```json
{ "content": "买过一些基金，但大部分是货币基金" }
```

**Response 200** (SSE，`Content-Type: text/event-stream`)：

```
event: delta
data: {"content": "了解"}

event: delta
data: {"content": "，货币基金"}

event: delta
data: {"content": "确实是比较稳健的选择..."}

event: completed
data: {"phase": "asking", "round": 3}
```

或评估完成轮：

```
event: delta
data: {"content": "感谢您的耐心回答..."}

event: completed
data: {
  "phase": "concluded",
  "round": 6,
  "assessment": {
    "assessment_code": "ASM-20260423-005",
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

**错误事件**：

```
event: error
data: {"code": "llm_unavailable", "message": "AI 暂时无法响应"}
```

#### POST /api/v1/assessment/chat/{session_code}/restart
放弃当前会话，重新开始。

**行为**：当前 session 标记为 `abandoned`，新建一个 session 并返回开场白（同 `/start` 的响应）。

### 4.2 Tool-use Schema

```python
ASK_TOOL = {
    "name": "ask_next_question",
    "description": "继续提问以收集信息。在累计 5–8 轮对话内、5 个维度尚未充分覆盖时使用。",
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "下一个问题的自然语言文本（可包含对前一答案的简短回应 + 新问题）"
            }
        },
        "required": ["content"]
    }
}

CONCLUDE_TOOL = {
    "name": "conclude_assessment",
    "description": "信息充分时输出评估结论。要求 5 个维度均有判断依据，且累计对话 ≥ 5 轮。",
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "给客户看的收尾文本"},
            "risk_preference": {"type": "string", "enum": ["C1", "C2", "C3", "C4", "C5"]},
            "summary": {"type": "string", "description": "评估依据摘要（约 100–200 字）"},
            "dimensions": {
                "type": "object",
                "properties": {
                    "experience": {"type": "integer", "minimum": 1, "maximum": 5},
                    "loss_tolerance": {"type": "integer", "minimum": 1, "maximum": 5},
                    "income_stability": {"type": "integer", "minimum": 1, "maximum": 5},
                    "investment_horizon": {"type": "integer", "minimum": 1, "maximum": 5},
                    "volatility_tolerance": {"type": "integer", "minimum": 1, "maximum": 5}
                },
                "required": ["experience", "loss_tolerance", "income_stability",
                             "investment_horizon", "volatility_tolerance"]
            }
        },
        "required": ["content", "risk_preference", "summary", "dimensions"]
    }
}
```

约束：每轮模型只能选其一；后端兜底取首个 tool_use block。

---

## 5. 对话流程

### 5.1 会话生命周期

```
[start]                               [message *N]                    [conclude]
   │                                       │                              │
   ▼                                       ▼                              ▼
chat_sessions.create  ──▶  chat_messages.insert (user + assistant)  ──▶  assessments.insert
status=active                                                            chat_sessions.status=completed
                                                                         assessments.chat_session_id FK
```

### 5.2 中断恢复

- `POST /chat/start` 时按 `customer_id + status='active'` 查询最近 1 条 session
- 命中则 `resumed=true`，返回该 session 的全部历史 `chat_messages`
- 未命中则新建 session、生成开场白
- 客户端需提供「重新开始」按钮调用 `POST /chat/{code}/restart`

**约束**：每个 customer 最多 1 条 active session；新建时若已存在 active session，新请求复用而非新建（保护数据一致性）。

### 5.3 错误重试

| 故障类型 | 后端行为 | 前端行为 |
|---|---|---|
| LLM 5xx / 超时 | 自动重试 1 次（指数退避 1s） | 失败后 SSE 推 `error` 事件，UI 显示重试按钮 |
| LLM 输出 JSON 解析失败 | 自动重试 1 次（追加 "请按格式输出" 提示到下一次请求） | 同上 |
| SSE 流中断 | — | 检测到连接断开，UI 显示"连接断开，重试"按钮 |
| 重试按钮点击 | 调用 `/chat/{code}/message` 时复用最后一条 user 消息 | — |

后端的 user 消息只在 LLM 成功响应后才写入 `chat_messages`，避免重试导致重复写入。

---

## 6. Prompt 设计

### 6.1 来源
所有 prompt 与维度定义**放配置文件**，不入库不进数据库管理 UI：

```
backend/prompts/
├── risk_assessment_system.md     # system prompt
└── risk_assessment_dimensions.yaml  # 5 个维度的描述、评分锚点
```

随代码一起版本化，调 prompt 直接改 markdown 重启服务即可。

### 6.2 system prompt 关键约束

- 角色：理财风险评估助手，专业但语气亲和
- 评估维度（5 个）的具体含义与 1–5 分锚点
- 对话节奏：每轮一个核心问题；累计 5–8 轮内完成
- 工具调用规则：每轮必选 `ask_next_question` 或 `conclude_assessment` 之一
- 禁止：编造产品推荐、给出投资建议、超出风险评估范围

### 6.3 多轮上下文传递（方案 B）

每次请求把完整 `messages` 历史拼进 prompt（不依赖 CLI `--resume`）。后端 service 层维护 messages 数组：

```python
messages = [
    {"role": "user", "content": "买过一些基金..."},
    {"role": "assistant", "content": [{"type": "tool_use", "name": "ask_next_question", "input": {...}}]},
    {"role": "user", "content": "..."},
    ...
]
```

完整 messages 每轮全量发给 SDK；prompt caching（生产 API）会缓存 system prompt 部分。

---

## 7. claude-cli-bridge

### 7.1 职责与边界

**职责**：把 Anthropic Messages API 的子集请求翻译成 Claude CLI 的非交互调用，再把 CLI 输出翻译回 Anthropic SSE 协议。

**实现的协议子集**：
- `POST /v1/messages`，仅 `stream=true` 模式
- 入参：`messages`、`system`、`tools`、`tool_choice`（仅 `auto`）、`model`、`max_tokens`
- 出参：标准 Anthropic SSE 事件流（`message_start` / `content_block_start` / `content_block_delta` / `content_block_stop` / `message_delta` / `message_stop`）

**不实现**：批处理、文件、citations、thinking、非流式响应、`tool_choice` 其他模式。

### 7.2 协议转换

**入：messages + tools → CLI prompt**
1. 把 `system` 作为 prompt 头部
2. 把 tools schema 序列化成 JSON 描述追加到 system，约束模型"必须输出符合其中一个 tool input_schema 的 JSON"
3. 把 messages 渲染成 `<role>: <content>` 文本片段
4. 拼成单个 string 传给 `claude -p --output-format json`

**出：CLI JSON 输出 → Anthropic 事件流**
1. 解析 CLI 返回的 JSON（包含 `result` 字段为模型输出文本）
2. 从模型输出中提取 JSON 段，匹配 tools 中的 schema 确定 `tool_name` 与 `input`
3. 伪造事件序列（按字符或词切块吐 `input_json_delta`，制造流式观感）
4. 通过 FastAPI `StreamingResponse` 推送 SSE

### 7.3 启动方式

集成到现有 `/dev-server` skill：

- `LLM_PROVIDER=cli`（dev 默认）：`/dev-server` 在端口 8787 拉起 bridge
- `LLM_PROVIDER=api`：跳过 bridge 启动
- 后端 `.env.dev` 默认设置 `LLM_PROVIDER=api` + `ANTHROPIC_BASE_URL=http://localhost:8787` + `ANTHROPIC_API_KEY=fake`（base URL 不带 `/v1`，SDK 会自动追加）

### 7.4 目录结构

```
tools/claude-cli-bridge/
├── pyproject.toml
├── src/
│   └── claude_cli_bridge/
│       ├── main.py              # FastAPI app
│       ├── messages.py          # /v1/messages endpoint
│       ├── cli_runner.py        # subprocess 调度 + 超时
│       ├── prompt_builder.py    # messages + tools → prompt 字符串
│       ├── tool_parser.py       # CLI 输出 → tool_use 结构
│       └── sse_emitter.py       # 伪造 Anthropic SSE 事件
└── tests/
    ├── test_prompt_builder.py
    ├── test_tool_parser.py
    └── test_messages_endpoint.py  # mock subprocess
```

---

## 8. 前端设计

### 8.1 路由结构

| 路径 | 用途 | 备注 |
|---|---|---|
| `/assessment` | **模式选择页**（新） | 两张卡片：「固定问卷」/「AI 对话评估」 |
| `/assessment/questionnaire` | 问卷页 | 现有 `/assessment` 迁移到此 |
| `/assessment/chat` | AI 对话页 | 新增 |
| `/assessment/result/:assessmentCode` | 评估结果页 | 现有，复用 |

### 8.2 SSE 消费

使用 fetch + ReadableStream 解析 SSE（避免 EventSource 不支持 POST body 的限制）：

```typescript
const resp = await fetch(`/api/v1/assessment/chat/${code}/message`, {
  method: 'POST',
  body: JSON.stringify({ content }),
  headers: { 'Content-Type': 'application/json' },
});
const reader = resp.body!.getReader();
// 解析 SSE 事件：event: <type>\ndata: <json>\n\n
```

事件分发：
- `delta` → 追加到当前 assistant 气泡的 content
- `completed` (phase=asking) → 解锁输入框、轮次 +1
- `completed` (phase=concluded) → 显示结果摘要 → 跳转 `/assessment/result/{assessment_code}`
- `error` → 显示重试按钮

### 8.3 进度展示

顶部固定栏显示「已对话 X 轮 / 预计 5–8 轮」：

- X = 当前 assistant 消息数（含开场白则减 1，与"用户回合数"对齐）
- 不做精确进度条，避免 AI 实际轮次动态变化导致跳动

### 8.4 评估完成后的展示

复用现有 `AssessmentResult` 页（Q7=A）：

- 检测 `assessment.source === 'ai_chat'`，额外渲染：
  - `ai_summary` 文本块（卡片形式）
  - `ai_dimensions` 横向条形图（5 行进度条，1–5 分映射到 0–100% 宽度）
- 问卷模式不渲染上述两个区块
- 推荐列表、风险偏好徽章、"重新评估"按钮等共用部分不变

### 8.5 评估历史展示

`/profile` 评估历史列表的每一项前加来源标签：

- `source='questionnaire'` → `[问卷]`
- `source='ai_chat'` → `[AI 对话]`

点击列表项进入同一个 `AssessmentResult` 详情页。

---

## 9. 测试策略

| 层 | 工具 | 范围 | CI |
|---|---|---|---|
| 后端业务 | pytest + 拦截 SDK HTTP | session 创建、消息落盘、状态机、错误重试、conclude 落 assessments 的事务 | ✅ |
| bridge 单测 | pytest + mock subprocess | prompt 拼装、CLI 输出解析、SSE 事件序列 | ✅ |
| 前端 E2E | Cypress + cy.intercept | 模式选择、对话渲染、流式追加、中断恢复、重试按钮、评估完成跳转 | ✅ |
| 真链路冒烟 | bash + Anthropic SDK | bridge ↔ 真实 CLI 协议契合度（仅 1 轮对话） | ❌（手动） |

### 9.1 Smoke 脚本

`scripts/smoke-ai-chat.sh`：

1. 检查 `claude` CLI 已安装且已登录、端口 8787 空闲
2. 启动 bridge
3. 用 Anthropic SDK 调 bridge 跑 1 轮对话
4. 断言：收到 `message_start` / `content_block_delta` / `message_stop`、tool_use 解析出非空 `content`
5. 杀 bridge 进程，输出结果

跑时机：bridge 改动后 + PR merge 前手动验证。

---

## 10. 实施阶段

### P1 — 后端骨架 + Mock 端到端
**范围**：
- migration：`chat_sessions`、`chat_messages`、`assessments.chat_session_id`
- 业务 service：`chat_service.py`（会话/消息 CRUD、状态机、conclude 落盘）
- SSE endpoint：`/assessment/chat/start`、`/message`、`/restart`
- LLM 调用层：用 `respx` 在测试中拦截 SDK，业务测试用脚本化响应
- pytest：覆盖创建会话、多轮对话、完成落盘、恢复未完成、重新开始、错误重试

**产物**：后端可端到端跑通，前端可对接（用 mock 响应）。

### P2 — 真实 LLM 接入
**范围**：
- 用 Anthropic SDK 实现真实 LLM 调用（业务代码视角与 P1 一致）
- system prompt + 维度定义文件
- prompt caching 配置（生产 API 时生效）
- 错误处理 / 自动重试 / 超时配置

**产物**：拿到 API key 即可生产可用。dev 环境此时仍跑 mock 或等待 P2'。

### P2' — claude-cli-bridge（与 P2 并行）
**范围**：
- 独立 FastAPI 项目 `tools/claude-cli-bridge/`
- 协议转换三件套：prompt_builder / tool_parser / sse_emitter
- 集成到 `/dev-server` skill
- bridge pytest + smoke 脚本

**产物**：dev 环境完整链路（业务 → SDK → bridge → CLI）可跑。

### P3 — 前端
**范围**：
- 路由调整：`/assessment` 改模式选择页，问卷迁 `/assessment/questionnaire`
- AI 对话页 `/assessment/chat`：消息流、SSE 消费、流式气泡、轮次计数、重试按钮、重新开始按钮
- `AssessmentResult` 页扩展：AI 模式渲染 `ai_summary` + `ai_dimensions` 条形图
- `/profile` 评估历史加来源标签
- Cypress E2E：拦截 SSE 跑完整流程

**产物**：用户视角的 AI 对话评估完整可用。

### 阶段依赖

```
P1 ──▶ P2 ──▶ 生产可用
 │
 ├──▶ P2' ──▶ dev 完整链路
 │
 └──▶ P3 ──▶ 用户可用
```

P3 可在 P1 完成后开始（基于 mock 响应开发）；P2 与 P2' 解耦推进。

---

## 11. 决策记录

| # | 议题 | 选项 | 理由 |
|---|---|---|---|
| Q1 | 消息历史存储 | **B 独立 chat_messages 表** | 支持审计、按消息分析；扩展性好 |
| Q2 | 匿名客户支持 | **A 与问卷一致支持** | 体验对称；本地 dev 不考虑速率限制 |
| Q3 | AI 输出协议（dev/CLI） | **B 纯 JSON** | CLI 无 tool-use；解析稳定 |
| Q3' | AI 输出协议（prod/API） | **tool-use** | schema 强制校验；流式友好 |
| Q4 | 流式传输 | **SSE** | 单向回合制场景够用；FastAPI 原生支持 |
| Q5 | dev 适配方式 | **claude-cli-bridge** | 业务代码统一用 SDK，单一实现 |
| Q6 | prompt 管理 | **B 配置文件** | 与代码一起版本化；调起来快 |
| Q7 | 结果页复用 | **A 复用 + 分支渲染** | 大量共用代码，AI 字段少量增量 |
| Q8 | 模式选择入口 | **A 模式选择页** | 符合 spec「客户可自选模式」 |
| Q9 | 中断恢复 | **B 自动恢复 + 重新开始按钮** | 体验明显更好，成本可控 |
| Q10 | 错误处理 | **C 自动 1 次 + 前端按钮** | 兼顾用户感知与实现成本 |
| Q11 | Migration 范围 | **B 加新表 + chat_session_id** | 一字段换可追溯能力 |
| Q12 | bridge 启动方式 | **B 集成 /dev-server** | 与现有开发流程一致 |
| Q13 | 测试策略 | **C 分层 mock + smoke** | CI 稳定 + 真链路 sanity check |
| Q14 | 进度展示 | **B 轮次计数器** | 给基本预期，零成本 |
| Q15 | 历史来源区分 | **A 标签** | 一眼可识别；详情页复用 |
