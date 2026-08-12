# langgraph-lab — LangGraph 学习隔离环境

阶段六 LangGraph 学习的**独立环境**，刻意隔离于 `backend/`（不污染 FinWise 的 Anthropic 栈）。

- **独立 venv**：`langgraph-lab/.venv`（不提交，已 gitignore）。装了 langgraph 1.2.10 + langchain-anthropic 1.5.4 + anthropic SDK。
- **LLM 来源**：基础篇节点走本地 bridge（`bash backend/scratch/run_bridge.sh` 起在 :8787），裸 anthropic SDK 调用（bridge 兼容）。`.env`（gitignore）放 LangSmith key 等。
- **概念/笔记**：见 `docs/ai-agent-learning/langgraph-notes.md`。

## 脚本
- `lg_01_linear_graph.py` — 线性图：把 s6_02 手写 supervisor 重写成 LangGraph（State/Node/Edge/条件边）。
- `verify_chatanthropic_bridge.py` — 验证 ChatAnthropic 走 bridge（结论：响应格式不达标、崩，同 tool_runner；见 langgraph-notes）。

## 跑
```
bash backend/scratch/run_bridge.sh          # 另开终端起 bridge
cd langgraph-lab && .venv/bin/python lg_01_linear_graph.py
```
