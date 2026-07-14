# C. 阶段三专题：把 AI 对话改造成完整 tool-use agent

> 配套 `00-roadmap.md` / `01-practice-with-finwise.md`。
> 这是一份**可执行的改造设计**，不是随手实现——按步骤走，每步都带测试（遵守 AGENTS.md 铁律）。
> 目标读者：已读过 `chat_service.py`、理解现有流程的你。

---

## 1. 先看清：现在的"工具"其实不是工具

打开 `backend/app/services/chat_service.py`，看 `TOOLS_SCHEMA` 和 `handle_user_message`。当前流程一个回合是这样的：

```
用户消息 → 模型 → 调用 ask_next_question(content) 或 conclude_assessment(...)
                       ↑ 这一步就结束了，工具的"调用"直接当作输出落盘
```

关键事实：**这两个"工具"从不被服务端执行，也不给模型返回任何结果。** 模型调用 `conclude_assessment` 不是"请服务端帮我算个结论"，而是"我要用这个结构把我的最终答案吐出来"。`anthropic_client.py` 里也印证了这点——它取到**第一个** `tool_use` 就 `return`，根本没有"把工具结果发回模型再继续"的机制。

这在 AI 工程里叫 **structured output（结构化输出）**，是 tool-calling 的一种用法，但**不是 agent loop**。

真正的 agent loop 长这样：

```
用户消息 → 模型 → 调用 search_products(risk="C4")
                       ↓ 服务端真的去查产品库
                    tool_result: [产品A, 产品B, ...]  ← 结果发回模型
                       ↓
                    模型看着真实数据继续想 → 再调 conclude_assessment(...)
                       ↓
                    没有更多工具调用 = 最终答案
```

区别一句话：**结构化输出里，工具调用是"终点"；agent loop 里，工具调用是"中间步骤"，结果要回喂给模型，直到它不再调工具。**

---

## 2. 改造目标

给评估 agent 加一个**真会被执行的工具** `search_products`：模型在下结论前，可以先查真实产品库，让 `conclude_assessment` 的推荐建立在实际数据上，而不是凭空生成。

这会强制 `handle_user_message` 从"调一次 LLM"变成"**循环调 LLM 直到它给出终态工具**"。改完你就亲手实现了一个真正的 agent loop。

**为什么选 `search_products` 而不是别的**：
- 产品库已存在（`models/product.py` + `recommendation_service.py` 的查询逻辑可复用）。
- 天然需要"模型决定查什么 → 服务端查 → 模型用结果"，是 agent loop 的最小完整案例。
- 和阶段四 RAG 练习能衔接。

---

## 3. 需要动的部件（改造地图）

| 部件 | 现状 | 改造 |
|---|---|---|
| `events.py` | `ToolResult` 表示"终态工具" | 保留；新增区分"可执行工具"的能力（见步骤 2） |
| `anthropic_client.py` | 取第一个 tool_use 就 return | 改为能吐 tool_use 事件并支持被再次调用续流 |
| `chat_service.py::TOOLS_SCHEMA` | 2 个终态工具 | +1 个可执行工具 `search_products` |
| `chat_service.py::handle_user_message` | 单次调用 | 改成 while 循环（agent loop） |
| `chat_service.py::build_api_messages` | 只转 user/assistant 文本与终态 tool_use | 需能持久化并回放 tool_use + tool_result 对 |
| `models/chat.py` | ChatMessage 有 tool_use 字段 | 可能需存 tool_result（新 role 或字段） |
| `mock.py` | 脚本化单响应 | 已支持多次 push，天然能模拟多步 |

**工具分类（改造后的心智模型）**：
- **终态工具**（terminal）：`ask_next_question`、`conclude_assessment` —— 调用即结束本回合。
- **可执行工具**（executable）：`search_products` —— 服务端执行、结果回喂、循环继续。

---

## 4. 分步实施（每步一个可测的小改动）

> 铁律：每步改 `app/**` 都要在 `tests/test_chat_service.py`（或 `test_chat_router.py`）补测试，且已有测试保持全绿。用 `MockLLMClient.push` 脚本化多步响应。

### 步骤 0：基线保护（先写测试，后动代码）
- 为现有 `handle_user_message` 的两条主路径（继续问 / 下结论）补齐/确认测试存在。
- 目的：改造是重构，先有回归网。
- **验收**：`pytest tests/test_chat_service.py` 全绿。

### 步骤 1：让 LLM 层能表达"可执行工具调用"
- 在 `events.py` 明确：`ToolResult` 现在可能是终态、也可能是待执行的工具。最简做法是**不改数据结构**，靠工具名区分（`search_products` = 可执行，其余 = 终态）——先用约定，别过度设计。
- `anthropic_client.py`：现在取第一个 tool_use 就 return，这对单步没问题；多步循环里"续流"由 `chat_service` 通过**再次调用 `stream_chat`** 完成（把 tool_result 追加进 messages 再调一次），所以 client 本身可暂不改。
- **验收**：加一个单测，mock 返回 `ToolResult(name="search_products", ...)`，断言 chat_service 能识别它不是终态。

### 步骤 2：实现工具执行器
- 新增 `chat_service._execute_tool(db, name, tool_input) -> dict`：`search_products` 复用 `recommendation_service` / 产品查询，返回精简产品列表（控制 token）。
- 纯函数式、可单测。
- **验收**：`test_chat_service.py` 加 `test_execute_search_products`，断言按风险等级返回正确产品。

