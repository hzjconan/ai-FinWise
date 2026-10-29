# 外部面试题 × 已学课程：差距分析（⚠️ 临时文档）

> ⚠️ **临时参考**：补课期间对照用，全部补完后删除（有价值的结论届时已沉淀进 concepts-basics / mock-interview）。

> 输入：`misc/AI_面试问题搜集.docx`（约 60 题，含 4 道非 AI 后端系统设计题）
> 对照：00~06、concepts-basics、chroma-primer、langgraph-notes、mock-interview（Q1~Q26）
> 用途：① 定补课清单（学习方案待讨论）② 复习清单 + 新题库 ③ 其它建议

图例：🆕 课程完全没有 / 🟠 提到过但只是一句话 / ✅ 学过且讲透

---

## 一、课程里没有、需要补的（最高优先级）

按主题归成 10 块。「面试频率」是我对 AI 应用工程师岗的判断。

| # | 主题 | 面试题里的具体考点 | 现状 | 面试频率 |
|---|---|---|---|---|
| N1 | **检索工程进阶：Hybrid + Rerank + Query 改写** | BM25 原理（TF 饱和 / IDF / 长度归一化）；向量 + BM25 双路召回 → 归一化/去重 → **RRF** 融合；**Bi-Encoder vs Cross-Encoder** 分工；Top-K 漏斗（召回 30~50 → 重排 10~20 → 给 LLM 5~10）；重排数量依据；Query 改写防语义漂移 | 🆕（BM25 只在 Q3 当反例提过；rerank 只出现过一个词） | ★★★ 几乎必考 |
| N2 | **RAG 评估体系** | RAGAS：faithfulness（忠实度）、context recall/precision、answer relevancy；幻觉率、引用准确率；nDCG@10；Embedding 选型看 MTEB/C-MTEB Retrieval 分数 + 业务自测 | 🟠 学过 Hit@K / MRR / 召回·精确，**没有"生成侧"指标** | ★★★ |
| N3 | **LLM 推理内部** | Tokenizer 产物（token_id / attention_mask / position_ids / 特殊 token）；**Prefill vs Decode**；**KV Cache**；RoPE 位置编码；temperature 缩放 logits + top_p/top_k；Encoder-only / Decoder-only / Encoder-Decoder 三类分别对应什么模型和用途 | 🟠 学过注意力/多头/temperature 直觉，**没有推理流程** | ★★★ |
| N4 | **MCP 协议 + Skills** | JSON-RPC 2.0；传输层 stdio / Streamable HTTP；`Mcp-Session-Id` 有状态 vs 无状态；MCP 调用失败策略（调用前校验 → 调用时退避/超时/熔断/降级链 → 输出校验 → 转人工）；Skill 太多时怎么提升命中率（描述区分、负面边界、分层） | 🆕 | ★★★ 2025 起热点 |
| N5 | **Agent 可靠性工程** | 死循环防护进阶：**重复调用检测**（工具名+参数 hash 计数）、带上次错误重试、重试降级；**事务性**：Saga 补偿、状态持久化与断点恢复、工具幂等；**并发控制**：Semaphore 控并发、RateLimiter 控 QPS、`asyncio.timeout`；熔断器 | 🟠 学过 MAX_STEPS / recursion_limit / 重试退避，**没有 Saga、熔断、并发、重复检测** | ★★★ |
| N6 | **上下文工程进阶** | 压缩**触发策略**（固定阈值 / 语义边界 / 按占比分级压缩）；压缩时怎么不丢关键信息（按 schema 结构化抽取、原文与摘要分层存、让 LLM 自查遗漏）；**上下文分层**（Task / Working / Knowledge / Runtime / Historical）；lost in the middle 的对策 | 🟠 Q12 追问里讲过"别把 blob 塞进 State + trim/summarize"，**没有体系** | ★★☆ |
| N7 | **多 Agent 拓扑与纠错** | supervisor / 群聊式 / 流水线 / 层级式 各自适用场景与优缺点；Planner 输出做 **DAG 程序校验**（环检测、依赖 id 存在）；结果冲突引入第三方复核；多 agent 常见问题（context 爆炸、格式互不认） | 🟠 只手写过 supervisor | ★★☆ |
| N8 | **可观测性工程化（指标体系）** | trace_id + span_id 贯穿 LLM/Tool/MCP；拦截器埋点；token（prompt/completion，P95、按用户维度）、延迟分阶段（P50/P95/P99、超时率、工具耗时占比）、工具成功率 + **错误分类**（参数/网络/超时/返回异常）；Prometheus / OpenTelemetry | 🟠 学过 LangSmith tracing（"看一次运行"），**没有"指标 + 告警"** | ★★☆ |
| N9 | **文档入库工程** | 复杂文档 chunk：表格保留表头、跨页表先合并再切、图片 OCR + 生成描述、OCR 保坐标/置信度；PDF 解析工具（Docling / marker）；**增量更新**（stable id + 内容 hash + 删旧）；**chunk 冲突**（版本/时间/来源优先级）；**RAG 权限**（检索前 metadata 过滤 tenant/department/user；权限频变时只存 doc_id，权限映射放 DB） | 🟠 学过确定性 chunk id、metadata 过滤，**没有复杂文档/冲突/权限** | ★★☆ |
| N10 | **训练与后训练（概念级）** | Pretraining → SFT → 奖励建模 → RL；**PPO vs GRPO**（GRPO 去掉 value model、组内相对奖励）；奖励函数设计（准确率/长度惩罚/步骤奖励）；**LoRA**（低秩矩阵，只训少量参数）；Agentic RL；vLLM vs Ollama（PagedAttention、continuous batching） | 🆕 | ★☆☆ 应用岗问得浅；算法/平台岗必问 |

