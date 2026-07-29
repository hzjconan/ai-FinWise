# 03. B 系列实战复盘：把 chat_service 改成 agent loop，学到了什么

> 配套 `02-tooluse-refactor.md`（设计规格）。那份讲"怎么改"，这份讲"改完真正沉淀下来的经验"。
> 目标读者：做完 B#3–B#7、想把体感提炼成可迁移原则的你。
> 对应代码：`backend/app/services/chat_service.py`、`backend/tests/test_chat_service.py`、`backend/scratch/a2_real_assessment.py`。

B 系列一共五步，全在真实的 `chat_service` 上做，每步代码+测试、全绿提交：

| 练习 | 内容 | 提交 |
|---|---|---|
| B#3 | 可执行 vs 终态工具分类 + `_execute_tool` | 阶段三② 步骤1-2 |
| B#4 | agent loop + `MAX_AGENT_STEPS` 安全阀 | 阶段三② 步骤3 |
| B#5 | 新增第二个可执行工具 `get_product_detail` + 三层测试 | `3f571fe` |
| B#6 | conclude 硬校验 + search 修 C→R 映射 | `05f8e7a` |
| B#7 | 定级去模型化（维度分→确定性阈值）+ 维度三层硬校验 | `e620373` |

贯穿始终只有两条主线：**① agent loop 的机制**、**② 别信模型**。下面按主题沉淀。

---

## 一、agent loop 的机制

### 1. 终态工具 vs 可执行工具

这是整个改造的心智基石。同样是 `tool_use`，两类工具在 loop 里的命运完全不同：

```python
TERMINAL_TOOLS   = frozenset({TOOL_ASK, TOOL_CONCLUDE})      # 调用即结束本回合
EXECUTABLE_TOOLS = frozenset({TOOL_SEARCH, TOOL_GET_DETAIL}) # 服务端执行 → 结果回喂 → 继续
```

- **终态工具**：模型用它把"最终答案"吐出来（`ask` 出下一个问题、`conclude` 出结论）。调用 = 回合终点，落盘 + SSE。
- **可执行工具**：模型用它"请服务端帮我做件事"（查产品）。服务端真的执行，把结果塞回 `messages`，loop 继续，让模型看着真实数据往下想。

一句话：**终态工具的调用是"终点"，可执行工具的调用是"中间步骤"。** 这条线就是"结构化输出"与"agent loop"的分界。

### 2. loop 的骨架 + 三个不可省的部件

```python
for _step in range(MAX_AGENT_STEPS):          # ① 硬上限：防失控烧钱
    text, tool_result, err, deltas = await _call_llm_with_retry(...)
    # ...错误处理...

    if is_executable_tool(tool_result.name):   # 可执行分支
        result = _execute_tool(db, tool_result.name, tool_result.input)
        messages.append({"role": "assistant", "content": [{"type": "tool_use", ...}]})   # ② 成对回喂
        messages.append({"role": "user",      "content": [{"type": "tool_result", ...}]})
        continue

    if not is_terminal_tool(tool_result.name):  # ③ 未知工具防御
        yield error("unknown_tool"); return

    # 终态分支：吐 delta、落盘、（conclude 建 Assessment）、收尾
    ...
    return

yield error("max_steps")                        # ① 兜底：超步数仍未终态
```

三个**不可省**的部件（漏一个就是坑）：

1. **`MAX_AGENT_STEPS` 硬上限**：agent loop 必须有终止保护。模型理论上可以无限调可执行工具，没上限就是无限烧 token。超限报 error 兜底，不是静默。
2. **`tool_use` + `tool_result` 必须成对追加**：Anthropic API 要求 assistant 的 `tool_use` 和随后 user 的 `tool_result` 通过 `tool_use_id` 配对。少一半、或只塞结果不塞调用，API 直接报错。
3. **未知工具防御**：`is_terminal_tool` 判否就 error 返回。模型可能调一个 schema 里根本没有的名字（或你新加工具忘了归类），别让它掉进终态分支裸奔。

### 3. 中间步骤对用户"透明"

可执行工具的调用 **不落 `chat_messages`、不吐 SSE delta**——用户不该看到"内部查了一次产品库"。只有终态工具的 content 才落盘 + 推前端。

