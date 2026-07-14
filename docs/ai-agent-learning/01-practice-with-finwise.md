# B. 用 FinWise 练手：实战清单

> 配套 `00-roadmap.md`。这份文档把七个学习阶段**映射到本仓库的真实代码**，告诉你每个阶段"读哪个文件、改哪个文件、做什么练习、怎么验收"。
> 遵守仓库铁律：**每个改动必须有对应测试**（后端 pytest，前端 Cypress）。AI 功能的"测试"优先做 eval（见阶段五）。

## 先建立全局认知：这个仓库的 AI 现状

好消息——FinWise 不是白纸，它已经是个能读的活教材。先花 30 分钟通读这几处：

| 能力 | 位置 | 状态 |
|---|---|---|
| LLM 抽象层（Protocol） | `backend/app/services/llm/base.py` | ✅ 已有，`stream_chat(system, messages, tools)` |
| Provider 工厂 / 注入 | `backend/app/services/llm/factory.py` | ✅ mock / api 双模式 |
| 真实 Anthropic 客户端 | `backend/app/services/llm/anthropic_client.py` | ✅ 已接 SDK |
| Mock 客户端（测试用） | `backend/app/services/llm/mock.py` | ✅ 脚本化响应 |
| **Tool-use agent** | `backend/app/services/chat_service.py` | ✅ 已是 tool-use（`ask_next_question` / `conclude_assessment`） |
| 流式 SSE | `backend/app/routers/chat.py` + chat_service | ✅ delta / completed / error 事件 |
| Prompt 版本化 | `backend/prompts/risk_assessment_system.md`、`risk_assessment_dimensions.yaml` | ✅ 随代码版本化 |
| 智能推荐 | `backend/app/services/recommendation_service.py` | ⚠️ **纯规则匹配，没用 AI**（练习空间大） |
| **Eval / 可观测性** | — | ❌ **完全缺失**（阶段五的主战场） |
| 配置 | `backend/app/config.py`（`FINWISE_LLM_PROVIDER` 等） | ✅ |

> 关键判断：**能力已经搭好，缺的是"你亲手从零重建一遍的理解"和"eval 防护网"。** 所以练习的核心不是"加功能"，而是"拆开看懂 + 补上缺口"。

---

## 阶段一：LLM API 基础 → 剥离框架，裸调一遍

**读**：`anthropic_client.py`（看它如何把 SDK 调用翻译成 `LLMEvent` 流）、`config.py`（模型、max_tokens、provider 开关）。

**练习**
1. 在 `backend/scratch/`（新建，git 忽略）写一个 20 行独立脚本，不经过任何 service，直接用 anthropic SDK 调一次 `claude-haiku-4-5-20251001`，打印文本 + token 用量。
2. 把它改成流式，逐 chunk 打印——对照 `anthropic_client.py` 里真实项目怎么处理流。
3. 对照实验：同一个 prompt，`temperature=0` vs `1` 各跑 3 次，记录差异。

**验收**
- [ ] 能说清 `anthropic_client.py` 里每一步在做什么。
- [ ] 能独立写出带 token 统计的流式调用。

> 注：这是纯学习脚本、不进 `app/`，可豁免测试（属仓库白名单外的 scratch）。

---

## 阶段二：Prompt Engineering → 玩透 risk_assessment prompt

**读**：`prompts/risk_assessment_system.md` + `risk_assessment_dimensions.yaml` + `prompts.py`（看占位符 `{DIMENSIONS}` 如何渲染注入）。这是仓库里"prompt 即代码"的样板。

**练习**
1. 改 `risk_assessment_dimensions.yaml` 某个维度的评分锚点，观察评估结论怎么变。
2. 给 system prompt 加一条约束（如"提问不超过两句话"），验证模型是否遵守。
3. 故意写个模糊的用户回答，看模型会不会跑偏、格式会不会崩。

**验收**
- [ ] 能解释 5 维度 + 评分锚点如何塑造 `conclude_assessment` 的输出。
- [ ] 改一处 prompt 能预测并验证行为变化。

> 测试：prompt/yaml 属白名单可豁免；但若你顺手加了 prompt 断言逻辑到 service，需补 pytest。

---

## 阶段三：Tool Use → 看懂并重建 agent loop（详见文档 C）

**读**：`chat_service.py` 全文，重点 `TOOLS_SCHEMA`、`_call_llm_with_retry`、`handle_user_message`。这是仓库里最核心的 agent 代码。

**关键观察**：FinWise 的 agent 是**单轮工具**模式——模型每次要么 `ask_next_question` 要么 `conclude_assessment`，没有"调用工具→拿结果→再想"的多步循环。这是理解"什么是完整 agent loop"的最佳反例对照。

**练习**（进阶版在文档 C 展开）
1. 画出 `handle_user_message` 一个回合的时序图。
2. 思考：如果要让 agent 能调用"查询产品库"工具再继续对话，`handle_user_message` 要怎么改成真正的 while 循环？
3. 在 scratch 里手写一个最小多步 agent loop（2 个工具，模型自主决定顺序），不复用框架。