另外两个零散的新点，可并入上面：
- **意图识别 + 低置信度兜底**（规则引擎处理简单意图、置信度 × 风险等级矩阵决定是否追问）→ 并入 N6 或 N7。课程里 Router 模式提过但没讲置信度。
- **Agent 能力怎么算达标**（任务完成率、工具选择正确率、参数正确率、鲁棒性/负向测试、上线后用户干预率）→ 并入 N2，把 eval 从"检索"扩到"agent 级"。

---

## 二、学过、但没讲透或没出过题的（复习 + 新题）

| # | 知识点 | 课程里在哪 | 缺的那一层 |
|---|---|---|---|
| R1 | 余弦 / 点积 / 欧氏 / L2 归一化 | concepts「点积与模长」「余弦」、chroma「hnsw:space」 | 没出过题；没推过**归一化后 `‖a−b‖² = 2 − 2cos`**（三者排序等价） |
| R2 | Temperature | Q2、concepts | 机制层：`softmax(logits / T)`，以及与 top_p / top_k 的先后关系 |
| R3 | Transformer / 注意力 | concepts 末尾 | Q/K/V 各自的作用；三类架构（BERT/e5 是 encoder-only、Claude/GPT 是 decoder-only） |
| R4 | 降低幻觉 | Q9 grounding 纵深防御 | 面试常要"三层落地方案"：检索质量 → 限制生成自由度 → 验证（引用约束 / 自检 / verifier） |
| R5 | RAG 效果差怎么定位 | Q24（推荐质量下降） | **逐层隔离法**：固定检索结果测 prompt → 绕过 rerank → 看正确文档是否进 TopK → 换 embedding 对比 |
| R6 | Function Calling vs 纯 Prompt 工具调用 | 阶段二/三、05 schema 即 prompt | 没以"对比题"形式出过；本质区别是"有没有 schema 强约束" |
| R7 | JSON 输出不稳定 | 阶段二、03「别信模型的结构」 | 五层递进：prompt 约束 → 容错解析 → 原生结构化输出（tool_use / strict）→ Pydantic 校验 → 带错误重试 / 降级 |
| R8 | Prompt 注入 | Q19、06 S2 | 课上讲了输入隔离/最小权限；题里还有**执行端 sandbox**、**输出端**（敏感信息过滤、超大内容截断） |
| R9 | 延迟 / 成本优化 | Q25、06 C1/L2 | 并行工具、结果缓存、模型分级、streaming；prompt caching（C1 当时"暂不改"，**没动手做过**） |
| R10 | Chunking | Q8、s4_04 | 补"按标题/语义切"和表格/跨页（与 N9 一起） |
| R11 | LangChain vs LangGraph | langgraph-notes、Q22 | 一句话定位：组件库 vs 有状态工作流编排；两者怎么配合 |
| R12 | 标准 prompt 结构 / prompt 优化 | 阶段二 | Role / Goal / Context / Rules / Tools / Output / Examples / Task；"什么时候**不能**调工具"要写明 |
| R13 | Token vs 字符 | 阶段一 | 中英文 token 比例不同 → 影响成本估算与截断 |
| R14 | 知识库存什么、怎么选型 | chroma-primer 第七节 | 原文 / chunk / 向量 / 元数据 / 权限 / 版本 / 来源；"向量库存向量，关系库存结构化信息" |