这是刻意的架构选择：**agent 内部的复杂度不外溢到前端契约**。前端始终只收 `delta / completed / error` 三种事件，无论 loop 内部走了 1 步还是 5 步。

> 测试怎么证明"中间不落库"？B#5 的 loop 集成测试断言：最终 `ChatMessage` 只有 `["user", "assistant"]` 两条——search、get_detail 那两步没留痕。

---

## 二、工具在 schema ≠ 模型会用它

这是 A#2 真机实验的结论，也是 B 系列的重要背景认知。`search_products`、`get_product_detail` 一直挂在 `TOOLS_SCHEMA` 里（模型"能"调），但**调不调由 system prompt 一句一句地引导决定**。

我们用 `scratch/a2_real_assessment.py`（`ToolLoggingLLM` 探针记录每次工具调用）做了三组真机对比，人设与 schema 完全相同，**唯一变量是 prompt**：

| prompt | 工具序列 | search | get_detail |
|---|---|---|---|
| 默认业务 prompt | `ask×5 → conclude` | ✗ | ✗ |
| 实验 prompt（含"必须调 search + get_detail"） | `ask×4 → search → get_detail → conclude` | ✓ | ✓ |
| 实验 prompt（删掉"必须调 get_detail"那一行） | `ask×4 → search → conclude` | ✓ | ✗ |

**一行 prompt = 一个工具的开关。** 删掉"必须调用 get_product_detail"这一句，模型就完全不碰这个工具——尽管它明明挂在 schema 里、明明"能"调。

结论：
- **schema 决定"能做什么"，prompt 里的每句话决定"实际做什么"。** 两者要配套设计。
- 生产系统里 **prompt 是"行为契约"**：工具能力是模型的"可以"，prompt 才是"应该"。

> 探针技巧：可执行工具是"内部的"——loop 消费掉它、不吐 SSE 事件，所以从外面的事件流看不到。`ToolLoggingLLM` 装饰器插在 chat_service 和真实 LLM 之间，每次 `stream_chat` 流过的 `ToolResult` 都记下来，才能看见 search 这种内部调用。

---

## 三、别信模型（B 系列的灵魂）

"agent 让模型驱动流程"不等于"信任模型的一切输出"。恰恰相反——**模型驱动得越多，边界校验越要硬**。这条在 B#5/B#6 反复出现，分成几个层面。

### 1. 不信它给的「值」——关键值硬校验

`conclude_assessment` 的 `risk_preference` 会直接落进 `Assessment` 表。模型可能幻觉出 `"C7"`、`"R3"`、`""`。所以落库前硬拦：

```python
VALID_RISK_PREFERENCE = frozenset(PREFERENCE_LABELS)   # 单一事实来源

if tool_result.name == TOOL_CONCLUDE and \
   tool_result.input.get("risk_preference") not in VALID_RISK_PREFERENCE:
    yield error("invalid_risk_preference"); return      # 非法 → 不落任何库
```

要点：**合法集合从 `PREFERENCE_LABELS` 派生，别在两个文件各写一份**（单一事实来源，将来加等级不会漏）。

### 2. 不信它给的「结构」——`.get()` vs `[]`

比"值错了"更极端的畸形是"**key 干脆没给**"。这时 `tool_result.input["risk_preference"]` 直接 `KeyError`，而这行在 loop 里没被 try 包住 → 冒出整个请求 → **500 崩**。你想拦非法值，却被一个更极端的输入绕过并炸了。

```python
tool_result.input["risk_preference"]        # ❌ 缺 key → KeyError → 崩请求
tool_result.input.get("risk_preference")    # ✅ 缺 key → None → 被当非法拦下
```

**"别信模型 = 既不信它给的值、也不信它给的结构。"** `.get()` 是这条原则在取值层的体现。（B#6 专门加了 `test_missing_risk_preference` 覆盖缺字段。）

### 3. 可执行工具的"找不到/异常" → 返回结构化空值，别抛异常

`_execute_tool` 在 loop 里**没被 try 包住**，一旦 `raise`，异常冒出整个请求 → 500。所以工具遇到"产品找不到"这类情况，**返回结构化空值让 loop 继续**，而不是抛异常崩掉整轮：

