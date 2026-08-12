# LangGraph 学习笔记（随学随记）

> 用途：专门记录 **LangGraph 框架本身** 的知识——和 `concepts-basics.md`（AI 通用概念）、
> `python-syntax-notes.md`（Python 语法）分开。
> 学习环境：隔离 venv `learn_ai/langgraph-lab/.venv`（独立于 backend，不污染 FinWise 的 Anthropic 栈）。
> 本机装的版本：**langgraph 1.2.10**（依赖 langchain-core / langgraph-checkpoint / langgraph-prebuilt / pydantic）。
> 维护：以后遇到新的 LangGraph 知识点，讲解后**经用户确认**再追加到本文档。

---

## 目录

- [LangGraph 是什么 / 官方资源](#langgraph-是什么--官方资源)
- [核心抽象：State / Node / Edge](#核心抽象state--node--edge)
- [手写 supervisor ↔ LangGraph 对照](#手写-supervisor--langgraph-对照)
- [State 设计：契约不是垃圾桶（长任务怎么不失控）](#state-设计契约不是垃圾桶长任务怎么不失控)
- [可视化：draw_mermaid / 条件边要声明才画得出](#可视化draw_mermaid--条件边要声明才画得出)
- [错误处理：节点抛异常 = 整图崩](#错误处理节点抛异常--整图崩)
- [核心认知：框架不是魔法](#核心认知框架不是魔法)

---

## LangGraph 是什么 / 官方资源

**LangGraph** 是 LangChain 团队做的、用来编排 **有状态的多步/多 agent 工作流** 的框架。核心思想：把 agent 的流程建模成一张**图（graph）**——节点是"干活的步骤"，边是"谁接谁"，一份共享**状态**贯穿全图。擅长复杂编排：分支、循环、并行、中断/恢复（human-in-the-loop）、持久化。

**官方资源**（URL 可能随官网改版变动，用前确认一下）：
- 文档：https://langchain-ai.github.io/langgraph/ （亦见 https://docs.langchain.com）
- GitHub：https://github.com/langchain-ai/langgraph
- 产品页：https://www.langchain.com/langgraph

**和 LangChain 的关系**：LangGraph 依赖 `langchain-core`，但**可以脱离 LangChain 单独用**——你可以只用它的图编排、节点里放任意 Python（不一定是 LLM）。本学习环境正是这么做：节点用确定性/桩函数，图离线就能跑，聚焦"图结构"本身。

---

## 核心抽象：State / Node / Edge

LangGraph 把编排拆成三样，`from langgraph.graph import StateGraph, START, END`（`START='__start__'`、`END='__end__'` 是内置的起止哨兵）：

**① State（状态）——贯穿全图的共享数据**
一个字典（用 `TypedDict` 定义结构），每个节点读它、往里写。取代"手写编排里层层传参的变量"。
```python
from typing import TypedDict
class State(TypedDict):
    customer_desc: str
    risk_level: str
    products: list
    recommendation: dict
```

**② Node（节点）——一个函数，吃 State、返回"要更新的字段"**
返回的 dict 会被 **merge 进 State**（不是替换整个 State，只更新你返回的键）。
```python
def assess_node(state: State) -> dict:
    # 读 state["customer_desc"]，算出 risk_level
    return {"risk_level": "C4", "dimensions": {...}}   # merge 进 State
```

**③ Edge（边）——谁接谁**
```python
graph = StateGraph(State)
graph.add_node("assess", assess_node)
graph.add_node("retrieve", retrieve_node)
graph.add_node("recommend", recommend_node)

graph.add_edge(START, "assess")           # 入口
graph.add_edge("assess", "retrieve")      # 普通边：顺序
graph.add_conditional_edges(              # 条件边：一个函数决定下一步去哪
    "retrieve",
    lambda s: "recommend" if s["products"] else END,
)
graph.add_edge("recommend", END)

app = graph.compile()                     # 编译成可执行图
result = app.invoke({"customer_desc": desc})   # 跑图，传入初始 State
```

- **普通边** `add_edge(a, b)`：a 跑完固定去 b。
- **条件边** `add_conditional_edges(a, fn)`：a 跑完，`fn(state)` 返回下一个节点名（或 `END`）——对应手写的 `if/else` 分支。
- **`compile()`** → 可执行 app；**`invoke(初始state)`** → 跑一遍返回终态 State。

---

## 手写 supervisor ↔ LangGraph 对照

（用 s6_02 手写的多 agent supervisor 直接对照，一一对应——这是理解 LangGraph 最快的路）

| s6_02 手写 | LangGraph |
|---|---|
| 层层传参的变量（risk_level/products…） | **State**（TypedDict，共享字典） |
| agent / 检索 函数 | **Node**（吃 State、返回更新字段） |
| "先 A 后 B" 的调用顺序 | **Edge**（`add_edge`） |
| `if not products:` 分支 | **Conditional edge**（`add_conditional_edges`） |
| `supervisor()` 这个函数 | 编译后的 **graph**，`app.invoke()` |
| `await agent(...)` 手动串 | 图按边自动流转 |

**LangGraph 相对手写多给的**（编排变复杂时才显价值）：
- **状态管理**：多节点共享/累积状态，不用层层传参（10 个节点手写就乱）。
- **可视化**：图能画出来，一眼看清流转（手写要读代码）。
- **循环/回退**：A→B→又回 A（如"推荐不满意就重评估"）= 一条回边；手写 while 会绕。
- **中断/恢复（human-in-the-loop）**：图能在某节点暂停、等人确认再续，状态自动存档（靠 checkpoint）。
- **并行**：多节点同时跑再汇合，图天然表达。

**但**：简单线性编排（A→检索→B 一条直线）**手写反而更简洁**——LangGraph 的价值在复杂图。**简单编排手写、复杂编排上图**，工程判断，不是越框架越好。（呼应 [[concepts-basics]] "Agent 框架"节的"何时上框架"。）

---

## State 设计：契约不是垃圾桶（长任务怎么不失控）

**疑问**：State 全局、会包含每步输出，长任务里岂不很重、难维护、不知哪个字段哪个 step 写的？

**先纠正**：State **不自动累积每一步输出**——它只包含节点主动 `return` 的字段。`return {"risk_level":"C4"}` 只写这一个；`return {}` 什么都不写；节点内部的中间变量（临时列表、计数）**留本地、不进 State**。**State 大小是你设计的，不是自动膨胀。**
→ 第一原则：**只往 State 放"跨节点要用"的数据，中间量留节点本地**（lg_01 的 assess_node 算了 values/normalized 但只 return risk_level+dimensions）。

**长任务变重时的管理手段（由轻到重）**：
1. **字段标注归属**：每个字段注释"谁写的"（`risk_level: str  # assess 节点写`）——约定=可维护性。
2. **按域分组（嵌套）**：别 flat 铺开，`assessment: dict` / `recommendation: dict` 按产出方聚成子 dict。
3. **input/output schema 分离**：`StateGraph(State, input_schema=..., output_schema=...)`——内部 State 可丰富，对外只暴露窄接口。
4. **subgraph（子图）——规模化的真正答案**：大系统不该是一个巨型 flat State，而是**拆成多个子图**，每个子图有自己的小 State，父图只看子图的汇总输出（像函数拆分，不把所有变量塞进全局作用域）。

**反直觉的点**：State 其实比手写"散变量"**更**可维护——手写时 risk_level/products 是散落在函数里的局部变量、靠读代码追数据流；State 把跨节点数据收进**一个声明式、带类型的 TypedDict**，一览无余还能类型检查。

一句话：**State 是你设计的"跨节点数据契约"，不是自动堆东西的垃圾桶。** 重了就靠 标注归属 / 按域嵌套 / input-output schema / subgraph 拆分。

---

## 可视化：draw_mermaid / 条件边要声明才画得出

图能画出来是 LangGraph 相对手写编排的一大好处（手写只能读代码想象流程）。

**核心方法**：`app.get_graph()` 拿到可绘制图对象，再调画法：
```python
g = app.get_graph()
g.draw_mermaid()      # → Mermaid 文本（零依赖、永远可用；贴到 mermaid.live / GitHub markdown 渲染）
g.draw_ascii()        # → 终端 ASCII 图（需 pip install grandalf）
g.draw_mermaid_png()  # → PNG 图片（需联网调 mermaid.ink，或本地 graphviz）
```
> 贴 mermaid 时**第一行 `graph TD;` 不能省**（否则 mermaid.live 报 "No diagram type detected"）；`draw_mermaid()` 的完整输出已带它，整段贴即可。实线 `-->`=普通边，虚线 `-.->`=条件边。

**机制（一点不神秘，能看穿）**：`draw_mermaid()` 不运行图、不调 LLM，就是**把图的"节点+边清单"翻译成文本**：
```
get_graph().edges 里每条边：             draw_mermaid 翻译：
 __start__→assess  conditional=False  →  __start__ --> assess;
 retrieve→recommend conditional=True  →  retrieve -.-> recommend;   （条件边→虚线）
```
链路：**声明分支 → get_graph() 把分支补进 edges 清单 → draw_mermaid 翻译成文本 → mermaid.live 画成图**。每层只做一件事。（你也能自己遍历 `g.edges` 导出任意格式。）

**⚠️ 条件边默认画不出——因为它的目标是运行时才知道的，静态不可见**。要画出条件分支，必须**声明**目标（官方两方案）：
1. **路由函数加 `Literal` 返回标注**（推荐，最轻）：`def route(s) -> Literal["recommend", "__end__"]:` —— LangGraph 读标注把分支补进 edges 清单。注意 `END` 的字面值是 `"__end__"`。
2. **`add_conditional_edges` 传 path_map**：`add_conditional_edges("retrieve", route, {"recommend":"recommend", END:END})`。
（用 `Command` 路由时，返回标注 `Command[Literal[...]]` 是**强制**的，否则渲染不出——见官方文档。）

**为什么推荐 Literal**：一行标注三重收益——① 图画得对；② 类型检查（路由只会返回这几个值、写错节点名被抓）；③ 自文档。不只是为画图，是纯赚的好习惯，所有路由函数都建议加。

**更本质**：任何"静态可视化"都只能画静态可知的东西；运行时才决定的分支必须以某种形式声明（标注/映射表）工具才画得出——不限于 LangGraph。

---

## 错误处理：节点抛异常 = 整图崩

**LangGraph 默认：任何节点抛异常 → 整个 `app.invoke()` 崩**（和手写 supervisor"一个 await 失败整个函数崩"一样，框架不自动容错）。lg_01 就撞到：bridge 偶发失败 → assess 节点抛 → 整图崩。

两个层面的容错：
1. **节点内自己兜**（最直接）：节点里的 LLM 调用加 try/重试（lg_01 的 `call_bridge_tool` 加了 retries）。
2. **节点级 retry_policy（LangGraph 原生）**：`g.add_node("assess", assess_node, retry=RetryPolicy(max_attempts=3))`——框架帮你重试失败节点，不用自己写 try。这是"框架多给你的"一个容错特性（对照手写要自己包）。lg_02 会正式用。

---

## LLM 从哪来（学习环境的取舍）

节点是普通 Python 函数，里面**怎么调 LLM 都行**。本学习环境的约束与选择：

- **基础篇（lg_01/02/03）用裸 `call_tool`**（backend/scratch/_bridge 的 anthropic SDK + 本地 bridge）——**已验证能跑**（s6_02 就是这么做的），零改动、能用真 LLM。
- **`ChatAnthropic`（langchain）走不通本地 bridge**：验证脚本 `langgraph-lab/verify_chatanthropic_bridge.py` 实测——请求能发出（`anthropic_api_url` 指向 bridge + `NO_PROXY=localhost` 绕本机代理），但 `_format_output` 里 `data.model_dump()` 崩：`'str' object has no attribute 'model_dump'`。**和 tool_runner（`messages.parse` 崩在 `'str'...content`）同一病根**：bridge 的 `/v1/messages` 返回的**响应体结构不够标准**（裸 SDK 能容忍，langchain/tool_runner 的严格解析层吃不下）。**不是端点缺失，是响应格式不达标。**
- **教训**：别只查"端点在不在"就断言能用——要真跑。（这次先验证才挖出真相。）
- **进阶篇（lg_04 ChatAnthropic）用教学 mock bridge——✅ 已验证可行**：`langgraph-lab/mock_bridge.py`（FastAPI，端口 8788）。根因：真 bridge 只支持 `stream=true`（SSE），而 `ChatAnthropic.invoke()` 默认走**非流式**、期望完整 Message JSON → 对不上就崩。mock 不接真模型，只做一件事：收到 `POST /v1/messages` 就按请求里的工具名返回一个**结构合法的非流式 Anthropic Message JSON**（`{id,type:message,role,model,content:[{type:tool_use,id,name,input}],stop_reason:tool_use,usage}`），input 写死（离线、确定）。实测 `ChatAnthropic(anthropic_api_url="http://localhost:8788").bind_tools([...]).invoke(...)` 成功解析出 `tool_calls`。
  起服务：`cd langgraph-lab && .venv/bin/uvicorn mock_bridge:app --port 8788`。

---

## 核心认知：框架不是魔法

和学 `tool_runner`（s6_01）同一条：**LangGraph 就是把你手写的"节点+边+状态"结构化成一张图**。你在 s6_02 亲手写过 supervisor，所以现在看这些抽象，**每一个都知道对应你哪行代码**——`add_edge` 就是那行 `await agent2(...)`、条件边就是那个 `if not products`。

这正是"先裸手编排、再上 LangGraph"的意义：框架对你**透明**，出问题能定位到"哪个节点/哪条边"，而不是被"图引擎"唬成黑箱。
