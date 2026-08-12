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

## LLM 从哪来（学习环境的取舍）

节点是普通 Python 函数，里面**怎么调 LLM 都行**。本学习环境的约束与选择：

- **基础篇（lg_01/02/03）用裸 `call_tool`**（backend/scratch/_bridge 的 anthropic SDK + 本地 bridge）——**已验证能跑**（s6_02 就是这么做的），零改动、能用真 LLM。
- **`ChatAnthropic`（langchain）走不通本地 bridge**：验证脚本 `langgraph-lab/verify_chatanthropic_bridge.py` 实测——请求能发出（`anthropic_api_url` 指向 bridge + `NO_PROXY=localhost` 绕本机代理），但 `_format_output` 里 `data.model_dump()` 崩：`'str' object has no attribute 'model_dump'`。**和 tool_runner（`messages.parse` 崩在 `'str'...content`）同一病根**：bridge 的 `/v1/messages` 返回的**响应体结构不够标准**（裸 SDK 能容忍，langchain/tool_runner 的严格解析层吃不下）。**不是端点缺失，是响应格式不达标。**
- **教训**：别只查"端点在不在"就断言能用——要真跑。（这次先验证才挖出真相。）
- **进阶篇（lg_04 ChatAnthropic）计划**：另做一个**教学用 bridge**，只模拟"合法的响应结构"（不必真接 claude CLI，返回符合 Anthropic Message/SSE 结构的假数据即可满足教学）——干净解决 langchain/tool_runner 兼容，且不动现有 bridge。或到时用真 ANTHROPIC_API_KEY。

---

## 核心认知：框架不是魔法

和学 `tool_runner`（s6_01）同一条：**LangGraph 就是把你手写的"节点+边+状态"结构化成一张图**。你在 s6_02 亲手写过 supervisor，所以现在看这些抽象，**每一个都知道对应你哪行代码**——`add_edge` 就是那行 `await agent2(...)`、条件边就是那个 `if not products`。

这正是"先裸手编排、再上 LangGraph"的意义：框架对你**透明**，出问题能定位到"哪个节点/哪条边"，而不是被"图引擎"唬成黑箱。