### 复习题库（Q27 起，接 mock-interview 的编号）

> 答题方式和之前一样：你先答，我点评打分再追问。

**第六轮 · 基础机制回炉**
- **Q27 🟢** 两个 embedding 已经做过 L2 归一化。点积、余弦、欧氏距离三者是什么关系？Chroma 用 `l2` 和 `cosine` 时，top-K 结果会一样吗？
- **Q28 🟡** temperature 在数学上改了什么？T→0 和 T→∞ 时分布各变成什么样？同时设 `temperature=0.7, top_p=0.9`，执行顺序是什么？
- **Q29 🟡** 为什么 embedding 模型（e5、BGE）大多是 encoder-only，而对话模型是 decoder-only？反过来用会出什么问题？
- **Q30 🟡** 同样的产品说明，中文版比英文版贵还是便宜？为什么？做 `max_tokens` 截断或成本预估时要注意什么？

**第七轮 · 工程方案（把散的知识点串起来）**
- **Q31 🔴** FinWise 产品问答 RAG 上线后用户反馈"答非所问"。给一套**逐层隔离**的排查步骤：每一步固定什么、换掉什么、看哪个指标。
- **Q32 🔴** "降低幻觉"请给出能落地的**三层**方案，并说清每一层在 FinWise 里对应哪段代码或哪个机制。
- **Q33 🟡** Function Calling 和"在 prompt 里约定 `<tool>xxx</tool>` 让模型输出"相比，优缺点各是什么？什么场景你会选后者？
- **Q34 🔴** 模型输出的 JSON 偶尔解析失败。从轻到重给出你的防御层级，每层能挡住哪类问题、挡不住哪类？
- **Q35 🟡** 防 prompt 注入，你之前答过"输入隔离 → 声明 → 输出校验 → 最小权限"。如果 agent 能**执行代码 / 访问 URL**，还要加哪些层？

**第八轮 · 取舍题**
- **Q36 🟡** 一份标准的生产 system prompt 由哪几块组成？为什么"什么时候**不要**调工具"必须写明？拿 FinWise 的 `search_products` 举例。
- **Q37 🔴** 你在 06 体检里把 prompt caching 判为"暂不改"。现在面试官问："你们 system prompt 每轮重复计费，为什么不开缓存？"给出量化的取舍论证（前缀长度、命中率、TTL、写入溢价）。
- **Q38 🟡** 什么时候只用 LangChain 组件就够，什么时候必须上 LangGraph？用你的 lg_02 循环图举例。

---

## 三、其它建议

### 1. 这份面试题的答案有几处不准，别照背

