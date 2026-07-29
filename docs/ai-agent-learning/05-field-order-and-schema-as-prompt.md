# 05. 字段顺序影响输出质量——「schema 即 prompt」

> 一个反直觉但可迁移的 tool_use 工程经验：**tool 的 `input_schema` 里字段的「顺序」会影响模型输出质量**。
> 根源和「字段的存在会塑造输出内容」是同一个——自回归 + schema 即 prompt。
> 真实例子对应 `backend/app/services/chat_service.py` 的 `conclude_assessment`。

---

## 一、根本原因：自回归生成

LLM 是**自回归**的——从左到右逐 token 生成，每个 token 都以**前面已经生成的内容**为条件。

模型填 tool 入参 JSON 时，倾向**按 schema 的 `properties` 顺序**逐字段吐出（流式看就是一串 `input_json_delta` 片段，先 key1 再 key2……）。所以：

> **先写的字段，成为后写字段的「上下文」。**

这就是为什么字段顺序不是纯排版，而是**在悄悄决定模型的思考顺序**。

---

## 二、推论：CoT vs 事后找补

同样两个字段，顺序不同，效果天差地别：

| 顺序 | 效果 |
|---|---|
| `{reasoning, answer}`（推理在前） | answer 以 reasoning 为条件生成 = **chain-of-thought**，难题更准 |
| `{answer, reasoning}`（答案在前） | answer **先定死**，reasoning 只是**事后找补**，改不了已给的答案 |

一条实操推论：**`confidence` 该放在答案之后**——它是对「已经给出的答案」的评估，放前面等于让模型先猜置信度再凑答案。

一句话：**要让字段 B 建立在字段 A 之上，就把 A 放前面。** 结论类字段应在依据类字段之后。

---

## 三、FinWise 真实例子：`conclude_assessment` 顺序是反的

看当前 schema（`chat_service.py` 的 `TOOLS_SCHEMA`）：

```python
"properties": {
    "content": {"type": "string"},          # 给用户看的结论话术
    "risk_preference": {"enum": [C1..C5]},   # ★ 结论（等级）
    "summary": {"type": "string"},           # 依据摘要
    "dimensions": {"type": "object"},        # ★ 依据（5 维打分）
}
```

**问题**：结论（`content` + `risk_preference`）排在**依据**（`summary`、`dimensions`）**之前**。等于让模型**先拍板 C 级、再回头补五维分**——五维分成了对既定结论的**事后解释**，而不是推出结论的**依据**。

**更好的顺序（依据在前、结论在后）**：
```
dimensions → summary → risk_preference → content
（先逐维打分 → 汇总 → 得出等级 → 组织话术）
```
这样 C 级是从五维**推导**出来的，话术又建立在等级之上，一层层有条件。

### B#7 让这个点更重要了

[[03-agent-loop-lessons]] 第六节把定级改成了**用 `dimensions` 确定性算等级**（不再采信模型自报的 `risk_preference`）。这意味着：

- `risk_preference` 字段现在**只作参考**，它排哪其实无所谓了；
- 但 **`dimensions` 的打分质量变得空前重要**（它现在直接决定最终等级）——而它偏偏排在**最后**，是在写完 content / risk_preference 之后才打的分，最像"事后凑"。

所以后 B#7 的理想顺序更该是 **`dimensions` 打头**：先认真逐维打分（真正的 reasoning），再由代码把它算成等级。字段顺序和"定级去模型化"是**同一个诉求的两面**——都想让"依据先于结论"。

> 这是个**真实、当前、可改进**的设计点。改它要动 schema + 补测试（可作为后续练习），本笔记先把「为什么」讲清。

---

## 四、实操细节：`properties` 顺序有效，`required` 顺序无效

- **`properties` 的顺序**：影响模型吐字段的先后 → **有效**，要精心排。
- **`required` 数组的顺序**：只是"哪些必填"的集合，**不影响**生成顺序 → 随便排。

排字段顺序时，动 `properties`，别指望调 `required` 的次序有用。

---

## 五、Caveats（别过度神话）

1. **不是 100% 保证**：模型只是**强烈倾向**按 schema 顺序吐 key，不保证。可用字段 `description`、或 strict/structured output 模式加强。
2. **只对难题明显**：简单任务模型一步就对，顺序无所谓；越是需要推理的任务，顺序效应越明显。
3. **推理在前有成本**：多生成 reasoning = 更多 token、更高延迟。
4. **重推理优先用 thinking**：需要大量推理时，优先用 Claude 的 **extended / adaptive thinking**；在 schema 里塞 `reasoning` 字段是**轻量替代**（够用、但不如原生 thinking 强）。

---

## 六、更大的图景：字段的「存在」vs「顺序」

这条经验有个同源的姊妹（早期练习 s1_01）：给 tool schema **加一个 `analogy_target` 字段**，会把整个回答**扭成类比腔**——哪怕你没在 prompt 里要求类比。

合起来看：

| 维度 | 塑造什么 | 根源 |
|---|---|---|
| 字段的**存在** | 输出的**内容/风格**（加 `analogy_target` → 类比腔） | schema 即 prompt |
| 字段的**顺序** | 输出的**质量**（reasoning 在前 → CoT） | 自回归 |

**根本都是一句话：`schema` 不只是"数据格式约束"，它本身就是 prompt 的一部分——你写进 schema 的每个字段、每个顺序，都在给模型下指令。** 设计 tool 时，把 schema 当 prompt 来设计，而不是当被动的数据契约。

关联：[[03-agent-loop-lessons]]（定级去模型化 = 顺序问题的架构解）、[[reference-pricing-agent-orchestration]]（关键值别信模型，与"依据先于结论"同气）。
