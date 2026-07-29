# 04. 模型每一轮返回什么？——结合 FinWise 代码的数据结构速查

> 目标：把"模型一轮到底吐什么形状"讲清楚。全部字段对应真实代码：
> `backend/app/services/llm/anthropic_client.py`、`events.py`、`chat_service.py`。
> 读法：先看「三层结构」建立心智模型，再看「三个真实回合」把三层串起来。

---

## 一、先建立心智模型：数据流经三层，每层形状不同

一次用户消息进来，数据要穿过三层，**每层的结构不一样**，别混：

```
         ┌─────────────────────────────────────────────────────────┐
 真实 API │  Layer A：Anthropic 原始响应（SDK 给的）                  │
（或bridge)│  流式 text_delta 事件 + 结束时 final_message.content 块列表 │
         └─────────────────────────────────────────────────────────┘
                          │  anthropic_client.py 归一化
                          ▼
         ┌─────────────────────────────────────────────────────────┐
 内部事件 │  Layer B：LLMEvent（我们自己的类型）                      │
         │  TextDelta / ToolResult(name, input, id) / LLMError       │
         └─────────────────────────────────────────────────────────┘
                          │  chat_service.handle_user_message 消费
                          ▼
         ┌──────────────────────────┬──────────────────────────────┐
 对外     │ Layer C-1：回喂给模型的  │ Layer C-2：吐给前端的 SSE     │
         │ messages（tool_use /     │ delta / completed / error     │
         │ tool_result 块）         │                               │
         └──────────────────────────┴──────────────────────────────┘
```

- **Layer A**：Anthropic 的原始形状。你几乎不直接碰它，`anthropic_client.py` 帮你收敛。
- **Layer B**：我们抽象出的三个事件类型，是 chat_service 唯一要认的东西。
- **Layer C-1**：多步 loop 里，把工具调用+结果拼回 `messages` 再问模型（只可执行工具走这里）。
- **Layer C-2**：最终吐给前端的 SSE 事件（前端只认这三种）。

---

## 二、Layer A：Anthropic 原始响应

模型一轮的输出是 **一个 message，它的 `content` 是「块列表」**。块有两种类型（本项目用到）：

```jsonc
// final_message.content —— 块列表
[
  { "type": "text", "text": "让我先查一下这个等级的产品……" },   // 文本块（可能有，可能没有）
  {
    "type": "tool_use",
    "id":   "toolu_01A9f8...",        // ★ 每个工具调用的唯一 id
    "name": "search_products",
    "input": { "risk_level": "C4" }    // 已解析好的参数对象
  }
]
```

要点：
- 一轮里**可能同时有 text 块和 tool_use 块**（模型先说句话、再调工具），也可能只有其一。
- 流式阶段，text 是一段段 `text_delta` 吐出来的；tool_use 的 `input` 是 `input_json_delta` 拼的 JSON 片段。`anthropic_client.py` 用 `stream.get_final_message()` 等流结束后，直接从 `final.content` 里拿**已经拼好**的块（省得自己攒 JSON）。
- **`id` 是关键**：多步回喂时 tool_result 要用它指回去（见 [[03-agent-loop-lessons]] 第七节）。

对应代码（`anthropic_client.py`）：
```python
async for event in stream:                       # 1) 流式阶段：只捞 text_delta
    if event.type == "content_block_delta" and event.delta.type == "text_delta":
        yield TextDelta(text=event.delta.text)

final = await stream.get_final_message()         # 2) 结束后：从 final.content 取第一个 tool_use
for block in final.content:
    if block.type == "tool_use":
        yield ToolResult(name=block.name, input=dict(block.input), id=block.id)
        return                                    # 只取第一个 tool_use（本项目每轮只用一个工具）
```

---

## 三、Layer B：我们的内部事件 `LLMEvent`

`anthropic_client` 把原始流收敛成三个 dataclass（`events.py`）：

```python
@dataclass
class TextDelta:                 # 一段增量文本
    text: str

@dataclass
class ToolResult:                # 模型完成的一次工具调用（流结束时产出一次）
    name: str                    # "ask_next_question" | "conclude_assessment" | "search_products" | ...
    input: dict                  # 完整参数对象
    id: str = ""                 # tool_use 块的 id（回喂配对用）

@dataclass
class LLMError:                  # provider 明确上报的失败（不抛异常，作为事件上报）
    message: str
    code: str
```