### 步骤 3：把 handle_user_message 改成 agent loop
核心改动，伪代码：

```python
async def handle_user_message(db, session, user_content, llm):
    messages = build_api_messages(session) + [{"role": "user", "content": user_content}]
    MAX_STEPS = 5  # 防失控，硬上限
    for _ in range(MAX_STEPS):
        text, tool_result, llm_error, deltas = await _call_llm_with_retry(
            llm, system=load_system_prompt(), messages=messages, tools=TOOLS_SCHEMA,
        )
        # ...错误处理同现状...

        if tool_result.name in (TOOL_ASK, TOOL_CONCLUDE):
            # 终态：吐 delta、落盘、（conclude 时建 Assessment）、结束
            ...
            return

        if tool_result.name == TOOL_SEARCH:
            # 可执行：执行 → 把 tool_use + tool_result 追加进 messages → 继续循环
            result = _execute_tool(db, tool_result.name, tool_result.input)
            messages.append({"role": "assistant", "content": [{"type": "tool_use", ...}]})
            messages.append({"role": "user", "content": [{"type": "tool_result", ...}]})
            continue

    # 超过 MAX_STEPS 仍未终态 → 报错兜底
    yield {"event": "error", "data": {"code": "max_steps", "message": "agent 未能在限定步数内完成"}}
```

要点：
- **`MAX_STEPS` 硬上限**：agent loop 必须有终止保护，防止模型无限调工具烧钱。
- 中间的 `search_products` 步骤**不落 chat_messages、不吐给前端**（用户不该看到内部工具调用），只在内存 `messages` 里累积；只有终态工具的 content 才落盘 + SSE。
- **验收**：加 `test_conclude_after_search` —— mock 依次 push `[ToolResult(search_products)]`、`[ToolResult(conclude_assessment)]`，断言：① 中间不落库不吐 delta ② 最终建了 Assessment ③ `llm.calls` 有 2 次且第 2 次 messages 含 tool_result。

### 步骤 4：消息持久化与会话恢复（如需跨回合保留工具轨迹）
- 评估决定：`search_products` 只在**单个回合内**发生（结论前查一次），跨回合无需回放 → `build_api_messages` **可不改**，简单。
- 若将来要跨回合保留工具轨迹，再扩展 `models/chat.py` 存 tool_result。**本次改造建议不做**，避免 scope 膨胀。
- **验收**：会话恢复相关既有测试仍绿。

### 步骤 5：前端与 SSE 契约
- SSE 事件契约**不变**（前端仍只收 delta / completed / error）——因为中间工具步骤对用户透明。这是刻意设计：agent 内部复杂度不外溢到前端。
- 若想让用户看到"正在查询产品…"的中间态，再加一个 `event: tool_running` 事件，并补 `frontend-customer` 的 Cypress E2E。**建议作为可选增强**。
- **验收**：若动了前端 `src/**`，必须补 `frontend-customer/cypress/e2e/**`（AGENTS.md Stop hook 会强制）。

---

## 5. 测试策略汇总

| 层 | 测什么 | 怎么测 |
|---|---|---|
| `_execute_tool` | 工具执行正确性 | 纯 pytest，真实 DB fixture |
| agent loop | 多步编排、终止、tool_result 回喂 | `MockLLMClient` 多次 push + 断言 `llm.calls` |
| MAX_STEPS 兜底 | 失控保护 | mock 一直 push `search_products`，断言最终 error |
| router / SSE | 契约不变 | `test_chat_router.py` 现有断言 |
| 前端（若改） | 中间态展示 | Cypress `cy.intercept` |

**关键测试技巧**：`MockLLMClient` 已经支持 `push` 多个响应，每次 `stream_chat` 弹一个——这天然就是多步 agent 的测试利器。断言 `mock.calls[1]["messages"]` 里含 `tool_result`，就能证明"结果确实回喂给了模型"。

---

## 6. 风险与回滚

| 风险 | 对策 |
|---|---|
| 循环失控烧 token | `MAX_STEPS` 硬上限 + eval 监控平均步数 |
| 改坏现有单步流程 | 步骤 0 先建回归网；终态逻辑尽量原样保留 |
| tool_result 消息格式不对导致 API 报错 | 步骤 3 用 mock 断言 messages 结构，再接真实 API 验证 |
| scope 膨胀（跨回合持久化） | 明确本次只做单回合内循环，步骤 4/5 增强项标注"可选" |

回滚：改造集中在 `chat_service.py` 一个文件的 `handle_user_message` + 新增 `_execute_tool` + `TOOLS_SCHEMA` 加一项。保留旧函数签名，出问题可快速还原。

---

## 7. 完成标志

- [ ] `handle_user_message` 是一个带 `MAX_STEPS` 的真 while 循环。
- [ ] 存在一个服务端真实执行、结果回喂模型的工具 `search_products`。
- [ ] 有测试证明第 2 次 LLM 调用的 messages 里带着 tool_result（结果确实回喂了）。
- [ ] 你能对着自己的代码，说清"结构化输出"和"agent loop"的分界线在哪一行。

做到最后一条，阶段三就真正过关了——你不仅用过 agent，还亲手把一个结构化输出改造成了 agent loop。

---

## 8. 延伸（做完再看）

- 把 `search_products` 换成向量检索 → 直接进入**阶段四 RAG**。
- 用 Claude Agent SDK 重写这个 loop → **阶段六**，对比框架替你做了什么。
- 给这个 loop 加 eval：平均步数、结论准确率 → **阶段五**。
