# A#1 练习：handle_user_message 三条路径时序图

> 阶段三② agent loop 的时序练习。补全下面三张 Mermaid 序列图的 `%% TODO` 处，
> 画完对着 `backend/app/services/chat_service.py` 的 `handle_user_message` 核对。
>
> 预览：VS Code 装扩展 "Markdown Preview Mermaid Support"；或把 mermaid 块贴到 https://mermaid.live 。
>
> 画的时候留意几个要点（体现对 loop 的理解）：
> - 每轮 `H->>LLM` = 一次 `_call_llm_with_retry(messages, TOOLS_SCHEMA)`；
> - search 那步用 `Note over H` 标「回喂 messages、**不落库、不吐 delta**」；
> - `H-->>R` 用 `yield` 体现「边跑边流式发事件」；delta 是逐字气泡，completed/error 是收尾；
> - 「结构化输出 ↔ agent loop」的分界线：`if is_executable_tool(...)` —— 想清楚它把 search 变成了「中间步骤」，而 ask/conclude 是「终点」。

---

## 路径一：直接 conclude（1 次 LLM，最短）

```mermaid
sequenceDiagram
    participant FE as 前端
    participant R as router(SSE)
    participant H as handle(loop)
    participant LLM as LLM(bridge)
    participant DB as DB

    FE->>R: POST /{code}/message
    R->>H: async for ev in handle_user_message(...)
    %% TODO 第1轮：H 调 LLM，LLM 返回 ToolResult(conclude)
    %% TODO：is_executable_tool(conclude)=False → 走终态分支
    %% TODO：落 user+assistant 消息、建 Assessment、session=completed（H->>DB）
    %% TODO：H 逐个 yield 事件给 R（delta？completed(concluded)？）→ R 转 SSE 给 FE
```

---

## 路径二：search → conclude（2 次 LLM）

```mermaid
sequenceDiagram
    participant FE as 前端
    participant R as router(SSE)
    participant H as handle(loop)
    participant LLM as LLM(bridge)
    participant DB as DB

    FE->>R: POST /{code}/message
    R->>H: async for ev in handle_user_message(...)
    %% TODO 第1轮：LLM 返回 ToolResult(search_products)
    %% TODO：is_executable_tool=True → _execute_tool 查 DB
    %% TODO：Note over H 标「tool_use+tool_result 回喂 messages，不落库/不吐delta」→ continue
    %% TODO 第2轮：LLM 返回 conclude（此时 messages 已含 tool_result）
    %% TODO：落盘/建 Assessment → yield delta/completed → R 转 SSE
```

---

## 路径三：一直 search → 触 MAX_AGENT_STEPS 兜底

```mermaid
sequenceDiagram
    participant FE as 前端
    participant R as router(SSE)
    participant H as handle(loop)
    participant LLM as LLM(bridge)
    participant DB as DB

    FE->>R: POST /{code}/message
    R->>H: async for ev in handle_user_message(...)
    %% TODO：loop 循环，每轮 LLM 都返回 search_products → 执行回喂 → continue
    %%   （可以用 loop N 次 的 mermaid loop 语法，或画两轮 + 省略号示意）
    %% TODO：跑满 MAX_AGENT_STEPS 都没遇到终态工具 → 循环【外】yield error(max_steps)
    %% TODO：R 把 error 转 SSE 给 FE（想想：这里为什么是 yield error 而不是 return）
```

---

## 附：mermaid 序列图常用语法速查

- 箭头：`A->>B: 实线（调用）` ／ `A-->>B: 虚线（返回/yield）`
- 备注：`Note over H: 文字` ／ `Note right of H: 文字`
- 循环：`loop 每轮` … `end`
- 可选/分支：`alt 条件` … `else` … `end`
- 自调用：`H->>H: 内部动作`（如 _execute_tool、回喂 messages）
