# L03 · MCP 协议与 Skills

> 来源：2026-10 外部面试题补课（第 3 课，对应差距清单 N4）。边学边写：每讲完一步追加一节。
> 前置：阶段三 tool use（B 系列 chat_service 的工具 schema + `_execute_tool`）、03 / 04 讲义、阶段七 R1 重试策略、L02 第 8 步（fail-closed）。

## 本课目标

能回答这类面试题：
- MCP 协议是什么？（JSON-RPC 2.0、stdio / Streamable HTTP、有状态 `Mcp-Session-Id` → 无状态）
- MCP 调用失败怎么处理？（调用前校验 → 调用时退避 / 超时 / 熔断 / 降级链 → 输出校验 → 转人工）
- MCP 的幂等性：重复调用不产生副作用
- Agent skill 过多时，怎么提高命中率？
- Function Calling 与纯 Prompt 工具调用相比，优缺点是什么？（Q33）
- LLM 的 JSON 输出格式不稳定怎么处理？（Q34）

## 步骤目录

| 步 | 内容 | 状态 |
|---|---|---|
| 1 | 为什么需要 MCP：工具集成的 N × M 问题 | ✅ |
| 2 | MCP 是什么：Host / Client / Server 三角色，Tools / Resources / Prompts 三类能力 | ✅ |
| 3 | 协议层：JSON-RPC 2.0，一次会话的生命周期 | ✅ |
| 4 | 传输层：stdio vs Streamable HTTP，有状态 vs 无状态 | ✅ |
| 5 | 动手：把 FinWise 的 `search_products` 包成 MCP server，接入 Claude Code | ✅ |
| 6 | 失败策略与幂等：校验、退避、超时、熔断、降级链 | ⬜ |
| 7 | MCP 的安全：工具描述注入、最小权限 | ⬜ |
| 8 | Skills：是什么、和 MCP / tool 的区别、skill 太多怎么提高命中率 | ⬜ |
| 9 | 穿插复习题：Q33（Function Calling vs 纯 Prompt）、Q34（JSON 不稳定的防御层级） | ⬜ |

---

## 第 1 步 · 为什么需要 MCP：工具集成的 N × M 问题

### 🔁 回顾：FinWise 里一个工具要经过三处代码（`backend/app/services/chat_service.py`）
```
① 定义 schema：TOOLS_SCHEMA 里写 search_products 的名字、描述、参数（告诉模型有这个工具）
② 写执行器：  _execute_tool(db, name, tool_input) 真正去查数据库
③ 接进 loop： 收到 tool_use → 调 _execute_tool → 结果作为 tool_result 回传（🔁 04：按 id 配对）
```
这些都是 FinWise **自己写在自己代码里**的。

> **💬 课堂问答**
>
> **🙋 问**：3 个 AI 应用（FinWise 对话、内部 Claude Code、另一团队另一框架的客服机器人）都想用 5 个工具（查产品、客户、订单、合规条款、行情）。按 FinWise 现在的做法，会出什么问题？  
>
> **🧑 我的回答**：相同的逻辑会在3个AI应用里重复  
>
> **🤖 点评**：✅ 对，而且比"重复 3 次"更糟：  
> ① **数量是乘出来的**：3 × 5 = **15 份**集成代码 = **N × M 问题**。  
> ② **连复制粘贴都做不到**：各家工具格式不同（Anthropic `input_schema`、OpenAI `function.parameters`、LangChain `@tool`），每个应用按自己格式重写。  
> ③ **改一处要改 N 处**：查询逻辑改了，3 个应用都要改，容易漏；数据库账号、权限也分散在 3 处。

### 解决：标准协议，N × M → N + M
```
没有标准：每个应用 × 每个工具单独对接            有了标准协议：
  FinWise ──┬── 产品                              FinWise ──┐            ┌── 产品 server
  Claude Code ┼── 客户       = 15 条线            Claude Code ┼── 协议 ──┼── 客户 server
  客服机器人 ──┴── 订单 ……                        客服机器人 ──┘            └── 订单 server ……
                                                  应用各实现 1 次 client + 工具各实现 1 次 server = 3 + 5 = 8
```
类比：**USB-C**（不用两两适配）；**LSP**（Language Server Protocol：编辑器 × 语言 → 都支持 LSP 就互通，**MCP 正是借鉴了 LSP**）。

### 📌 要记住的
> MCP 解决工具集成的 **N × M 问题**（重复、格式不通用、改一处改 N 处）→ **标准协议**把 N × M 变成 **N + M**：工具实现一次（server），应用实现一次（client）。

---

## 第 2 步 · MCP 是什么：三个角色、三类能力

📛 **MCP = Model Context Protocol**（模型上下文协议）：Anthropic 2024 年 11 月开源，之后被各大 AI 厂商和工具普遍支持。一个**给模型提供上下文**（工具、数据、提示模板）的**标准协议**。

### 三个角色

| 角色 | 是什么 | 例子 |
|---|---|---|
| **Host**（宿主） | 用户直接使用的 AI 应用 | Claude Code、FinWise 理财对话 |
| **Client**（客户端） | Host 里负责连接 server 的组件，**一个 client 只连一个 server** | Claude Code 里连"产品 server"的连接器 |
| **Server**（服务端） | 对外提供能力的程序 | 第 5 步要写的"FinWise 产品查询 server" |

```
┌──────── Host（Claude Code）────────┐
│  LLM                                │
│   │                                 │
│  Client A ──────────────────────────┼──▶ Server A（FinWise 产品查询）
│  Client B ──────────────────────────┼──▶ Server B（GitHub）
└─────────────────────────────────────┘
```

### Server 提供的三类能力：按"谁决定用"区分

| 能力 | 是什么 | 谁决定用 | 类比 |
|---|---|---|---|
| **Tools** | 可执行的操作或查询 | **模型** | 🔁 阶段三的 tool use |
| **Resources** | 可读取的数据（文件、文档） | **应用** | REST 的 GET，只读 |
| **Prompts** | 预先写好的提示模板 | **用户** | 输入框里的 `/` 斜杠命令 |

> **💬 课堂问答**
>
> **🙋 问**：(a) 按风险等级和关键词查产品 (b) 每个产品的完整说明书（应用打开某产品时放进上下文） (c) "生成风险评估报告"模板（用户选它才触发），分别做成 Tools / Resources / Prompts？  
>
> **🧑 我的回答**：(a) Tools，(b) Resources，(c) Prompts  
>
> **🤖 点评**：✅ 全对，依据正是"谁决定用"。  
> ➕ 边界没那么绝对：**Tools 支持最普遍**，Resources / Prompts 各客户端支持不一 → 很多 server 把 (b) 也做成工具 `get_product_doc(code)`，让模型按需取。做成哪类，看你希望谁来决定什么时候读。  
> ➕ 反方向（client 提供给 server）也有能力，知道名字即可：**Sampling**（server 请 Host 的 LLM 帮它生成）、**Elicitation**（server 请 Host 向用户追问）。  
> ⚠️ 更正（第 5 步实测后补）：**2026-07-28 版协议已把 Sampling（以及 Roots、Logging）标记为弃用**（SEP-2577，弃用功能至少再保留 12 个月），这些反向能力正在调整。

### 追问：MCP 是不是在被 Skill 取代？

> **❓ 我的追问**：我听说现在 MCP 的流行程度有所下降，因为大部分时候可以被 skill 取代，是这样吗？  

**有依据，但"取代"太绝对。**

为什么有"退潮"的说法：
1. **上下文开销大**：多数 MCP 客户端一连上就把**所有工具定义**塞进上下文，server 一多光工具描述就几万 token。Anthropic 2025-11 的工程文章 "Code execution with MCP" 也承认这一点（一个例子里改成按需读取工具定义后 15 万 → 2000 token，但只是特定任务）。🔁 L01：context 越长越贵、越容易 lost in the middle。
2. **能跑命令的 agent 不太需要**：Claude Code 这类 agent 可直接调 `gh`、`git`、`curl`；很多 MCP server 只是给 CLI / API 包了一层 → **Skill（写清怎么用 CLI）+ CLI** 常更省更灵活。有博客称"CLI + Skill 已成主流"，但证据主要是个人经验，**没有采用率数据**。

为什么"取代"不准确：
1. **解决的是不同层面**：Skill 提供**知识和流程**（"怎么做"）；MCP 提供**连接和能力**（"能访问哪些系统"）。常见是**组合**：用 Skill 教 agent 用好某几个 MCP 工具。
2. **Skill + CLI 做不了的场景**：agent **没有 shell**（如 FinWise 网页聊天）；**远程服务、鉴权、多租户**（OAuth、权限、审计集中在 server 处理）；**跨厂商标准**（OpenAI、Google、微软都支持；2026-06 企业统一授权扩展进入稳定版，说明还在走向成熟）。

结论：开发者 + 能跑命令的 agent 圈子里，部分场景确实转向 Skill + CLI；应用连企业系统的圈子里，MCP 仍是标准做法。多数对比文章认为**两者互补**。