```python
# get_product_detail：找不到就返回空列表，不抛异常
return {"products": [ {...} for p in products ]}   # products 为空 → {"products": []}

# search_products：非法 C 级也返回空
if rules is None:
    return {"risk_level": risk_level, "products": []}
```

原则：**内部错误不外溢**——对模型返回一个它能理解并继续处理的空结果，比抛异常炸掉整个对话好得多。

### 4. 工具结果必须"可 JSON 序列化"

可执行工具的返回值会 `json.dumps` 成 `tool_result` 回喂给模型。所以：

- **不能返回原始 ORM 对象**（`Product` 实例不可序列化）——必须手动构造 dict。
- **不能塞 `datetime`**（`created_at` 等）——`json.dumps` 直接 TypeError；要么删、要么 `.isoformat()`。
- **`float(可空列)` 要加 None 守卫**：`float(p.return_stddev) if p.return_stddev is not None else None`。

顺带一条设计观：**工具结果只塞模型/下游需要的字段**（`get_product_detail` 只回 `product_code/name/expected_return`），控制 token、也减少模型被无关字段带偏。

### 5. 风险等级不该由模型自由裁量（最深的一课）

A#2 真机里发现：**同样的五维打分（均值 3.6，正好卡 C3/C4 边界），两次跑一个判 C4、一个判 C3**。模型把"维度分 → 等级"当软判断做，边界值会抖。

这在有财务后果的系统里不可接受。正解：**让模型只输出它擅长的主观维度分，"维度分 → 等级"由确定性代码算**（固定阈值/规则），同样的 3.6 永远给同一个等级。

> 这正是 memory 里那条「定价类 agent：关键值来自认证+权威源+服务端计算，别信用户输入/模型」的现场。B#6 的硬校验是第一道防线（拦非法值），更彻底的是把定级这一步整个从模型手里拿走。

---

## 四、C→R 映射：领域正确性 + "测试数据会和 bug 合谋"

### 领域模型

FinWise 里**产品是 R 级（R1–R5，由波动率 σ 算出）**，**客户偏好是 C 级（C1–C5）**，靠 `MATCH_RULES` 把 C 翻译成 R。原有的 `recommendation_service` 一直是对的：

```python
rules = MATCH_RULES.get(pref, MATCH_RULES["C3"])              # pref 是 C 级
.filter(Product.status == "active", Product.risk_level.in_(rules["exact"]))   # 查 R 级
```

而我们重构里新写的 `search_products` 图省事写成 `Product.risk_level == "C4"`——拿 C 级直接比 R 级列，**匹配不到任何真实产品**。这是重构引入的 bug（`recommendation_service` 从没错过）。

### 为什么一直没暴露：测试数据"合谋"

关键教训在这。我们的测试 fixture 和 a2 脚本 seed 的产品 `risk_level` **都填的是 C 级**（`_make_product(db, "P-C4", ..., "C4", ...)`）。于是：

> **buggy 代码（`== "C4"`）+ buggy 测试数据（产品也填 C 级）互相验证、一起"通过"。** 128 个测试全绿、a2 实验里 search C3 也真找到了产品——但一接真实 R 级数据，`search_products` 会静默返回空。

真相藏在没被这层错误假设污染的 `risk_calculator`（算出 R 级）+ `recommendation_service`（用 MATCH_RULES）里。

### 修复的连锁反应，是好事

把 `search_products` 改对（C→R 映射）后，**老测试反而变红了**——因为它们 seed 的 C 级产品现在匹配不到了。

**这不是"你搞坏了"，是它们本来就测错了。** 修 bug 必须**同步纠正被错误假设污染的测试数据**（C 级 seed → 真实 R 级 seed），否则要么假绿、要么修完莫名其妙地红。

```python
# 修前（和 bug 合谋）           # 修后（真实数据）
_make_product(db,"P-C4","..","C4",..)  →  _make_product(db,"P-R4","..","R4",..)
```

### 数据结构层级：外层 key vs 内层 key

修测试时踩的一个纯 Python 坑，值得单记。`search` 返回：