`handle_user_message` 只需认这三种。**`ToolResult` 是核心**——它的 `name` 决定这一轮是"终态"还是"可执行"：

```python
TERMINAL_TOOLS   = {"ask_next_question", "conclude_assessment"}   # 调用即结束本回合
EXECUTABLE_TOOLS = {"search_products", "get_product_detail"}      # 执行→回喂→继续
```

---

## 四、三个真实回合，把三层串起来

### 回合 A：模型「继续提问」(ask_next_question · 终态)

**Layer A** final_message.content：
```jsonc
[{ "type": "tool_use", "id": "toolu_ask01", "name": "ask_next_question",
   "input": { "content": "您能接受多大的短期浮亏？比如 10% 还是 20%？" } }]
```
**Layer B** 事件序列：
```python
ToolResult(name="ask_next_question",
           input={"content": "您能接受多大的短期浮亏？…"},
           id="toolu_ask01")
```
**Layer C**：终态工具 → 不回喂 messages。落库 user+assistant，吐 SSE：
```python
{"event": "delta",     "data": {"content": "您能接受多大的短期浮亏？…"}}
{"event": "completed", "data": {"phase": "asking", "round": 2}}
```
> `ask` 的 `input` 只有一个 `content`（就是要问的问题文本）。前端拿到 delta 显示气泡，completed 里 `phase="asking"` 表示"还没完，继续对话"。

---

### 回合 B：模型「查产品」(search_products · 可执行，多步)

**Layer A** final_message.content：
```jsonc
[{ "type": "tool_use", "id": "toolu_search01", "name": "search_products",
   "input": { "risk_level": "C4" } }]
```
**Layer B**：
```python
ToolResult(name="search_products", input={"risk_level": "C4"}, id="toolu_search01")
```
**Layer C-1（关键：回喂 messages 后再问一次模型）**——`_execute_tool` 查库得到结果，然后把「调用 + 结果」成对追加：
```python
# 服务端执行结果（_execute_tool 返回的 dict）
result = {"risk_level": "C4",
          "products": [{"product_code": "P-R4", "name": "成长精选混合",
                        "type": "基金", "expected_return": 0.085}]}

# 追加进内存 messages（注意 id 配对！）
messages.append({"role": "assistant", "content": [
    {"type": "tool_use", "id": "toolu_search01",
     "name": "search_products", "input": {"risk_level": "C4"}}]})
messages.append({"role": "user", "content": [
    {"type": "tool_result", "tool_use_id": "toolu_search01",     # ★ 用同一个 id 指回去
     "content": '{"risk_level":"C4","products":[…]}'}]})          # 结果 JSON 字符串化
# 然后 continue → 带着这两条再调一次 LLM，模型看着真实产品继续想
```
**Layer C-2（SSE）**：可执行工具**对用户透明**——这一步**不落库、不吐任何 SSE**。前端什么都看不到，只会在最终 conclude 时收到结果。

> 这是 agent loop 的心脏：`tool_use`（模型说"查 C4"）+ `tool_result`（服务端说"查到 P-R4"）**必须靠 `id` 配对**，成对塞回 `messages`，模型下一轮才知道自己查了什么、查到了什么。

---

### 回合 C：模型「下结论」(conclude_assessment · 终态)

**Layer A** final_message.content（`input` 是本项目最复杂的结构）：
```jsonc
[{ "type": "tool_use", "id": "toolu_concl01", "name": "conclude_assessment",
   "input": {
     "content": "综合来看，您属于成长型（C4）……",
     "risk_preference": "C4",
     "summary": "客户经验丰富、可接受约 10% 波动、期限 3–5 年……",
     "dimensions": {
       "experience": 5, "loss_tolerance": 3, "income_stability": 3,
       "investment_horizon": 4, "volatility_tolerance": 3
     }
   } }]
```
**Layer B**：
```python
ToolResult(name="conclude_assessment", input={…上面那个 dict…}, id="toolu_concl01")
```
**Layer C**：终态 → 落 Assessment（注意：`risk_preference` **不采信** `input` 里的，而是用 `dimensions` 走 `calculate_risk_preference` **算出来**，见 [[03-agent-loop-lessons]] 第六节），吐 SSE：
```python
{"event": "delta",     "data": {"content": "综合来看，您属于成长型（C4）……"}}
{"event": "completed", "data": {
    "phase": "concluded", "round": 4,
    "assessment": {
        "assessment_code": "ASM-…", "source": "ai_chat",
        "risk_preference": "C4",              # ← 服务端算出来的，非模型自报
        "risk_label": "成长型",
        "ai_summary": "客户经验丰富……",
        "ai_dimensions": {"experience": 5, …}
    }}}
```
> `conclude` 的 `input` 有 4 个字段（schema 里 `required`）：`content`（给用户看的结论话术）、`risk_preference`（模型自报，**仅作校验/参考**）、`summary`（内部摘要）、`dimensions`（5 维打分，**真正用来定级的**）。

