# s2_01 练习用的改动版 prompt（实验存档）

这两个文件是做 `backend/scratch/s2_01_prompt_shaping.py` 的 TODO#1 / TODO#2 时
**改动过的业务 prompt 副本**，仅供复习实验用；`backend/prompts/` 下的原文件已复原。

- `risk_assessment_dimensions.yaml` —— TODO#1：把多个维度的评分锚点改激进
  （如损失承受压成「8% 以上=5 分」、收入稳定性「无收入=5 分」等）。
  效果：同一段客户对话的 conclude 从 C3 变成 C5（详见 s2_01 注释里的改前/改后记录）。
- `risk_assessment_system.md` —— TODO#2：加了「每个问题不超过 20 字」约束。
  效果：开场问题从约 150 字缩到约 28 字。

⚠️ 不要把这些改动合回 backend/prompts/——那是 FinWise 真在用的业务配置。