```python
result = {
    "risk_level": "C4",           # ← 外层 key：回显「输入的 C 级」
    "products": [
        {"product_code": ..., "name": ..., "type": ..., "expected_return": ...},  # ← 产品 dict：无 risk_level
    ],
}
```

- `result["risk_level"]` → `"C4"`（外层有，回显输入）
- `result["products"][0]["risk_level"]` → **KeyError**（产品 dict 里没放）
- **`"R4"` 在输出里任何地方都不出现**——它只活在 `.filter(...in_(["R4"]))` 里。C→R 映射靠"**哪些产品被查回来**"证明（R4 产品被 C4 搜到），不靠任何字段值。

JS 类比：`result.risk_level`（"C4"）vs `result.products[0].risk_level`（undefined）——两个不同对象，层级差一层。

---

## 五、JS → Python 的高频陷阱（测试里踩的）

做惯 JS/TS 的人写 Python 测试特别容易踩这几个，Python 还不替你报类型错、直接给诡异运行时行为：

| 陷阱 | JS 直觉 | Python 正解 |
|---|---|---|
| 列表没有 `.filter/.map` | `arr.filter(fn)` | 推导式 `[x for x in arr if fn(x)]` / `any(...)` / `all(...)` |
| 漏 `assert` 的裸表达式**静默通过** | `expect(x).toBe(y)` 必须写 | `x == y` 单独一行什么都不测；ruff `B015` 能抓 |
| `any()` 嵌套 = 两层 `.some()` | `arr.some(m => m.content.some(b => ...))` | `any(any(... for b in m["content"]) for m in msgs)` |
| MockLLMClient 脚本是**两层嵌套** | — | `[[事件...], [事件...]]`：外层=多次调用，内层=一次调用的事件序列；漏一层括号 → 层级错位、行为诡异 |
| `len(dict)` 是 key 数 | — | `len({"products":[...]})` == 1（key 数），不是列表长度；要 `len(result["products"])` |
| `str` 可迭代 | — | `for b in m["content"]` 若 content 是字符串会逐字符遍历 → 先 `isinstance(..., list)` 挡掉 |

还有 pytest 本身：
- `conftest.py` 是**约定文件名**，里面的 fixture 自动注入同目录测试，无需 import（类比 JS 的全局 `beforeEach` 但按依赖注入）。
- 每个 test 结束 DB 自动重置（autouse fixture 的 `create_all` / `drop_all` 包住每个用例）——类比 `beforeEach`/`afterEach`。

---

## 六、把关键值从模型手里拿走（B#7 专题）

三.5 提过"风险等级不该由模型自由裁量"，B#7 就是把这条从**原则**变成**代码**。它是整个 B 系列最硬的一仗，单列一节。

### 缺口：同一系统里两套定级方式

- **问卷链路（确定性）**：`calculate_risk_preference`——分数按阈值映射到 C 级，可复现、零裁量。
- **AI 对话链路（模型裁量）**：conclude 直接 `risk_preference=payload["risk_preference"]`，信任模型**自报**的等级。B#6 只校验它 ∈ C1–C5，**不校验它对不对**。

真机实证（`a2_real_assessment.py` 两次跑）：**同一套维度分（均值 3.6 → normalized 72），模型两次自报一次 C4、一次 C3**；而 C3 那次跟它**自己给的维度分**（72 按阈值应为 C4）**自相矛盾**。软判断会在边界抖——不是理论担忧，是真机里发生过的自相矛盾。

### 方案：算，而不是信

conclude 用模型给的 `dimensions` 走 `calculate_risk_preference(sum(values), len(values)*5)` 得到等级，用**算出来的**落库，`payload["risk_preference"]` 降级为纯校验/参考。同样的 3.6 永远得 C4，抖动被测试永久钉死。

> **为什么不做成"计算 tool"让模型调？** 因为 tool 算出 C4 后，**最终落库的 `risk_preference` 仍是模型在 conclude 里自己填的**——它可以调了 tool 拿到 C4、却还填 C3，信任边界还在模型之后。那条 memory「关键值来自权威源+**服务端计算**」的重点是**"服务端算 + 服务端直接用"**：算对了却路由回模型再吐一遍，等于把信任又交还回去。tool 适合"模型需要这个值去继续推理"，不适合"这个值本身就是不容模型改的最终结论"。定级属于后者。