---

## 五、一张表看懂每个工具的 `input` 形状

| 工具 | 类型 | `input` 结构 | 用途 |
|---|---|---|---|
| `ask_next_question` | 终态 | `{content}` | 继续问，content=问题文本 |
| `conclude_assessment` | 终态 | `{content, risk_preference, summary, dimensions}` | 下结论；dimensions 是 5 维分 |
| `search_products` | 可执行 | `{risk_level}` | 按 C 级查产品 |
| `get_product_detail` | 可执行 | `{product_codes: [...]}` | 按代码批量查详情 |

`input` 的形状由 `TOOLS_SCHEMA` 里各工具的 `input_schema` 定义（`chat_service.py`）。模型返回的 `input` **应当**符合 schema——但"应当"是软约束，所以服务端仍要硬校验（见 [[03-agent-loop-lessons]] 第三/六节：不信值、不信结构）。

---

## 六、三个最容易搞混的点

1. **`final_message.content` 是「块列表」，不是字符串**。一轮可能有 text 块 + tool_use 块。别把它当成一个 `.text`。
2. **`tool_result` 是「我们」造的，不是模型返回的**。模型只返回 `tool_use`（它想调什么）；`tool_result`（执行结果）是**服务端**执行后自己拼回 messages 的。两者靠 `id`（`tool_use.id` ↔ `tool_result.tool_use_id`）配对。
3. **可执行工具的一轮，对前端完全隐形**。它不落库、不吐 SSE，只在内存 messages 里累积。前端永远只看到终态工具的 delta/completed。

---

## 七、流式的两层视角：为什么用户不是「逐字」看到的

一个反直觉的点：`handle_user_message` yield 的是 SSE 事件，看着像流式；但**对用户其实是「攒完再放」，不是实时逐字流**。分两层看：

| 层 | 流式吗 | 说明 |
|---|---|---|
| `stream_chat`（LLM 客户端） | ✅ 真流式 | token 到一个吐一个 `TextDelta` |
| `_call_llm_with_retry` | ❌ **缓冲** | `async for` 把整轮流**消费完、攒成 `deltas` 列表**才 return |
| `handle_user_message` → 前端 | ❌ **回放** | 等 LLM 整轮答完后，delta 才成批 yield 成 SSE |

关键代码（`_call_llm_with_retry`）：
```python
async for event in llm.stream_chat(...):     # stream_chat 确实是流式
    if isinstance(event, TextDelta):
        deltas.append(event)                  # 但这里全「攒进 list」
    elif isinstance(event, ToolResult):
        tool_result = event
return "".join(text_parts), tool_result, llm_error, deltas   # 流「全部结束」后才 return
```

**对用户的效果**：不是打字机逐字，而是"等这轮 LLM 延迟结束 → 整段几乎同时到"。SSE 的"流式"是**事后回放**。

### 为什么故意缓冲（两个真实原因）

1. **重试要靠缓冲**：`_call_llm_with_retry` 失败会**重试整轮**。若 delta 已实时吐给用户、流到一半抛异常，就没法干净重试（用户已看到半截）。缓冲 = 要么整段成功、要么重试，不留半截。
2. **可执行工具要"隐形"**：`tool_result` 是流**结束时**才拿到的（从 final_message）。只有等整轮结束、看到 `tool_result.name`，才知道这轮是"可执行(要藏)"还是"终态(要显示)"。缓冲让 loop 能**事后决定这批 delta 要不要吐**——可执行就丢弃（用户看不到"让我查一下产品…"），终态才回放。这正是「六.3 可执行工具对前端隐形」能成立的**机制**。

> 一句话：**流式在 `stream_chat` 那层是真的，但被 `_call_llm_with_retry` 有意拦下缓冲了**——牺牲实时逐字体验，换来「可重试」+「可执行工具对用户隐形」。想要真正实时逐字流，得重构成"终态轮实时透传 / 可执行轮抑制"，难点在于 `tool_use` 在流末尾才到、开头还不知道这轮是哪种。
