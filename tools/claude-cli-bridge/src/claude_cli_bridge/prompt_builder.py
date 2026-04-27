"""把 Anthropic messages API 的入参拼成单个文本 prompt 喂给 Claude CLI。

CLI 不支持 tool-use 协议，所以我们：
1. 把 system prompt 放最前
2. 追加一段强约束文本，要求模型只输出**符合某个工具 input_schema 的纯 JSON**
3. 把对话历史按 `<role>: <content>` 渲染
4. 末尾加 `Assistant:` 引导补全
"""
import json
from typing import Any


def build_prompt(
    *,
    system: str,
    messages: list[dict],
    tools: list[dict],
) -> str:
    parts: list[str] = []

    if system:
        parts.append(system.strip())

    if tools:
        parts.append(_render_tools_instruction(tools))

    parts.append(_render_messages(messages))
    parts.append("Assistant:")

    return "\n\n".join(p for p in parts if p)


def _render_tools_instruction(tools: list[dict]) -> str:
    lines = [
        "# 输出格式（极其重要）",
        "",
        "你**必须**只输出**一个纯 JSON 对象**，且包含字段 `tool_name` 与 `tool_input`，",
        "其中 `tool_name` 必须是下列工具之一，`tool_input` 必须符合该工具的 input_schema。",
        "**禁止**输出 markdown、代码块围栏、自然语言解释、前后缀。",
        "",
        "可用工具：",
    ]
    for tool in tools:
        lines.append("")
        lines.append(f"## {tool['name']}")
        if tool.get("description"):
            lines.append(tool["description"])
        lines.append("input_schema:")
        lines.append("```json")
        lines.append(json.dumps(tool["input_schema"], ensure_ascii=False, indent=2))
        lines.append("```")

    lines.append("")
    lines.append("示例（仅示意格式）：")
    lines.append('{"tool_name": "ask_next_question", "tool_input": {"content": "..."}}')
    return "\n".join(lines)


def _render_messages(messages: list[dict]) -> str:
    lines: list[str] = ["# 对话历史"]
    if not messages:
        lines.append("（空——这是第一轮，请生成开场白）")
        return "\n".join(lines)
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        rendered = _render_content(content)
        lines.append(f"{role.capitalize()}: {rendered}")
    return "\n".join(lines)


def _render_content(content: Any) -> str:
    """支持两种 content 形态：字符串、list[block]。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", ""))
            elif btype == "tool_use":
                # 历史里的 assistant tool_use：把 input 平铺成 JSON 让模型看到自己的"上一步选择"
                parts.append(json.dumps(
                    {"tool_name": block.get("name"), "tool_input": block.get("input", {})},
                    ensure_ascii=False,
                ))
            elif btype == "tool_result":
                parts.append(str(block.get("content", "")))
        return " ".join(parts)
    return str(content)