### 信任层级（想清楚边界到哪为止）

| 数据 | 谁的活 | 怎么对待 |
|---|---|---|
| 维度**分数**（每维 1–5） | 模型（主观判断，它擅长） | **校验结构**（键对/类型对/可选范围），**值信任** |
| 维度分 → **等级** | 代码（确定性阈值） | 已去模型化 ✅ |
| **等级**本身 | —— | 从不信模型自报 ✅ |

### 别信模型的「结构」——维度三层硬校验

只校验"5 个键 + 都是数值"还不够——模型可能给 `{...4个真键, "FOO": 2}`：**丢一个真键、混一个瞎编键，个数还是 5**，照样过。所以校验**键名本身**：

```python
VALID_DIMENSION_KEYS = frozenset(d["key"] for d in load_dimensions())   # 从 yaml 派生，单一事实来源

if (not isinstance(dimensions, dict)
        or set(dimensions.keys()) != VALID_DIMENSION_KEYS               # 缺键/多键/瞎编键/typo
        or not all(isinstance(v, (int, float)) for v in dimensions.values())):  # 5 个键但混字符串
    yield error("invalid_dimensions"); return
```

`set(keys) == 期望集` 顺带就保证了个数=5。而且 `VALID_DIMENSION_KEYS` 从 `load_dimensions()`（读 yaml）派生——yaml 改维度它自动跟着变，不怕配置漂移。这和 `VALID_RISK_PREFERENCE ← PREFERENCE_LABELS` 是同一个"单一事实来源"套路。

### 这轮的坑（都很典型）

| 坑 | 教训 |
|---|---|
| `UnboundLocalError: payload/values` | 函数内变量一旦在某处被赋值，整个函数体都算 local，赋值点之前引用就崩——定义要提前 |
| 把已归一化的 normalized 当 `total_score` 传 | 分清"原始总分"和"已归一值"，别二次归一；normalized 从 `calculate_risk_preference` 返回值取（单一来源） |
| `normalized, pref = 四元组` | Python 解包必须**数量精确**（不像 JS 解构可只取前几个）；`*_` 吞尾部 |
| 一批老测试变红（连 router 都中招） | 改"落库值从哪来"这种核心契约必然辐射；变红是**照出"哪些测试依赖旧假设"的信号** |
| 老测试用**瞎编维度键**蒙混 | 键校验一上，假键测试立刻现形——正是这层校验的价值 |
| 可变对象当默认参数 | 常量 vs 字面量**不修**陷阱、只改命名；真修靠 None 哨兵+函数体内新建 |

---

## 七、一句话总结每条

1. 终态工具是终点，可执行工具是中间步骤——这条线就是"结构化输出 vs agent loop"。
2. loop 三件套不可省：`MAX_STEPS` 硬上限、`tool_use`+`tool_result` 成对回喂、未知工具防御。
3. 中间工具步骤对用户透明，前端契约只有 `delta/completed/error`。
4. 工具在 schema ≠ 模型会用它——一行 prompt = 一个工具开关。
5. 别信模型：不信值（硬校验）、不信结构（`.get()`）、找不到返回空别抛异常、结果必须可 JSON 序列化。
6. 关键值（风险等级）不该由模型自由裁量——边界会抖，交给确定性代码。
7. buggy 代码 + buggy 测试数据会合谋假绿——修代码让老测试红是好事，同步纠正 fixture。
8. 层级看清：外层 key ≠ 内层产品 key；`"R4"` 从不进输出，映射靠"查回来哪些产品"证明。
9. 关键值（等级）"算而不信"：服务端算 + 服务端直接用，别路由回模型再吐一遍——tool 也不行。
10. 别信模型的结构不只看"个数+类型"，还要校验**键名**（从权威定义派生期望集）——缺一真键混一假键，个数照样对。
11. 信任分层：维度分数=模型的活（校验结构、信任值）；维度→等级=代码的活（确定性）；等级=从不信自报。

做到能对着自己的代码把这十一条讲清楚，B 系列就真正内化了。