| 原文 | 问题 | 更准的说法 |
|---|---|---|
| "实际项目 60% 是 chunk 问题、20% recall、10% rerank、10% prompt" | 编出来的比例，面试官追问出处就答不上 | 说"经验上 chunk 和召回问题最常见，所以排查从检索侧开始"，不要报数字 |
| "RAG 检索方式：HNSW 图检索、IVF 聚类索引" | 这两个是 **ANN 索引结构**，不是检索方式 | 检索方式 = 向量 / 关键词 / 混合 / 结构化 / 图检索（GraphRAG）；HNSW/IVF 是向量检索的底层索引 |
| "Encoder 读取所有词元生成向量表，Decoder 根据 encoder 生成下一个词" | 这是原始 Transformer（翻译）的结构；GPT/Claude 这类 decoder-only **没有 encoder** | 先讲三类架构，再讲各自的注意力掩码（双向 vs 因果） |
| "Temperature 不改变 logits" | 不严谨：它把 logits **除以 T** 再做 softmax | "不改变模型前向算出的原始 logits，只改变采样前的分布形状" |
| "Query 改写设余弦 ≥ 0.8 防语义改变" | 阈值随模型变（你在 s4 亲眼看到 e5 分数挤在 0.7~0.95） | 阈值要在自己的 embedding 上用 eval 定，不是常数 |
| "vLLM 有显存分页" | 只说了一半 | PagedAttention（KV cache 分页，减少显存碎片）+ continuous batching（请求级动态拼批）→ 高吞吐；Ollama 主打本地单机、易用 |
| "Agent 判断危险输入主要靠规则引擎、特征模型" | 这是**风控业务**的答案，不是通用 agent 安全 | 先确认题目问的是"内容安全/注入"还是"业务风控"，两种答法不同 |

### 2. 非 AI 题单独放
短链接、验证码、订单超时、分布式任务只执行一次——这 4 道是**后端系统设计**题，不是 AI 题。按之前的约定不混进 AI 文档；要的话另开 `backend-system-design-notes.md`。不过其中的**幂等、分布式锁、原子状态机**和 N5（Agent 事务性）是同一套思想，可以放在一起讲。

### 3. 两份材料都没覆盖、但面试常问的
- **长期记忆（Memory）**：短期 vs 长期、记忆的写入/检索/遗忘策略。路线图阶段六列了，但没做。
- **Fine-tune vs RAG vs Prompt 怎么选**：经典决策题，正好接 N10。
- **Human-in-the-loop**：高风险动作审批、中断/恢复（LangGraph `interrupt`）——和 N5 的断点恢复是同一个机制。
- **线上评估闭环**：用户反馈（👍/👎）→ bad case 回流进 golden set → 回归 eval。课程只做过离线 eval。
- **项目叙述**：把 FinWise 的 B#7 去模型化定级、C→R bug、替身掩盖真实契约整理成 2~3 个 STAR 故事。面试里"讲一个你踩过的坑"必问，这些是你最有说服力的素材。

### 4. 学习方式上的建议
- **能动手的就动手**（保持之前的风格）：N1 可以在 s4 的 FinWise 产品库上加 BM25 + RRF + cross-encoder，用 s5_01 的 Hit@K/MRR 量提升；N4 可以把 `search_products` 包成一个 **MCP server** 让 Claude Code 调用；N5 可以给 chat_service 加重复调用检测。
- **只学概念的**：N10（RL/LoRA）在 Mac 上没法真训，建议概念级 + 一张图讲清 PPO/GRPO 的差别；除非目标是算法岗。
- **补完 N3 后回头重答 Q2/Q3**，验证"本质层"是不是真的补上了（总评里的待补第 2 点）。

---

## 四、补课计划（2026-10-21 定）