**验收**
- [ ] 能说清 FinWise 现在为什么不需要多步循环、什么场景才需要。
- [ ] 手写出一个能连续调多工具的 loop。

**测试**：改 `chat_service.py` 必须补 `tests/test_chat_service.py`（用 `MockLLMClient.push` 脚本化工具响应）。

---

## 阶段四：RAG → 给推荐加"会解释"的检索

**现状**：`recommendation_service.py` 是纯规则匹配（风险等级 → 产品），不涉及 AI、无法解释"为什么推这个"。这是最好的 RAG 练习靶子。

**练习**
1. 把产品库（`models/product.py`）的描述字段做 embedding，存入向量库（本地 chroma / sqlite-vec 起步）。
2. 新增一个 service：给定客户评估结论，检索最相关的产品说明，喂给 LLM 生成一段**个性化推荐理由**。
3. 对照：规则匹配给"推荐哪些"，RAG 给"为什么适合你"——两者结合。

**验收**
- [ ] 跑通"评估结论 → 检索产品说明 → LLM 生成推荐理由"。
- [ ] 能解释为什么这里用 RAG 比把全部产品塞进 prompt 好。

**测试**：新增 service 必须补 pytest（mock LLM + 固定检索结果，断言理由包含关键要点）。

---

## 阶段五：评估与可观测性 → 补上仓库最大的缺口 ★

**现状**：AI 对话只有 pytest + MockLLM 的**结构性**测试（断言事件流、断言落库），**没有任何质量 eval**——没人保证"改了 prompt 后，真实模型给出的风险判断还准"。这正是阶段五要填的坑，也最贴合仓库"改动必须有测试"的铁律。

**练习**
1. 在 `backend/evals/`（新建）收集 10–20 条 golden 样例：一段模拟客户对话 → 期望的 `risk_preference` 和结论要点。
2. 写一个 eval 脚本（跑真实 `LLM_PROVIDER=api`）：
   - 规则断言：`risk_preference` 是否落在期望范围。
   - LLM-as-judge：结论摘要是否覆盖期望要点。
3. 输出一个通过率分数。改 prompt 前后各跑一次，看分数升降。
4. 给 `chat_service` 的每次 LLM 调用加轻量 trace 日志（耗时、token、tool 名），或接一个 tracing 工具。

**验收**
- [ ] 有一个能一键跑的 `evals/` 套件，输出通过率。
- [ ] 改 prompt 后能立刻量化质量变化。
- [ ] 能在日志/trace 里定位一次坏评估卡在哪一步。

**测试**：eval 脚本本身在 `evals/`（走真实 API），与 pytest 单测互补——单测保结构，eval 保质量。这条建议专门向用户确认它与 CI 的关系。

---

## 阶段六：框架与多 Agent → 用框架重写 chat agent 做对照

**练习**
1. 用 **Claude Agent SDK** 重写 `chat_service` 的 agent 部分，对比它替你封装了 `TOOLS_SCHEMA` / 重试 / 事件流里的哪些东西。
2. 拆成两个 agent：一个"提问 agent"负责收集信息，一个"结论 agent"负责出风险评级，用 supervisor 协调。

**验收**
- [ ] 能把框架的每个抽象对应回你在 chat_service 里读过的手写代码。
- [ ] 跑通一个 2-agent 协作评估流程。

**测试**：若改动落进 `app/`，补对应 pytest；若只是 scratch 对照实验可豁免。

---

## 阶段七：生产化 → 盘点 FinWise 上线风险

**练习**（分析为主，挑一项动手）
1. **成本**：`ANTHROPIC_MODEL` 现在是 haiku，评估这个任务是否够用；给 system prompt 上 prompt caching。
2. **延迟**：SSE 流已有；评估 `_call_llm_with_retry` 的重试是否会放大尾延迟。
3. **安全**：`handle_user_message` 直接把用户输入拼进 messages——分析 prompt injection 风险（用户能否诱导模型乱给高风险评级），加输出校验（`risk_preference` 必须在 C1–C5，已有 enum 约束，检查是否够）。

**验收**
- [ ] 产出一份 FinWise AI 功能的"成本/延迟/安全"风险清单 + 至少一项落地修复（带测试）。

---

## 建议推进顺序

不必严格按阶段线性走。对本仓库最高效的路径：

1. **阶段一 → 三 → 五**（裸调理解 → 读懂现有 agent → 补 eval）先打通主干，这三步能让你真正掌控现有 AI 对话功能。
2. 再回补**阶段二/四**（prompt 深挖 + 给推荐加 RAG），做增量功能。
3. **阶段六/七**随实际需要推进。

> 下一份文档 C 会把"阶段三 + 把现有对话改造成完整 tool-use agent"完整展开成可执行的改造方案。
