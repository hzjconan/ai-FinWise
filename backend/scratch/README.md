# scratch —— 阶段 1/2 学习脚本

配套 `docs/ai-agent-learning/`。这里是**可运行、带练习**的裸调脚本，用来打通 roadmap 的
**阶段一（LLM API 基础）**和**阶段二（Prompt Engineering）**。

> 这些是学习脚本，不是业务代码（不在 `backend/app/` 下，不触发测试硬约束）。放心改、随便跑。

## 前置：启动 bridge

脚本通过官方 `anthropic` SDK 调用，但把 base_url 指向本地 **claude-cli-bridge**，
后者用你本地的 `claude` CLI（订阅）应答，**无需 ANTHROPIC_API_KEY**。

另开一个终端：

```bash
bash backend/scratch/run_bridge.sh
# 保持它运行，看到 "Uvicorn running on http://127.0.0.1:8787" 即就绪
```

## 跑脚本

```bash
cd backend
.venv/bin/python scratch/s1_01_first_call.py       # 第一次调用（结构化输出）
.venv/bin/python scratch/s1_02_streaming_events.py # 看清流式底层事件
.venv/bin/python scratch/s1_03_multiturn.py        # 上下文即内存（无状态）
.venv/bin/python scratch/s2_01_prompt_shaping.py   # 玩转仓库真实评估 prompt
.venv/bin/python scratch/s2_02_structured_json.py  # 结构化输出 + 扛刁钻输入
```

每个脚本文件末尾/中部都有 **`练习 TODO`**，改完重跑观察变化——这才是学习的核心。

## ⚠️ bridge 的限制（背后是 Claude CLI，不是真实 API）

| 能力 | bridge | 说明 |
|---|---|---|
| 消息角色 / system prompt | ✅ | 正常 |
| 流式 SSE 事件 | ✅ | 但只吐 tool_use，不吐纯文本 |
| tool / 结构化输出 | ✅ | **每次调用必须带 tool**，否则 400 |
| 纯文本回答 | ❌ | 硬性要求工具 JSON |
| 真实 token 计数 | ❌ | usage 恒为 0 |
| temperature | ❌ | 参数被忽略 |
| max_tokens 截断 | ❌ | 参数被接住但从不转发给 CLI，回答不会被截断，stop_reason 恒为 tool_use |
| 合法 JSON 保证 | ⚠️ | 偶发「格式跑偏」（未转义引号等），脚本已用重试 + 优雅降级处理 |

代理注意：本机设了 `HTTP_PROXY=127.0.0.1:8002`，会劫持发往 localhost 的请求。
`_bridge.py` 已用 `trust_env=False` 的 httpx 客户端绕开，无需你操心。

## 「需真 key」才能练的部分

以下目标 bridge 覆盖不了，拿到真实 `ANTHROPIC_API_KEY` 后再练（各脚本文末/TODO 处有说明）：

- **真实 token 用量 / 成本量级**（`s1_02` 里 usage=0）。
- **temperature / top_p 采样对照实验**。
- **纯文本对话**（不带 tool 的自由回答）。
- **`max_tokens` 截断**（`s1_02` TODO#1）：bridge 吞掉 `max_tokens`，回答不会被截断、`stop_reason` 也不会变成 `max_tokens`；真实 API 上把 `max_tokens` 调小会看到回答硬截断 + `stop_reason == "max_tokens"`。
- **删「必须调用工具」看输出稳定性**（`s2_02` TODO#2）：bridge 在 prompt_builder 里硬加「必须只输出工具 JSON」并强制解析工具调用，无视你的 system 指令，所以删掉那句也没差别；真实 API（tool_choice=auto）上删掉后模型可能改用自由文本、不调工具，导致结构化输出不稳定。真正的硬保证是 `tool_choice`，不是 system 里的一句话。

切真实 API：设 `ANTHROPIC_API_KEY`，把 `_bridge.py::BRIDGE_BASE_URL` 去掉（用官方默认地址）。

## 与 roadmap 的对应

| 脚本 | roadmap 阶段 | 学到的核心概念 |
|---|---|---|
| s1_01 | 一 | model/system/messages/tools 四要素、结构化输出 |
| s1_02 | 一 | 流式事件、增量 JSON、（token 概念） |
| s1_03 | 一 | 无状态、上下文即内存 |
| s2_01 | 二 | prompt 即代码、复用仓库真实 prompt、失败模式 |
| s2_02 | 二 | JSON Schema 强约束、enum 校验、prompt injection 防御 |

学完这 5 个脚本 + 做完各自 TODO，阶段一/二的验收标准（见 `00-roadmap.md`）基本达成，
下一步就能进阶段三（`02-tooluse-refactor.md`）。