**定位**：主攻 AI 应用 / Agent 工程师；算法（N10）只做科普，不作为重点。
**顺序**：按面试频率。**复习题穿插**进对应新课，学完马上用题检验。**4 道非 AI 系统设计题**另开 `backend-system-design-notes.md`，和 N5 一起讲。
**每课流程**：开课写讲义骨架 `lessons/LNN-<主题>.md`（L + 全局连续序号，本轮 L01~L10，以后追加接着编） → 逐步引导讲解（每步讲完追加进讲义）→ 动手（脚本 + 测试）→ 穿插题（引导式）→ 课末精简进 concepts-basics。

| 课 | 内容 | 动手 | 穿插复习题 | 状态 |
|---|---|---|---|---|
| 1 | **N1 检索进阶**：BM25 原理 → 混合检索 + RRF → Bi/Cross-Encoder 重排、Top-K 漏斗 → Query 改写（R14 知识库选型未讲，挪到第 9 课）| 在 s4 FinWise 产品库上做 BM25 + RRF + cross-encoder，用 s5_01 的 Hit@K/MRR 对比纯向量 | Q27（余弦/点积/L2）、Q31（逐层排查） | ✅ L01 |
| 2 | **N2 RAG 评估**：RAGAS（忠实度、context recall/precision、答案相关性）、nDCG、Embedding 选型、agent 级指标；线上反馈回流闭环 | 给 s4_02 的生成结果写忠实度 / 引用准确率 eval（规则 + LLM-as-judge） | Q32（幻觉三层） | ✅ L02 |
| 3 | **N4 MCP + Skills**：JSON-RPC、传输层、会话状态、失败策略、Skill 命中率 | 把 `search_products` 包成 MCP server，接入 Claude Code 调用 | Q33（FC vs 纯 prompt）、Q34（JSON 防御层级） | ✅ L03 |
| 4 | **N3 推理内部**：Tokenizer 产物 → Prefill/Decode → KV Cache → RoPE → 采样（temperature/top_p）→ 三类架构 | 用 e5 tokenizer 看 token_id/attention_mask；对比中英文 token 数 | Q28、Q29、Q30、Q37（prompt caching ↔ KV cache） | ✅ L04 |
| 5 | **N5 Agent 可靠性** + 后端系统设计 4 题：重复调用检测、Saga 补偿、断点恢复、幂等、并发/限流、熔断；HITL | FinWise chat_service 加重复调用检测（附 pytest） | Q35（执行端/输出端防注入） | ✅ L05 |
| 6 | **N6 上下文工程** + 意图识别：压缩触发、结构化抽取、上下文分层、lost in the middle、置信度兜底；长期记忆 | 无代码改动；发现 FinWise prompt 与 TOOLS_SCHEMA 不一致（暂不修） | Q36（prompt 结构） | ✅ L06 |
| 7 | **N7 多 Agent 拓扑**：四种拓扑取舍、Plan 的 DAG 校验、冲突仲裁 | 可选：Plan DAG 校验小脚本 | Q38（LangChain vs LangGraph） | ⬜ |
| 8 | **N8 可观测性指标**：trace/span 贯穿、token/延迟/成功率/错误分类、Prometheus/OTel | 可选 | — | ⬜ |
| 9 | **N9 文档入库** + R14 知识库存什么/怎么选型：表格/跨页/OCR、Docling、增量更新、chunk 冲突、权限过滤 | 可选：增量更新（hash + stable id） | — | ⬜ |
| 10 | **N10 科普**（一页）：预训练 → SFT → RLHF、PPO vs GRPO、LoRA、vLLM vs Ollama；Fine-tune vs RAG vs Prompt 怎么选 | 无 | — | ⬜ |
| 待定 | **Python 面试八股 补充学习/复习**（AI 面试多半会问）；可能一并安排 Go（`~/workspace/learn-program-language/go`）——2026-10-23 记录，范围和形式到时再讨论 | — | — | ⬜ |
| 收尾 | 整理 2~3 个 FinWise STAR 项目故事 → 综合模拟面试一轮 → **全知识点 cheat sheet**（含阶段一~七，形式届时讨论）→ 结论沉淀后**删除本文档** | — | — | ⬜ |