来源：[CLI + Skill Wins](https://www.heyuan110.com/posts/ai/2026-07-04-cli-skills-vs-mcp/)、[Atlan: Agent Skills vs MCP](https://atlan.com/know/ai-agent/ai-agent-skills/agent-skills-vs-mcp/)、[Velt 对比指南](https://velt.dev/blog/agent-skills-vs-mcp-comparison-guide)、[Anthropic: Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)、[AIMultiple 复测](https://research.aimultiple.com/code-execution-with-mcp)

### 追问：怎么"按需加载工具定义"

> **❓ 我的追问**：你说的"用第 2 步提到的'按需加载工具定义'的办法"，怎么改？（5a 时问）  

**主要不是改 server，而是改 Host**：

1. **工具搜索**：Host 不把所有工具完整定义放进上下文，只给模型一个**元工具**（如 `tool_search`）；模型要某能力时先搜，Host 再加载搜到的那几个的完整定义。
   ```
   平时上下文：tool_search（一个）+ 其余工具只有名字
   模型："我要查产品" → tool_search("产品 查询") → Host 加载 search_products 的定义 → 正常调用
   ```
   **本会话就是例子**：`WebSearch`、`TaskStop` 一开始只有名字，我先调 `ToolSearch` 加载定义才能用——Claude Code 的 **deferred tools**（延迟加载工具）。Anthropic API 也提供类似能力（工具标记为延迟加载，交给工具搜索按需加载）。
2. **代码执行**（Anthropic "Code execution with MCP"）：工具变成沙箱里的**代码文件**（如 `./servers/finwise/search_products.py`）；模型列目录 → 只读需要的文件 → 写代码调用并在代码里处理结果。**中间结果也不进上下文**（1000 个产品先在代码里筛成 5 个）——15 万 → 2000 token 主要靠这点。代价：需要安全的代码沙箱。
3. **server 端从设计上减少工具**：

| 做法 | 说明 |
|---|---|
| 按业务领域拆 server、按需连接 | 理财对话 agent 只连产品 server。🔁 concepts-basics"路由器"模式 |
| 合并相似工具 | 一个工具带几个可选参数，而不是 `search_by_risk` / `by_type` / `by_keyword` 三个 |
| 描述精简、细节另取 | 描述一两句，详细用法需要时再查 |

**对我们的 server**：代码不用改。但**工具搜索靠名字和描述匹配** → 工具名**见名知义**（`search_products` 好过 `query_v2`），描述**第一句关键词齐全**（很多搜索 / 摘要只看开头）。🔁 和 L01 检索同一个问题：从一堆工具里找最相关的几个，工具描述 ≈ chunk。

### 📌 要记住的
> MCP **三个角色**：Host（用户用的 AI 应用）、Client（Host 里连 server 的组件，一对一）、Server（提供能力）。**三类能力**按"谁决定用"：**Tools 模型控制、Resources 应用控制、Prompts 用户控制**。
> **MCP 和 Skill 不是取代关系**：Skill =「怎么做」（按需加载、省 token），MCP =「能连什么」（远程系统、鉴权、权限、审计）。MCP 已知痛点：**工具定义一次性全进上下文，token 开销大** → 靠 Host 端**按需加载**（工具搜索 / 代码执行）+ server 端少而精的工具设计；server 作者要让**名字见名知义、描述首句关键词齐全**。

---

## 第 3 步 · 协议层：JSON-RPC 2.0，一次会话的生命周期

📛 **RPC = Remote Procedure Call**（远程过程调用）：像调本地函数一样调另一个程序里的函数。**JSON-RPC 2.0** = 用 JSON 写调用消息的轻量规范，只规定三种消息：

| 消息 | 带 `id` | 要回复 | 例子 |
|---|---|---|---|
| **Request** | ✅ | ✅ 必须回 Response | "调一下 search_products" |
| **Response** | ✅ 与请求同 id | — | 带 `result`（成功）或 `error`（失败），二选一 |
| **Notification** | ❌ | ❌ | "我初始化好了" |

🔁 `id` 配对：和 04 讲义 `tool_use` / `tool_result` 按 id 配对一样，同时发多个请求也不乱。

```jsonc
// Client → Server：Request
{"jsonrpc": "2.0", "id": 2, "method": "tools/call",
 "params": {"name": "search_products", "arguments": {"risk_level": "C2", "keyword": "养老"}}}
// Server → Client：Response（id 同为 2）
{"jsonrpc": "2.0", "id": 2,
 "result": {"content": [{"type": "text", "text": "[{\"code\": \"P-PENSION\", ...}]"}], "isError": false}}
```

### 生命周期

> ⚠️ **更正（第 5 步实测后补）**：下面这张图是 **2025-11-25 及以前版本**（"握手时代"）的生命周期。**2026-07-28 版协议改成了无状态**：**取消了 `initialize` 握手**，协议版本、客户端信息、能力改为**每个请求都在 `params._meta` 里自带**；新增可选的 `server/discover`（server 必须实现，client 可调可不调）。见本节末尾的真实抓包。新版 SDK（`mcp` 2.x）的 server **两种都支持**，老客户端发 `initialize` 也能用。

**握手时代（≤ 2025-11-25）：**
```
Client                                  Server
  │── initialize（请求）────────────────▶│   交换协议版本、各自支持的能力
  │◀───────────────────── 响应 ───────────│
  │── notifications/initialized（通知）─▶│   "我准备好了"，不回复
  │── tools/list（请求）────────────────▶│   "你有哪些工具？"
  │◀────── 响应：工具名、描述、参数 schema │
  │── tools/call（请求）────────────────▶│   "调用 search_products，参数……"
  │◀────────────────── 响应：结果 ────────│
  │      ……（可多次 tools/call）……        │
  │── 关闭连接 ──────────────────────────▶│
```

**无状态时代（2026-07-28）**：第 5 步用 `mcp` 2.3.0 的官方 client 连一个小 server，中间插了个转发代理，**抓到的原始消息**（节选）：
```jsonc
C→S {"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{
       "io.modelcontextprotocol/protocolVersion":"2026-07-28",
       "io.modelcontextprotocol/clientInfo":{"name":"mcp","version":"0.1.0"},
       "io.modelcontextprotocol/clientCapabilities":{}}}}
S→C {"jsonrpc":"2.0","id":1,"result":{"supportedVersions":["2026-07-28"],"capabilities":{"tools":{"listChanged":true},...}}}
C→S {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{"_meta":{ …同样三项… }}}
C→S {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"add","arguments":{"a":2,"b":3},"_meta":{ …同样三项… }}}
S→C {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"5"}],"structuredContent":{"result":5},"isError":false}}
```
- **没有 `initialize`**；每个请求的 `_meta` 都带着版本、客户端信息、能力 → **每个请求自己就是完整的**，server 不需要记住"这个客户端之前握过手"。
- 🔁 和第 4 步的"无状态"直接相关：协议层把状态拿掉了，任何一台机器都能处理任何一个请求。

> **❓ 我的追问**：你说"新版 SDK 的 server 两种协议都支持，老客户端发 initialize 也能连"，是哪两种协议？  

用词更正：**不是两种协议，是同一个 MCP 协议的两个版本**（都基于 JSON-RPC 2.0，都能跑在 stdio 或 HTTP 上），区别在**连接怎么建立**：

| | 2025-11-25 版（握手版） | 2026-07-28 版（无状态版） |
|---|---|---|
| 第一条消息 | `initialize` 协商版本和能力 | 直接发业务请求（可选先 `server/discover`） |
| 之后的请求 | 发 `notifications/initialized` 后，请求**不再带**版本信息，server 要**记住**协商结果 | **每个请求**在 `_meta` 自带版本、客户端信息、能力，server **什么都不用记** |
| Session | HTTP 下用 `Mcp-Session-Id` | 没有 |

- **server 怎么判断**：第一条是 `initialize` → 走老版本（响应回 `"protocolVersion": "2025-11-25"`）；请求 `_meta` 带 `2026-07-28` → 走新版本。`raw_jsonrpc_demo.py` 的 A / B 两段就是各连一次。
- **为什么同时支持**：客户端不可能同一天一起升级（Claude Code、IDE 插件、别的团队的客户端），server 兼容两版就不会把老客户端挡在门外。🔁 L02 第 6 步换 embedding 时"新旧并行、逐步切换"同一思路。

🔁 对照 FinWise：`tools/list` 返回的描述 ↔ `TOOLS_SCHEMA`；`tools/call` ↔ `_execute_tool(db, name, tool_input)`；`result` ↔ `tool_result` 内容。区别只是：FinWise 三样都在**同一进程**，MCP 把执行器搬到**另一个程序**，中间用 JSON-RPC 沟通。

> **💬 课堂问答**
>
> **🙋 问**：Claude Code 里模型决定查产品，MCP server 收到一条 `tools/call`。这条 JSON-RPC 是 LLM 自己生成、自己发出的吗？不是的话是谁？  
>
> **🧑 我的回答**：不是，是 Host（也就是那个agent程序本身）发出去的，类似于模型返回的tool_use后，程序自己要去调那个"tool"对应的函数，然后再把结果回喂给LLM  
>
> **🤖 点评**：✅ 对。更准确是 **Host 里的 MCP Client** 发的（下图）。  
> ➕ 推论：**LLM 根本不知道 MCP 存在**——在模型看来 MCP 工具和本地 `_execute_tool` 没区别 → **MCP 与模型无关**（任何支持 function calling 的 LLM 都能用，所以各厂商都能支持）。  
> ➕ **路由靠工具名**：Claude Code 把 MCP 工具命名成 `mcp__<server名>__<工具名>`，按前缀交给对应 Client（第 5 步能看到）。

```
① LLM 输出 tool_use：{"name": "search_products", "input": {...}}   ← 模型只会输出这个
② Host 查表：这个工具属于哪个 server → 交给对应 Client
③ Client 包装成 JSON-RPC：{"method": "tools/call", ...} → 发给 server
④ server 执行，返回 result
⑤ Host 把 result 包装成 tool_result 回喂 LLM                      ← 🔁 和 FinWise agent loop 一样
```

### 📌 要记住的
> JSON-RPC 2.0 三种消息：**Request**（带 id、要回）、**Response**（同 id，result 或 error）、**Notification**（无 id、不回）。生命周期：老版本 `initialize` → `initialized` → `tools/list` → `tools/call`；**2026-07-28 版取消握手**，每个请求在 `_meta` 自带版本、客户端信息、能力，可选 `server/discover`。
> **LLM 只输出 `tool_use`，不会说 JSON-RPC**；Host 里的 MCP Client 负责翻译和回喂 → **MCP 与模型无关**。

---

## 第 4 步 · 传输层：stdio vs Streamable HTTP，有状态 vs 无状态

第 3 步是"消息长什么样"，这步是"消息怎么传过去"：

| | **stdio** | **Streamable HTTP** |
|---|---|---|
| 📛 名字 | **st**andar**d** **i**nput/**o**utput（标准输入输出） | 可流式的 HTTP |
| 怎么运行 | Host **把 server 当子进程启动**，写它的 stdin、读它的 stdout，一行一条 JSON | server 是**独立 HTTP 服务**，client POST 到一个地址（如 `/mcp`）；响应可以是普通 JSON 或 SSE 流（长任务、进度） |
| 在哪 | **只能本机** | 可**远程** |
| 服务几个客户端 | 只服务启动它的**一个** Host | **多个** |
| 权限 | 继承**启动它的用户**的权限 | 自己做鉴权（如 OAuth） |
| 适合 | 本地工具（读本地文件、调本机命令） | 公司共享服务 |

🔁 SSE：阶段一流式输出、FinWise 对话气泡都用它。
⚠️ **stdio 的坑**：stdout 是**协议专用通道**，server 里随手 `print("开始查询")` 会混进 JSON-RPC 导致 client 解析报错 → **日志必须写 stderr**（第 5 步注意）。
> ⚠️ **更正（5d 之后查进程时发现）**：**mcp 2.x 的 SDK 已经替你挡住了这个坑**——启动时先把真正的 stdin / stdout 复制到编号更大的**私有文件描述符**（协议只走它们），再把 0 号换成 `/dev/null`、1 号换成和 stderr 一样的输出 → 随手 `print()` 会被导到 stderr，误读 stdin 只会读到空。"print 搞坏协议"是协议本身的规则，在旧版 SDK 或手写 server 里仍会发生；"日志写 stderr"的习惯照样要保持（不能指望每个 SDK、每种语言都做了这层保护）。见第 5 步"5d 之后的追问"。

### 有状态 vs 无状态
Streamable HTTP 下 server 可在 `initialize` 响应里返回 **`Mcp-Session-Id`** 头，之后每次请求带上它：
- **有状态**：server 用 session id 记住"这个客户端是谁、协商过哪些能力、做过什么"。
- **无状态**：server 不记，每个请求独立、自带全部信息。
- 面试原题"有状态 mcp-session-id → 无状态"= **尽量做成无状态**的趋势。
- ⚠️ **更正（第 5 步实测后补）**：这不只是"趋势"——**2026-07-28 版协议已经在协议层取消了 `initialize` 握手和 `Mcp-Session-Id` 头**，协议本身就是无状态的（第 3 步抓包）。上面"有状态"的描述适用于 2025-11-25 及以前的版本。**应用层**仍可以有自己的状态（比如购物车），但要自己管理（存数据库 / Redis），不再靠协议的 session。

> **💬 课堂问答**
>
> **🙋 问**：产品查询做成共享 MCP server 给 3 个应用用，部署 3 台机器 + 负载均衡（随机分配）。① stdio 还是 Streamable HTTP？② 做成有状态（session 只存在处理 initialize 那台的内存里）会怎样？  
>
> **🧑 我的回答**：Streamable HTTP且是无状态设计；有状态的话另一台机器找不到 session  
>
> **🤖 点评**：✅ 都对。  
> ➕ 确实需要有状态时的补救（都有代价，下表）。  
> ➕ `search_products` **天生适合无状态**：🔁 `_execute_tool` 注释"纯查询、无副作用"，每次只依赖传入参数。  
> ➕ 🔁 Web 类比：服务端 session vs **JWT**——FinWise 登录用 `python-jose` 的 JWT，用户信息随请求带来，任何一台都能验证。

| 补救 | 怎么做 | 代价 |
|---|---|---|
| 粘性会话（sticky session） | 负载均衡按 session id 固定分到同一台 | 负载可能不均；那台挂了 session 全丢 |
| 共享存储 | session 存 Redis 等公共存储 | 多一个依赖，每次请求多一次读写 |

### 📌 要记住的
> **stdio** = 本机子进程、标准输入输出、只服务一个 Host、继承用户权限、**日志只能写 stderr**；**Streamable HTTP** = 独立远程服务、多客户端、要鉴权。多机部署的共享服务**尽量无状态**，否则 `Mcp-Session-Id` 只在某台内存里，换一台就找不到（补救：粘性会话 / 共享存储，都有代价）。**2026-07-28 版协议已在协议层取消握手和 `Mcp-Session-Id`**，应用层状态要自己存。

---

## 第 5 步 · 动手：把 `search_products` 包成 MCP server，接入 Claude Code

**关键设计：不重写查询逻辑**，server 直接调 `chat_service._execute_tool` → FinWise 对话和 Claude Code 用**同一份代码**（第 1 步"工具只实现一次"）。

| 小步 | 内容 | 谁写 |
|---|---|---|
| 5a | 工具的**描述**和**参数说明**（🔁 05 schema 即 prompt） | 用户 |
| 5b | 工具函数体：开 session → 调 `_execute_tool` → 关 session；日志写 stderr | 用户 |
| 5c | `raw_jsonrpc_demo.py`：不用客户端库，亲手发 JSON-RPC（无状态版 + 握手版） | 我搭，用户运行看懂 |
| 5d | 接入 Claude Code，真实调用一次 | 一起 |

环境：隔离的 `mcp-lab/`（同 `langgraph-lab/`），`mcp` 2.3.0 + 后端查询依赖（不装 torch）；只读开发库 `backend/finwise.db`；Claude Code 用 **local** 范围注册。

### 注册范围：正式项目怎么做

> **❓ 我的追问**：关于"在 Claude Code 里注册这个 server"，一般正式的项目会怎么做？注册完之后，有办法不重启 claude code 吗？比如热加载什么的方式  

`claude mcp add --scope ...`（默认 local）：

| 范围 | 存在哪 | 谁能用 | 正式项目里放 |
|---|---|---|---|
| **project** | 仓库根 `.mcp.json`，**提交进 git** | 拉仓库的所有人 | **团队共用**的 server |
| **local** | 本机用户配置，按项目区分 | 只有你、只在这个项目 | 个人用 / 带个人凭证的 |
| **user** | 本机用户配置 | 只有你、所有项目 | 到处都想用的个人工具 |

- `.mcp.json` 会提交 → **密钥写成环境变量引用**，每人本机设真实值：
  ```json
  {"mcpServers": {"finwise": {
      "command": "mcp-lab/.venv/bin/python",
      "args": ["mcp-lab/finwise_mcp_server.py"],
      "env": {"FINWISE_DATABASE_URL": "${FINWISE_DATABASE_URL}"}}}}
  ```
- 别人**首次**拉到 `.mcp.json` 要**先确认**：未批准的显示"⏸ Pending approval"、**不自动连接**。原因：stdio server = 在你机器上执行一条命令，配置文件不能让别人电脑自动跑程序（第 7 步安全）。
- 公司级共享服务 → **远程 HTTP server**（🔁 第 4 步 Streamable HTTP + 无状态），`--transport http` 连接、`claude mcp login` 走 OAuth，server 统一做权限和审计；有的公司由管理员统一下发允许的 server。

### 能不能不重启

| 情况 | 要重启吗 | 怎么做 |
|---|---|---|
| **新加一个 server** | **目前要** | 运行中的 Claude Code 不读会话中途新加的配置（GitHub 上有 `/mcp reload` 的需求，说明还没内置） |
| **已有 server 改了代码** | 不用 | 会话里 `/mcp` → 选中该 server **重连**；stdio 重连 = 重启子进程 → 新代码生效（实际就是热加载） |
| server 的**工具列表变了** | 不用 | 协议层：server 发 `notifications/tools/list_changed`（🔁 第 3 步 Notification），client 重新 `tools/list` |

- **重启不丢对话**：`claude --continue`（`claude -c`）接着上次对话；`claude --resume` 从列表选。
- 流程：注册 → 退出 → `claude -c` 回来 → 测试；之后改代码只需 `/mcp` 重连。5a~5c 不经过 Claude Code，不受影响。

来源：[Claude Code MCP 文档](https://code.claude.com/docs/en/mcp)、[GitHub issue（/mcp reload 需求）](https://github.com/anthropics/claude-code/issues/36308)、[第三方文档镜像](https://www.mintlify.com/jackdog668/claude-code/integrations/mcp-servers)

### 搭环境时踩的坑（我搭骨架时遇到的，值得记）

| 坑 | 现象 | 原因 / 解决 |
|---|---|---|
| **SDK 大版本变了** | `from mcp.server.fastmcp import FastMCP` 报错 | `mcp` 2.x 把 `FastMCP` 改名为 `MCPServer`（`from mcp.server.mcpserver import MCPServer`）。网上 1.x 教程不能直接抄 → **先看装的是哪个版本、读它的源码 / 报错信息** |
| **协议版本变了** | 官方 client 抓包里没有 `initialize` | 2026-07-28 版改成无状态（第 3、4 步已更正） |
| **环境变量名带前缀** | 查询报 `no such table: products` | FinWise 配置 `env_prefix="FINWISE_"`，变量应是 `FINWISE_DATABASE_URL`；写成 `DATABASE_URL` 被忽略 → 默认相对路径 `./finwise.db` → **SQLite 在当前目录悄悄新建了一个空库**。SQLite"文件不存在就新建"的特性会把配置错误伪装成"表不存在" |
| **dict 返回值没有 structuredContent** | 测试取 `structured_content` 得到 None | 返回普通 `dict`（没有声明结构）时，SDK 只把它序列化成 JSON **文本**放进 `content`——这也正是模型看到的 tool_result |

### 读骨架时的追问

> **❓ 我的追问**：第 66 行 `@mcp.tool` 这个是从哪里 import 进来的？  
> → **不是 import 的**，是文件里自己创建的变量：`mcp = MCPServer("finwise", ...)`。容易看混是因为 `mcp` 也是 SDK 包名；但 `from mcp.server.mcpserver import MCPServer` 只把 `MCPServer` 带进当前文件，**不绑定包名 `mcp`**。→ 已**改名为 `server`**。`@` 是装饰器（🔁 FastAPI `@router.get(...)` 同理：把函数登记到路由表 / 工具表），见 python-syntax-notes「装饰器」。

> **❓ 我的追问**：`mcp.server.mcpserver` 是哪个 Python 包？  
> → 官方 Python SDK，PyPI 包名 `mcp`（2.3.0）。点号路径 = 目录层级：`site-packages/mcp/server/mcpserver/`。`mcp.server.lowlevel` 是底层 API（自己处理每种请求），`MCPServer` 是高层封装（装饰器 + 函数签名自动生成，🔁 L01"框架是手写 loop 的封装"）。1.x 叫 `FastMCP`。见 python-syntax-notes「包 / 模块路径」。

> **❓ 我的追问**：你直接 `pip install mcp` 后提交的代码，别人拉下来怎么知道要装这个包？  
> → 加了 `mcp-lab/requirements.txt`（**版本钉死**，因为 mcp 1.x → 2.x 就有不兼容改动）；顺带给 `langgraph-lab` 补了 `requirements.txt`，给 backend `pyproject.toml` 补了 `scratch` 可选组并修好打包配置。追问"为什么一个用 requirements.txt 一个用 pyproject.toml"见 python-syntax-notes「依赖管理」。

### 5a · 工具描述和参数说明 ✅

用户写的描述包含四要素：**做什么**（第一句）/ **什么时候用、什么时候不该用**（负面边界，🔁 05"工具在 schema ≠ 模型会用"）/ **C1~C5 不是 R1~R5**（描述和参数说明各写一次，🔁 03 C→R 映射）/ **返回什么、空了怎么办**（"如实告知暂无合适产品，不要编造"——🔁 L02 降低幻觉第二层"允许拒答"写进了工具描述）。
- 取舍：约 400 字。工具描述连接时**全进上下文**（第 2 步），一个工具没问题，50 个就要权衡精简或按需加载。
- 小细节："按产品代码查详情"指 `get_product_detail`，但本 server 没提供——模型可能去找一个不存在的工具。

### 5b · 工具函数体 ✅
```python
db = SESSION_FACTORY()
try:
    result = _execute_tool(db, "search_products", {"risk_level": risk_level})
    log.info("search_products risk_level=%s -> %d 个在售产品",
             risk_level, len(result.get("products", [])))
    return result
finally:
    db.close()
```
- `try / finally`：🔁 `app/database.py` 的 `get_db()` 同样写法；server 是长期运行进程，不关 session 会泄漏连接。
- 日志记了**结果数量**（🔁 L02 过程指标：可统计空结果比例）；用 `%s` 占位符而非 f-string（日志真正输出时才拼接）。
- 失败时没记日志——SDK 会接住异常并记录（见下"isError 怎么加的"）。

### 5c · 亲手发 JSON-RPC（`raw_jsonrpc_demo.py`）✅

脚本手动模拟 Host：`Popen` 启动 server 子进程 → 往它 stdin 写一行 JSON → 从它 stdout 读一行 → 检查 id 一致 → 通知不读回复；A 段（2026-07-28）和 B 段（2025-11-25）各用一个新子进程。为便于阅读，回复截到前 600 字符。

```
stderr（server 日志）：
[finwise-mcp] search_products risk_level=C3 -> 3 个在售产品
[finwise-mcp] Tool 'search_products' rejected arguments: ['risk_level']
[finwise-mcp] search_products risk_level=C2 -> 3 个在售产品

A. 2026-07-28：server/discover → tools/list（返回的 description 就是 5a 写的原文）
              → tools/call C3（查出 BROWSE-001 平衡混合A 等 3 个）→ tools/call R3（isError: true）
B. 2025-11-25：initialize（回 "protocolVersion": "2025-11-25"）→ notifications/initialized（不等回复）
              → tools/call C2（不带 _meta，照样查出 REC-001 稳健货币A 等）
```
- 两版对比：A **每条**都带 `_meta`；B 只在 `initialize` 交代一次。
- 顺带发现：`expected_return` 单位不一致（`4.3167` 像百分数，`0.075` 像小数）→ 按收益排序时"平衡配置C"（实际 7.5%）排最后。开发库种子数据问题，记一笔。

> **❓ 我的追问**：能让我看下你跑演示的具体过程和结果吗？  
> → 命令：`cd mcp-lab && .venv/bin/python raw_jsonrpc_demo.py`（stdout = 协议消息，stderr = 日志）。自己跑：输入框里 `! cd mcp-lab && .venv/bin/python raw_jsonrpc_demo.py`。

> **❓ 我的追问**：search_products 最终 return 的 result，是在 stdin 里被 raw_jsonrpc_demo.py 读到的吗？它返回的是个 dict，怎么转成 text 的？  

方向更正：demo 是从 **server 的 stdout** 读的（不是 stdin）——两根管道：
```
raw_jsonrpc_demo.py（扮演 Host）                    finwise_mcp_server.py（子进程）
   proc.stdin.write(请求)  ──── 管道 1 ────▶  server 的 stdin：读请求
   proc.stdout.readline()  ◀─── 管道 2 ─────  server 的 stdout：写响应
                                              server 的 stderr ──▶ 终端（日志）
```
dict → text 五步（SDK 源码位置）：
```
① 你的函数返回 dict
② func_metadata.py 第 653 行：pydantic_core.to_json(result, fallback=str, indent=2).decode() → JSON 字符串
③ 包成 TextContent → CallToolResult(content=[...], isError=False)
④ stdio.py 第 203~204 行：整条 JSON-RPC 消息 model_dump_json() 成【一行】，write(json + "\n") 到 stdout
⑤ demo：json.loads(proc.stdout.readline())
```
- **两层 JSON**：外层是协议消息；内层是放在 `text` 字段里的**字符串** → 引号转义成 `\"`、换行写成 `\n`，整条消息才能保持一行（🔁 stdio 一行一条）。
- 为什么转 text：Host 把 result 包成 tool_result 回喂模型，**模型读文字**。返回类型声明了结构（Pydantic 模型 / TypedDict）时会**额外**有 `structuredContent` 给程序用。

> **💬 课堂问答**
>
> **🙋 问**：请求 4 传了错误的 `R3`，server 回的是 `result` + `isError: true`，而不是 JSON-RPC 的 `error` 字段。为什么这样设计？  
>
> **🧑 我的回答**：这代表了参数校验失败，逻辑错，而不是json-rpc本身执行失败。  
>
> **🤖 点评**：✅ 区分对了：**协议错误**（JSON 坏了、方法不存在）→ `error`；**工具执行错误**（参数不对、查询失败）→ `result` + `isError`。  
> ➕ 更关键的"为什么"：result 会作为 tool_result **回喂模型**，模型读到"Input should be 'C1'…'C5'"就能**自我纠正**改成 C3 重试。🔁 LangGraph `handle_tool_errors`（错误当观察喂回模型）、03"工具异常返回结构化结果别抛"。用 `error` 的话 Host 通常当成调用本身失败，模型看不到原因。

> **❓ 我的追问**：这个 `isError: true` 是怎么被加进去的？  

`mcp/server/mcpserver/server.py` 的 `_handle_call_tool`：
```python
try:
    return await self.call_tool(params.name, params.arguments or {}, context)  # 调你的函数
except MCPError:
    raise                     # 协议错误 → JSON-RPC error 字段
except Exception as exc:      # 其他异常都在这里接住
    return CallToolResult(content=[TextContent(type="text", text=str(exc))], is_error=True)
```
→ **你的函数里不用写 isError**，抛异常即可（`is_error` 序列化成驼峰 `isError`）。请求 4 路径：`tools/base.py` 按 `Literal` 校验 → pydantic `ValidationError` → 包成 `ToolError` → `_handle_call_tool` 接住、记日志"rejected arguments" → `is_error=True`；**函数体根本没执行**。

SDK 对异常的三种处理（值得学的设计）：

| 异常 | 情况 | 模型看到 | 服务端日志 |
|---|---|---|---|
| `ToolError` | **预料之中**：参数校验失败、你主动 `raise ToolError("…")` | **完整错误信息**（方便纠正） | INFO，无堆栈 |
| 其他异常（包成 `UnexpectedToolError`） | **意外崩溃**：数据库连不上 | 只有 `Error executing tool search_products`，**不含原始内容** | ERROR，**完整堆栈** |
| `MCPError` | 协议层错误 | JSON-RPC `error` | — |

- 搭环境时连错库的那次：client 只看到笼统一句，"no such table"只在服务端 stderr。🔁 阶段七 **S3 错误不外泄**——SDK 已内置。
- → 想让模型知道原因的错误，要**主动 `raise ToolError(...)`**（第 6 步失败策略会用到）。

> **❓ 我的追问**：tools/base.py 做了参数校验，怎么被调到的？search_products 只调了 chat_service 的 _execute_tool。  
> → **不是你的函数调校验，是 SDK 先校验再调你的函数**（你在调用链最末端）：
```
stdin 进来 → 分发 tools/call → server.py _handle_call_tool → call_tool
→ tool_manager.py call_tool（按名字找工具）→ tools/base.py run：① validate_arguments
→ func_metadata.py call_fn：② 校验通过才调用 → 你的 search_products → _execute_tool
```
- 校验模型在 `@server.tool(...)` **装饰那一刻**按函数签名（`Literal["C1"…"C5"]`）生成，和工具一起登记。
- 📛 **控制反转**（Inversion of Control，"Don't call us, we'll call you"）：你写普通函数，框架决定何时、用什么参数调用，并负责校验、异常、序列化。🔁 FastAPI 请求体不合法时在调用你的函数**之前**返回 422。
- 同步函数（`def`）被 SDK 用 `anyio.to_thread.run_sync` 放到线程执行，阻塞的数据库查询不卡住 server。

> **❓ 我的追问**：为什么 finwise_mcp_server 可以直接 import backend 里的 app.services.chat_service？  
> → 文件开头 `sys.path.insert(0, BACKEND_DIR)`：Python 按 `sys.path` 顺序找模块，默认只有脚本目录、标准库、venv site-packages，插入 `backend/` 后才找得到 `app/`；`chat_service` 依赖的 sqlalchemy 等装在 mcp-lab venv（requirements.txt）。🔁 `backend/scratch/_bridge.py` 同样写法。  
> 两个问题（**决定：先保持现状**）：① 改 `sys.path` 是权宜之计 → 规范做法 `mcp-lab/.venv/bin/pip install -e ../backend`（刚修好打包配置才可行；代价是装进 backend 全部依赖）。② 引用了**私有函数** `_execute_tool`（下划线 = 内部使用、不保证稳定）→ 正式项目应在 backend 提供**公开函数**，对话和 MCP server 都调它（要改 `backend/app/` 并配测试，这次不动）。

> **❓ 我的追问**：`sys.path.insert(0, BACKEND_DIR)` 如果不是加在最前面，而是最后面呢？  
> → 本项目里两种都能用（没有其他同名 `app`）。区别在**有同名模块时谁胜出**（**第一个找到的就用**），临时目录模拟：

| 情况 | `insert(0)` | `append` |
|---|---|---|
| 脚本目录有个同名 `app.py` | ✅ 拿到 backend 的 app | ❌ 被同名 app.py 抢走 |
| backend 里有个 `logging.py` | ❌ **标准库 logging 被顶替**（整个程序受影响） | ✅ 用标准库 |

- 选 `insert(0)`：要的是很具体的 `app`，且 backend 顶层目录不和标准库 / 第三方包重名。隐蔽细节：`backend/alembic/` 与迁移工具 alembic 同名，但它**没有 `__init__.py`**（命名空间包），查找时遇到会继续往后找，后面有真正的 alembic 就用真的，所以不会顶替。
- 根本解法：作为包安装（`pip install -e`），不手动改 `sys.path`。

### 📌 第 5 步（5a~5c）要记住的
> **工具描述四要素**：做什么、何时用 / 何时不该用、关键参数的易错点、返回什么及空结果怎么办——这就是模型看到的全部信息。
> **控制反转**：装饰器按函数签名生成校验模型并登记工具；SDK 收到 `tools/call` **先校验、再调用你的函数**、再把返回值转成 text（`to_json(indent=2)` → TextContent → 一行 JSON 写到 stdout）。
> **两层错误**：协议错误 → JSON-RPC `error`；**工具执行错误 → `result` + `isError: true`**，让模型读到错误自我纠正。**预料之中**的用 `ToolError`（完整信息给模型）；**意外崩溃**只给模型一句笼统的话、堆栈只留服务端（S3 错误不外泄）。
> stdio 下 **stdout 只给协议用**，日志走 stderr；数据库 session 用 `try / finally` 关闭。

### 5d · 接入 Claude Code ✅

注册（local 范围，配置写进 `~/.claude.json`，仓库里不生成文件）：
```bash
claude mcp add --scope local finwise -- \
  /Users/hzjconan/workspace/learn_ai/mcp-lab/.venv/bin/python \
  /Users/hzjconan/workspace/learn_ai/mcp-lab/finwise_mcp_server.py
claude mcp get finwise      # Status: ✔ Connected（真的启动子进程握手一次）
```

> **❓ 我的追问**：先给我看下，claude.json 里你具体改了什么？  
> → `claude mcp add` 写入（不是手改），只取 MCP 部分：
```json
"projects": {"/Users/hzjconan/workspace/learn_ai": {"mcpServers": {"finwise": {
    "type": "stdio",
    "command": "/Users/hzjconan/workspace/learn_ai/mcp-lab/.venv/bin/python",
    "args": ["/Users/hzjconan/workspace/learn_ai/mcp-lab/finwise_mcp_server.py"],
    "env": {}}}}}
```
- 挂在 `projects["…/learn_ai"]` 下 = **local 范围**，只在这个目录打开 Claude Code 才加载；顶层（user 范围）无 MCP 配置。
- 如实说明：执行前没备份，给不出严格的前后对比；Claude Code 运行时本身也会更新该文件其他字段。
- 撤销：`claude mcp remove finwise -s local`。

重启（`/exit` → `claude -c`）后问"帮我查一下 C3 风险等级有哪些在售产品"，实际过程：

1. **先要加载工具定义**：重启后 `mcp__finwise__search_products` 只有名字，我先调 `ToolSearch` 加载定义才能调用 → 第 2 步"按需加载工具定义"（deferred tools）在自己的 server 上真实发生。
2. **模型看到的就是 5a 写的原文**：description 整段、参数说明"注意是客户等级，不是产品的 R1~R5"、`enum` C1~C5 → 据此传 **`C3`** 而不是 `R3`。
3. **路由前缀**：`mcp__finwise__search_products`，按中间的 `finwise` 交给对应 MCP client（第 3 步）。
4. 返回 3 个在售产品（BROWSE-001 平衡混合A、BROWSE-002 平衡混合B、DEV-R3-03 平衡配置C），内容就是 SDK `to_json(indent=2)` 转出的那段文本。收益单位不一致的问题照实列出、没有替它换算。
5. 没弹权限确认：当前会话是自动模式；默认模式下首次调用 MCP 工具一般要确认（第 7 步）。

整条链路：
```
用户提问 → 模型输出 tool_use → Claude Code 的 MCP client 翻译成 tools/call → stdin → server 子进程
→ SDK 校验参数 → 你的 search_products → backend 的 _execute_tool 查开发库
→ stdout → Claude Code 包成 tool_result → 模型整理成回答
```
**全程查询逻辑只有一份（backend 的代码）**——第 1 步"工具只实现一次"落地。

### 📌 第 5 步要记住的（5d）
> 注册：`claude mcp add --scope local|project|user`；`claude mcp get` 会真的启动 server 做健康检查。新加 server 要重启（`claude -c` 接着对话）。
> 模型对工具的全部认知 = **tools/list 返回的名字 + 描述 + 参数 schema**；Claude Code 还会**延迟加载**工具定义，用到时才读进上下文。

### 5d 之后的追问

> **❓ 我的追问**：你说 `mcp__finwise__search_products` 一开始只有名字，你一开始看到的名字是什么？`~/.claude.json` 里有 `finwise` 不奇怪，但 `search_products` 这个字符串是怎么得出的？  

会话启动时系统提示里的原文：
```
The following deferred tools are now available via ToolSearch. Their schemas are NOT loaded ...
ListMcpResourcesTool / ReadMcpResourceDirTool / ReadMcpResourceTool / mcp__finwise__search_products
# MCP Server Instructions
## finwise
FinWise 理财产品查询（只读）。
```
- 一开始就看到**完整名字**，只是没有描述和参数定义。
- `search_products` **不在配置里，来自运行时**：
```
Claude Code 启动 → 读 ~/.claude.json（有个 finwise，启动命令是 xxx）
→ 启动 finwise_mcp_server.py 子进程 → 经 stdio 问它：
     server/discover 或 initialize → "instructions": "FinWise 理财产品查询（只读）。"
     tools/list                    → name: "search_products" + 完整描述、参数 schema
→ 拼成 mcp__<配置名 finwise>__<tools/list 的名字 search_products>
→ 只把名字放进模型上下文，完整定义留在 Claude Code；调 ToolSearch 时才交给模型
```
- `search_products` 归根结底是**你的函数名**（装饰器登记）；instructions 来自 `MCPServer("finwise", instructions=...)`。→ **提问之前，Claude Code 已经启动了 server 并完整对话过一轮。**

> **❓ 我的追问**：现在这个 MCP 是让 Claude 在启动时也执行 finwise_mcp_server.py 吗？那是不是有个 web server 在本机跑着、占用某个端口？这个 Python 进程什么时候停？  

实际查进程：
```
PID    PPID   运行时长  命令
91216  91183  11:05     …/Python …/mcp-lab/finwise_mcp_server.py
父进程 91183 = claude -c；监听的 TCP 端口：无
```
- ✅ 是，Claude Code 启动时把它作为**子进程**运行。
- ❌ **不是 web server、不占端口**：stdio 只用进程间管道通信（第 4 步）。
- **何时停**：生命周期跟着 Claude Code 会话；退出时管道关闭 → server 读到输入结束 → 自己退出（5c 里关 stdin 子进程就结束，同理）；`/mcp` 重连 = 结束旧进程、启动新进程。

**顺带解开的谜：它的 stdin 居然是 `/dev/null`**
```
0（stdin）  → /dev/null           ← 照理应是连 Claude Code 的管道
1（stdout） → 一个 socket
2（stderr） → 和 stdout 同一个 socket
```
读 SDK `mcp/server/stdio.py` 发现是**有意为之**：① 先把真正的 stdin / stdout 复制到编号更大的私有描述符（协议只走它们）；② 再把 0 号换成 `/dev/null`（`_open_stdin_diversion`）、1 号换成 stderr 的副本（`_open_stdout_diversion`）。→ 随手 `print()` 进 stderr、误读 stdin 读到空，**都不会搞坏协议**。（第 4 步已加更正。）

> **❓ 我的追问**：现实中 MCP 多半是别人提供的远程服务，不是自己启动程序，这时怎么让 Claude 注册？  

用 **Streamable HTTP**，注册时给 **URL** 而不是启动命令：
```bash
claude mcp add --transport http sentry https://mcp.sentry.dev/mcp
claude mcp add --transport http corridor https://app.corridor.dev/api/mcp --header "Authorization: Bearer ..."
```
- 鉴权两种：**请求头带 token**（`--header`，内部服务 / 服务方发的 API Key）；**OAuth 登录**（`/mcp` 或 `claude mcp login <名字>` 跳浏览器授权，之后 Claude Code 自己保存和刷新 token）。
- 写进 `.mcp.json` 共享时 token 用环境变量引用：`{"type": "http", "url": "...", "headers": {"Authorization": "Bearer ${FINWISE_MCP_TOKEN}"}}`

| | stdio（现在这个） | HTTP（远程服务） |
|---|---|---|
| 注册时提供 | 启动**命令** | **URL** |
| 谁运行 server | **Claude Code**（子进程） | **服务提供方** |
| 何时停 | 跟着会话结束 | 一直在服务方运行 |
| 鉴权 | 不需要（继承本机用户权限） | 请求头 token / OAuth |

> **❓ 我的追问**：如果是 HTTP 的 MCP，启动时也会通过网络调用一遍吗？如果调用失败（不管本地程序还是 HTTP server），比如网络不通、进程没起来，会怎样？  

- **会**，做的事一样，只是走网络：不启动进程，向 URL 发 HTTP POST（`server/discover`、`tools/list`）。需要 OAuth 而没登录 → `/mcp` 里显示**需要认证**。
- 5c 抓包里 `server/discover` 响应带 `"cacheScope": "private"`、`"ttlMs": 0`：新版协议允许 server **告诉客户端结果能缓存多久**（0 = 别缓存），客户端是否利用看各自实现。

**启动时连不上**（本地进程起不来 / 网络不通，表现基本一样）：

| 结果 | 说明 |
|---|---|
| Claude Code 照常启动 | 一个 server 失败不影响整体 |
| 这个 server 的工具**不出现** | 没拿到 `tools/list` → 模型根本不知道这些工具，不会凭空调用 |
| 其他 server 不受影响 | 每个 server 独立 client（第 2 步） |
| 能看到失败状态 | `/mcp`、`claude mcp list` / `get` 显示失败（而非 `✔ Connected`） |
| 可手动重试 | 修好后 `/mcp` 里重连，不用重启 |
- 连接有**超时**限制（Claude Code 有可调整超时的环境变量），不会无限等。

**用到一半挂了**：

| | stdio | HTTP |
|---|---|---|
| 怎么挂 | 进程崩溃、被杀 | 服务重启、网络中断 |
| 调用时 | 调用失败，**错误作为 tool_result 返回给模型**，模型知道"没成功" | 同左 |
| 能否自动恢复 | 一般不会，`/mcp` 手动重连 | Claude Code 会**尝试自动重连** |
→ 5e-2 会实际验证：停掉 server、看错误、重启、重连。

> **❓ 我的追问**：鉴权看起来需要人工介入（有交互过程），本地没问题，线上的 agent 应用呢？  

线上没人坐在终端前点授权 → 换成**不需要人工交互**的方式。先分清 **agent 以谁的身份调用**：

**情况一：以"应用自己"的身份（机器对机器）**——如 FinWise 后端调内部产品服务（产品目录对所有用户一样）：

| 方式 | 怎么做 |
|---|---|
| **OAuth 2.0 Client Credentials**（客户端凭证模式） | 应用持有 `client_id` + `client_secret`，**用代码**换取**短期** access token，过期自动再换；无浏览器、无登录页 |
| **API Key** | 服务方发的长期 key 放请求头；最简单，泄露风险大，要定期更换 |
| **云平台身份**（workload identity） | 平台给服务分配身份（如 Kubernetes service account），连 secret 都不用自己保管 |
- 凭证放**密钥管理服务**或部署时注入的环境变量，不写代码 / 配置文件（🔁 `.mcp.json` 写 `${…}` 同理）。

**情况二：代表"某个用户"调用**——如查客户自己的持仓，只能看他自己的数据：
```
① 用户在 FinWise 网页正常登录 / 点"授权连接"   ← 人工交互挪到应用界面，只发生一次
② 后端拿到这个用户的 token，加密保存
③ agent 以该用户身份调 MCP：应用代码取出 token 放进请求头 → MCP 服务据此判断"是谁、能看什么"
④ 过期：refresh token 自动续期；彻底失效：agent 告诉用户"请重新授权"
```
- 更严格：把用户 token **换成权限更小的 token**再交给下游（只能读持仓、不能交易）= **token 交换**（token exchange），最小权限用在凭证上。🔁 阶段七 S1"code 即身份"：身份必须来自可信认证。

**最关键：凭证永远不能交给模型**
```
❌ 把 token 写进 system prompt，让模型调工具时作为参数传
✅ 模型只输出 tool_use（工具名 + 业务参数）；MCP client 发请求时由代码在请求头加 token
```
- 模型可能被 prompt 注入（🔁 S2）诱导泄露 token；模型没见过就没这风险。
- 🔁 第 3 步"LLM 不知道 MCP 存在"在这里成了安全优势：鉴权全在 Host 层。🔁 B#7：关键值来自认证和服务端，不来自模型。
- 协议层：MCP 鉴权规范**基于 OAuth**；企业统一授权扩展（2026-06 进入稳定版）由公司统一身份系统签发 token，不需要每个用户对每个 server 逐个授权。

> **❓ 我的追问**："机器对机器"的场景，Claude 启动时自己初始化访问 MCP 时怎么拿凭证？还是线上不存在这样的 case、没有 claude 命令行？  

**线上 agent 的 Host 一般不是 Claude Code，是你自己写的服务**：

| Host | 谁在用 | 在哪运行 |
|---|---|---|
| Claude Code、Claude Desktop、IDE 插件 | 开发者、个人 | 自己电脑 |
| **你自己的后端服务**（如 FinWise 后端） | 你的客户（网页、App） | 你的服务器 |
- 🔁 **FinWise 后端已经是 Host**：`chat_service.py` 自己跑 agent loop、调 Claude API 拿 `tool_use`、再调 `_execute_tool`——只是没用 MCP。
```
客户浏览器 → FinWise 后端（Host）
               ├── agent loop（你的代码）
               ├── 调 Claude API → 拿到 tool_use
               └── MCP client（MCP SDK）── HTTP + token ──▶ 远程 MCP 产品服务
                      ▲ token：服务启动时从环境变量 / 密钥管理服务读取
```
- "启动时初始化"由**你的服务代码**完成：读凭证 → 换 token → 创建 MCP client（token 放请求头）→ `server/discover`、`tools/list` → **由你的代码**把工具定义转成 Claude API 的 `tools` 参数。🔁 测试里写过 `async with Client(m.server) as c: await c.list_tools()`，线上只是连 URL 并带 token。全程无人工，和连数据库读密码一样。
- **Claude Code 在线上也会用，但用于自动化任务**：CI 里 `claude -p "任务"`（`.mcp.json` 写 `${GITHUB_TOKEN}`，CI 从密钥库注入）；**Claude Agent SDK**（把 Claude Code 背后的 agent loop、工具调用、MCP 连接做成可嵌入程序的库，代码里给 MCP 配置传请求头）。
- **需要人工 OAuth 登录的，只有开发者在自己电脑上用 Claude Code 的场景。**

> **❓ 我的追问**：那线上 agent 的场景，还有"注册 MCP"这个概念吗？  

**有，只是变成了应用里的一份配置**。`claude mcp add` 本质只做一件事：告诉 Host 连哪些 server、怎么连。线上同样需要，由你定义格式：

1. **写进应用配置（最常见）**，按环境区分，凭证只写环境变量引用：
   ```yaml
   mcp_servers:
     product:
       url: https://mcp-product.internal.example.com/mcp
       auth: {type: client_credentials, client_id_env: PRODUCT_MCP_CLIENT_ID, client_secret_env: PRODUCT_MCP_CLIENT_SECRET}
   ```
   加 server = 改配置、重新部署（走代码评审和发布，和改数据库地址一样）。
2. **按 agent 分配 server**（最小权限）：理财顾问 agent 只连 `[product, compliance]`，运营助手只连 `[order, customer]` → 被注入也查不到不该查的。🔁 第 2 步"按领域拆 server、按需连接"。
3. **统一 MCP 网关**：agent 只配网关地址，网关集中做鉴权、权限、审计、限流（🔁 Web 的 API 网关）。
4. **用户自己添加**（面向用户的产品，如 claude.ai 的"连接器"）：用户在界面添加远程 MCP 并 OAuth 授权，注册信息按用户存数据库。
- **不变的一条：连哪些 server 是事先配置的白名单，不能让模型根据对话自己决定去连某个 URL**——恶意 server 可在**工具描述**里藏指令（第 7 步"工具描述注入"）；🔁 `.mcp.json` 首次使用要确认也是防这个。

### 📌 5d 之后要记住的
> Host **启动时就连 server**（stdio 起子进程 / HTTP 发请求），拿 `tools/list` 后**只把工具名放进上下文**（延迟加载）；工具名 = `mcp__<配置名>__<server 返回的名字>`。stdio server **不占端口、随会话结束**；mcp 2.x SDK 把 stdin 换成 `/dev/null`、stdout 导向 stderr，保护协议通道。连不上的 server 工具**不出现**、不影响别的 server，`/mcp` 可重连。
> **线上 agent 的 Host 是你自己的后端**：注册 = 应用配置（白名单、按 agent 分配、或走网关）；凭证由代码从环境变量 / 密钥管理读取并**注入请求头**，**绝不进 prompt**。机器对机器用客户端凭证模式 / API Key / 云平台身份；代表用户则在应用界面授权一次、后端保存并续期。人工 OAuth 只出现在开发者电脑上用 Claude Code 的场景。

### 5e 计划（同一个 server，接到两种 Host）

| 小步 | 内容 | 对应的追问 |
|---|---|---|
| 5e-1 | server **以 HTTP 方式独立运行**，看端口、独立进程 | 是不是 web server、占不占端口、何时停 |
| 5e-2 | **开发者场景**：`claude mcp add --transport http` 注册；中途停掉 server 看失败、重启后 `/mcp` 重连 | 远程怎么注册；连不上 / 用到一半挂了 |
| 5e-3 | **线上场景**：模拟 FinWise 后端的 Host——① 配置文件（白名单 + 凭证引用）② server 加 token 校验（401）③ Host 启动：读 token → MCP client → discover / list → 转成 Claude API tools ④ agent loop（检查发给模型的内容里没有 token）⑤ server 停掉时 Host 怎么降级 | 线上 Host、凭证、"注册"、机器对机器鉴权 |

### 5e-1 · server 以 HTTP 方式独立运行 ✅

用户的代码（argparse 选择传输方式，默认仍是 stdio）：
```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FinWise 产品查询 MCP server")
    parser.add_argument("--http", action="store_true", help="以 Streamable HTTP 方式运行（默认是 stdio）")
    parser.add_argument("--port", type=int, default=8765, help="HTTP 模式监听的端口（默认 8765，避开 8000）")
    args = parser.parse_args()
    if args.http:
        log.info("以 Streamable HTTP 方式启动，监听 127.0.0.1:%d/mcp（无状态）", args.port)
        server.run("streamable-http", host="127.0.0.1", port=args.port, stateless_http=True)
    else:
        server.run("stdio")
```
- SDK 2.x：`server.run("streamable-http", host=..., port=..., stateless_http=True)`，路径默认 `/mcp`；`stateless_http=True` 不发 `Mcp-Session-Id`。
- **为什么不用默认 8000**：FinWise 后端开发服务器用 8000，`scripts/e2e-test.sh` 启动前会**杀掉**占 8000 的进程。
- 测试 9 个通过：新增"真的起子进程 `--http --port <随机>`、用 `Client(url)` 连接"和"默认仍是 stdio"。

实测：
```
Python  97315 … TCP 127.0.0.1:8765 (LISTEN)        ← HTTP 版监听端口
（同时 Claude Code 的 stdio 版 PID 91216 仍在、无端口——两个独立进程，同一份代码）
```
用 curl 手动调（与 5c 写进 stdin 的那行**完全一样**，只是放进 HTTP 请求体）：
```bash
curl -s -i --noproxy '*' -X POST http://127.0.0.1:8765/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_products","arguments":{"risk_level":"C3"},"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientInfo":{"name":"curl","version":"1"},"io.modelcontextprotocol/clientCapabilities":{}}}}'
```
响应：
```
HTTP/1.1 200 OK
server: uvicorn
content-type: text/event-stream

event: message
data: {"jsonrpc":"2.0","id":1,"result":{"content":[{"text":"{\n  \"risk_level\": \"C3\", …
```
- `server: uvicorn`：SDK 内部用 uvicorn 起 Web 服务（🔁 FinWise 后端也是）。
- `text/event-stream` = **SSE**，`data:` 那行就是 JSON-RPC 响应 → "Streamable"：同一连接可连续推多条（进度更新等）。
- 无 `Mcp-Session-Id` 响应头（无状态）。不带 `Accept`、不带 `_meta` 也能用（实现宽松），正规客户端都应带上。
- 当时它是我在 Claude Code 里起的后台任务 → 父进程链 `后台任务 → claude -c`，退出会被一起结束；5e-2 改由用户在**独立终端**启动。

> **❓ 我的追问**：POST http://127.0.0.1:8765/mcp 的 curl 命令给我下  
> → 即上面的命令。参数：`-s` 静默、`-i` 带响应头、`--noproxy '*'` 不走代理（本机有 `HTTP_PROXY=127.0.0.1:8002`；🔁 `_bridge.py` 同样的坑）、`-X POST`、`Content-Type` 请求体是 JSON、`Accept` 两种响应格式都接受（规范要求，server 据此回普通 JSON 或 SSE）、`-d` 请求体。另有 tools/list、传错参数（R3 → isError）两条变体。想好读：去掉 `-i`，末尾加 `| sed -n 's/^data: //p' | python3 -m json.tool`。前提：server 已用 `--http` 运行，否则 `Connection refused`。

### 5e-2 · 开发者场景：注册 HTTP 版、测试故障与恢复 ✅

```bash
claude mcp add --transport http --scope local finwise-http http://127.0.0.1:8765/mcp
```
- 注册时 server 刚被我停掉 → `claude mcp get` 立刻显示：
  ```
  Status: ✘ Failed to connect
  Issue: ECONNREFUSED: Unable to connect. Is the computer able to access the url?
  ```
  **注册本身成功**（只是记下要连谁，不要求对方在线）；`ECONNREFUSED` = 该地址无程序监听。对比：stdio 的 server **由 Claude Code 启动**，HTTP 的 **得别人先启动**。
- 用户在**独立终端**启动 `--http` → 重启 Claude Code。

**测试 A · 正常调用**："用 finwise-http 查一下 C2 风险等级的产品"
- 调的是 **`mcp__finwise-http__search_products`**（描述与 stdio 版一字不差，前缀不同 → 路由给 HTTP client）；查出 REC-001 稳健货币A 等 3 个。
- 进程：监听 8765 的 PID 97917，父进程 = **用户终端的 `/bin/zsh -il`** → 与 Claude Code 无关，退出 Claude Code 它也继续运行。
- stdio 版 PID 从 91216 变成 830 → 重启后旧子进程随旧会话结束、新会话又起了一个（验证"生命周期跟着会话"）。
- HTTP 版的日志打在用户自己的终端里；stdio 版的 stderr 被 Claude Code 接管，看不到。

**测试 B · 用到一半挂了**：用户 Ctrl+C 停掉 server，再让我查 C4
- **我根本没机会调用**：Claude Code 已检测到断开，① 把 `mcp__finwise-http__search_products` **从我的工具列表移除**（并告知"不要再搜索它"）② 告诉我 server 连接失败 `ECONNREFUSED`，强调这是**连接故障**、不是没配置，应告诉用户去修复或重试 ③ 撤回该 server 的 instructions。
- ⚠️ **更正我之前的预测**："调用失败、错误作为 tool_result 返回"——实际是**工具直接被移除**。只有"调用发出那一刻才挂掉、Claude Code 还没发现"时，才会是错误作为 tool_result 返回。
- 道理：已知连不上的工具，与其让模型调用再拿回错误，不如直接不给；强调"连接故障"防止模型误以为功能不存在。
- 当时 stdio 版 `finwise` 仍连着，可以**降级**改用它查（第 6 步"降级链"），但用户指定了 finwise-http，没有自作主张。

**测试 C · 恢复**：用户重启 server，再让我查 C4

| 时刻 | server | 我能不能用 |
|---|---|---|
| Ctrl+C 之后 | 停了 | ❌ 工具被移除，通知 `ECONNREFUSED` |
| 重新启动 server 后 | ✅（curl 返回 200） | ❌ **仍不能用**——Claude Code **没有自动重连** |
| 用户执行 `/mcp` 后 | ✅ | ✅ "Reconnected to finwise-http."，收到"工具重新可用"通知，**instructions 也恢复**，查出 C4 的 FAV-001 成长股票A 等 3 个 |

- ⚠️ **更正**："Claude Code 对 HTTP 会自动重连"在这个场景**不成立**（server 已被判定连接失败后再恢复，不会自己重连）。自动重连可能只针对短暂中断，这次实验无法完全确认，但结论明确：**这种情况不能指望它自己好**。
- 小插曲：用户输入 `! /mcp` 进了 bash 模式，shell 把它当文件路径执行报错。`/命令` 是 Claude Code 斜杠命令，要在普通模式输入；`! 命令` 交给 shell。`! claude mcp get` 只是另起进程检查能否连上，**不会让当前会话重连**。

### 📌 5e-1 / 5e-2 要记住的
> HTTP 方式：server 是**独立 Web 服务**（SDK 内用 uvicorn）、**监听端口**、curl 可直接调；JSON-RPC 消息与 stdio 时**完全一样**，只是放进 HTTP POST；响应是 **SSE**（`event: message` / `data: …`）。
> 注册 ≠ 连接：注册只记下要连谁；HTTP server 要**别人先启动**。中途挂了：Claude Code **把工具从模型的工具列表移除**并标明"连接故障"；server 恢复后**不会自动重连**，要 `/mcp` **手动重连**。
> → 线上 Host 没人执行 `/mcp`，**必须自己处理重连、重试和降级**（5e-3 ⑤、第 6 步）。

### 5e-3 · 线上场景：模拟 FinWise 后端风格的 Host ✅

> **❓ 我的追问**：一会儿做 5e 的时候，能完整地带我过一下线上 agent 的场景吗？  
> → 于是把 5e-3 设计成：同一个 server，接一个**自己写的 Host**（不是 Claude Code），完整走一遍线上流程。

| 文件 | 内容 |
|---|---|
| `mcp-lab/mcp_config.yaml` | **线上的"注册"**：server 白名单、URL、`token_env`（只写环境变量名）、重试参数、agent → server 分配 |
| `mcp-lab/finwise_mcp_server.py` | 新增 Bearer 鉴权：设置 `FINWISE_MCP_TOKEN` 时，不带 / 带错 token → **401**（TODO 5e-3a） |
| `mcp-lab/online_host.py` | `McpHost`：startup（读 token、建共享 HTTP 客户端、取工具并缓存）/ answer（MCP 会话跑 agent loop、审计、降级）/ shutdown（TODO 5e-3b、5e-3c） |
| 测试 | mcp-lab 共 28 个：server 17 + Host 11（含"server 中途挂掉 → 冷却 → 自动重连"） |

#### 5e-3a · token 校验

> **💬 课堂问答**
>
> **🙋 问**：比较 token 为什么要用 `hmac.compare_digest`，不用 `==`？（`==` 遇到第一个不同字符就返回）  
>
> **🧑 我的回答**：攻击者可以通过响应时间逐位猜出 token  
>
> **🤖 点评**：✅ 对，这就是📛 **时序攻击**（timing attack），属于**侧信道攻击**（不破解算法，从响应时间这类"旁边漏出来"的信息推断秘密）。  
> ➕ 过程：先把第 1 位各种字符都试一遍，最慢的那个是对的 → 固定后猜第 2 位……难度从"猜整个 token"降到"逐位猜、每位几十次"。时间差是纳秒级、会被网络延迟淹没，攻击者要大量重复请求做统计，但这是真实存在的攻击。  
> ➕ `hmac.compare_digest` 不管第一个不同字符在哪，都**比较完、耗时一样**（只可能泄露长度，不泄露内容）。

```python
def is_authorized(auth_header: str | None, expected_token: str) -> bool:
    if not auth_header or not auth_header.startswith("Bearer "):
        return False
    return hmac.compare_digest(auth_header[len("Bearer "):], expected_token)
```

> **❓ 我的追问**：代码里说"`app = server.streamable_http_app(stateless_http=True)` 和 `server.run("streamable-http", …)` 同一个应用"，解释下。  

SDK 源码 `run_streamable_http_async` 只做两件事：
```python
starlette_app = self.streamable_http_app(stateless_http=stateless_http, host=host, ...)   # ① 生成 Web 应用
config = uvicorn.Config(starlette_app, host=host, port=port, ...)                          # ② 交给 uvicorn 运行
await uvicorn.Server(config).serve()
```
`run_http` 把这两步**拆开**，中间插一层鉴权：
```python
app = server.streamable_http_app(stateless_http=True)   # ① 同一个应用
app = with_bearer_auth(app, token)                       # ★ 包一层：先查 token
uvicorn.run(app, host="127.0.0.1", port=port)            # ② 自己交给 uvicorn
```
- 🔁 和 FinWise 后端 `uvicorn app.main:app` 同一结构：**uvicorn**（Web 服务器：监听端口、解析 HTTP）+ **应用**（路由；这里是 SDK 返回的 **Starlette** 应用，FastAPI 也基于 Starlette）。
- 两者用 📛 **ASGI**（Asynchronous Server Gateway Interface）沟通：每个请求调一次 `app(scope, receive, send)`。`with_bearer_auth` 返回的 `wrapped` 也是 `(scope, receive, send)` 函数 → **本身也是 ASGI 应用** → 可以一层层嵌套 = **中间件的原理**（🔁 FastAPI `@app.middleware("http")`）。
  ```
  请求 → uvicorn → wrapped（查 token）──不通过──▶ 401
                        │ 通过
                        ▼
                MCP 的 Starlette 应用 → JSON-RPC → 参数校验 → search_products
  ```
- 小区别：SDK 还传了 `host=host`（防 DNS 重绑定，检查请求的 Host 头）；我们用默认 `"127.0.0.1"`，与监听地址一致，效果相同。

#### 重构：按生命周期组织（用户指出的问题）

> **❓ 我的追问**：answer 函数每处理一次用户问题，都会 load 一遍 config、调用 server_settings，这些不是应该只做一次么？  

✅ 对。初版 `answer()` 每次：读 YAML → 读 token → 新建连接取工具列表 → **再新建一个连接**跑 agent loop（每个请求建两次连接）。是为演示"一个函数跑完一个问题"，作为线上写法不对。

| 事情 | 什么时候做 | 原因 |
|---|---|---|
| 读配置 | 服务启动一次 | 线上改配置要重新部署 |
| 建连接 | 启动时建、之后复用 | keep-alive，别每次握手 |
| 工具列表 | 启动时取、缓存 | 有变化靠 `notifications/tools/list_changed` 或 `server/discover` 的 `ttlMs` 刷新 |
| 读 token | 启动时读，但要**能刷新** | 短期 OAuth token 过期前自动换 |
| agent loop | 每个请求 | 真正和问题相关的部分 |
| 用户身份 token（代表用户时） | 每个请求 | 每个请求对应不同用户——唯一必须按请求处理的凭证 |
- 启动时连不上：**服务照常启动**、标记不可用、相关请求降级、后台 / 下次请求再试（🔁 Claude Code 也是"一个 server 连不上不影响启动"；区别是线上要自己重连；第 6 步熔断器）。🔁 FastAPI **lifespan**：连接类资源启动时建、关闭时释放。

**重构时实测踩到的坑**：一开始按"启动时建好、之后复用"**长期持有 MCP Client 对象**，"server 中途挂掉"测试失败：
```
RuntimeError: Attempted to exit cancel scope in a different task than it was entered in
asyncio.exceptions.CancelledError: Cancelled via cancel scope ...
```
MCP Client 内部有后台**任务组**，server 一挂任务组被**取消**，取消信号窜进正在处理的请求；`CancelledError` 不是 `Exception`，`except Exception` 接不住。→ 改成两层：

| 层 | 生命周期 | 为什么 |
|---|---|---|
| **共享 HTTP 客户端**（含 token 请求头，内部自带连接池）+ 工具缓存 | 长期持有 | 真正"贵"的是 TCP 连接和握手 |
| **MCP 会话**（Client 对象） | 每个请求开、用完关 | 协议**无状态**，开会话很便宜；开和关都在同一个请求里，server 挂了只影响这一次 |
- 查源码确认：传进去的 `http_client`，SDK **不会关**（`client_provided` 时不 `aclose`），可放心多会话共用。

> **❓ 我的追问**：`make_http_pool` 是不是只返回了一个 http client？叫 pool 会不会有歧义？  
> → ✅ 对，返回的是 `httpx2.AsyncClient`，**一个客户端，内部自带连接池**，不是池对象。已改名 **`make_http_client`**，相关说法统一为"共享 HTTP 客户端"。🔁 类比 SQLAlchemy `create_engine()` 返回 engine（内部带池），没人叫它 pool。

```python
class McpHost:
    async def startup(self)    # 一次：读 token、建共享 HTTP 客户端、取工具并缓存（连不上 → 标记不可用，不抛）
    async def answer(self, q)  # 每次：不可用且过了冷却 → 重连；可用 → 开 MCP 会话跑 agent loop；会话中途断开 → 降级
    async def shutdown(self)   # 一次：关闭共享 HTTP 客户端
```

#### 5e-3b · 工具格式转换 / 5e-3c · tool_result
```python
return [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema} for t in mcp_tools]
```
- 真实 server 的 `enum: C1~C5` 和参数说明原样保留 → 模型看到的约束和 5a 写的一致。
- **"MCP 与模型无关"的落脚点**：换 OpenAI 只改这一行（`{"type": "function", "function": {"name", "description", "parameters"}}`），**server 一行不改**（🔁 第 1 步 N + M）。

```python
return {"type": "tool_result", "tool_use_id": tool_use_id,
        "content": "\n".join(c.text for c in call_result.content),
        "is_error": call_result.is_error}
```
- `tool_use_id` 配对（🔁 04）；`is_error` 原样告诉模型（🔁 5c 自我纠正）。
- 可留意：content 也可能有图片等非文本块（没有 `.text`），更稳妥可加 `if hasattr(c, "text")`。

#### 演示结果（用户终端带 token 启动 server：`FINWISE_MCP_TOKEN=demo-secret-123 .venv/bin/python finwise_mcp_server.py --http`）

`变量=值 命令` 只给这一条命令设环境变量 → 模拟"部署时注入凭证"。

**① 不带 / 带错 token**：
```
HTTP/1.1 401 Unauthorized
content-type: application/json
www-authenticate: Bearer
{"error": "unauthorized"}
```
- 在中间件层就被挡住，参数校验、`search_products` 都不执行。`WWW-Authenticate: Bearer` 是标准做法：告诉客户端"要 Bearer 认证"。

**② 线上 Host，一次启动处理两个问题**：
```
[host] 已连接 product，缓存工具：['search_products']      ← 只出现一次
[host] 第 1 轮：search_products(C3) → 第 2 轮：final_answer(...)
[host] 第 1 轮：search_products(C5) → 第 2 轮：final_answer(...)   ← 复用 HTTP 客户端和工具缓存
🔍 审计：本请求发给模型 2 次，其中✅ 没有出现 token        ← 两个问题都是
```

**⚠️ 意外发现：模型自作主张补了单位**
- C3 回答老实写"4.3167""0.075"，还主动说明"系统没有标注单位"；
- C5 回答写成"**16%**""**15%**""**14.5%**"——直接调工具看原始返回是 `0.16`、`0.15`、`0.145` → **"%"是模型自己换算的**。
- 🔁 L02 第 8 步：Faithfulness 衡量"**有没有根据**"不是"对不对"——碰巧算对也是**无依据**；库里单位本就不统一（`4.3167` 和 `0.16` 并存），换组数据就可能算错。
- 🔁 L02 写的 `unsupported_numbers` 正好能抓：回答里的 16、15、14.5 在工具结果里都找不到 → **线上 Host 的输出端也需要数字硬校验**。
- 根本解法在数据端：**收益率统一单位、在返回里写明单位**（如 `expected_return_pct`）。🔁 L02 降低幻觉第一层"给模型对的资料"。

**③ 副作用：Claude Code 的 finwise-http 也被拒**
```
Status: ✘ Failed to connect
Issue: Dynamic Client Registration rejected (HTTP 401): {"error": "unauthorized"}
```
- 鉴权对所有 Host 一视同仁。
- 为什么报的是 **Dynamic Client Registration**：Claude Code 看到 401 + `WWW-Authenticate: Bearer` → 判断需要认证 → MCP 鉴权**基于 OAuth** → 自动走 OAuth 流程，第一步是📛 **动态客户端注册**（客户端先向授权服务登记自己、拿 client_id，之后才引导用户登录授权）→ 我们的 server 只核对固定 token、**不支持 OAuth** → 登记请求同样 401。
- 只认固定 token 的 server，注册时直接带请求头：
  ```bash
  claude mcp add --transport http --scope local finwise-http http://127.0.0.1:8765/mcp \
    --header "Authorization: Bearer demo-secret-123"
  ```

### 📌 5e-3 要记住的
> 线上 Host 由**你的代码**完成：**"注册"**（配置白名单、按 agent 分配）、**鉴权**（token 从环境变量注入请求头，**全程不进模型**，审计验证）、**连接管理**（共享 HTTP 客户端 + 工具缓存长期持有，**MCP 会话按请求开关**——别长期持有带后台任务的客户端）、**故障处理**（重试 + 指数退避、冷却、降级、自动重连）。
> server 端用 **ASGI 中间件**挡未授权请求（401 + `WWW-Authenticate`），比较 token 用 **`hmac.compare_digest`**（防时序攻击）。`server.run()` = 生成 Web 应用 + uvicorn 运行，拆开才能插中间件。
> 实测：**模型会自作主张补单位**（0.16 → 16%）→ 输出端要数字硬校验，数据端要统一并写明单位。

来源（第 3、4 步更正）：[Equixly: Stateless MCP](https://equixly.com/blog/2026/08/05/stateless-mcp/)、[Wavect 迁移指南](https://wavect.io/blog/mcp-stateless-server-migration-2026/)、[Microsoft: MCP Just Went Stateless](https://techcommunity.microsoft.com/blog/appsonazureblog/mcp-just-went-stateless-%E2%80%94-what-the-2026-spec-changes-about-scaling-on-app-servic/4530222)、[AAIF: MCP 2026 Spec Changes](https://aaif.io/blog/mcp-2026-changes-the-rules)、[Stacktree: breaking changes](https://stacktr.ee/blog/mcp-2026-spec-changes)、[Wikipedia: MCP](https://en.wikipedia.org/wiki/Model_Context_Protocol)
