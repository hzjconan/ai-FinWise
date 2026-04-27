"""把 Claude CLI 的纯文本输出解析成 (tool_name, tool_input)。

prompt_builder 已经强约束模型输出形如 {"tool_name": "...", "tool_input": {...}} 的 JSON，
但模型偶尔会包代码块或带前后缀，这里做最小限度的容错。
"""
import json
import re

# 匹配 ```json ... ``` 或 ``` ... ``` 围栏
_FENCED = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


class ToolParseError(ValueError):
    """CLI 输出无法解析为合法 tool_use。"""


def parse_tool_call(raw: str, allowed_tools: list[str]) -> tuple[str, dict]:
    """从 CLI 输出中提取 (tool_name, tool_input)。"""
    if not raw or not raw.strip():
        raise ToolParseError("CLI 输出为空")

    candidate = _strip_fences(raw)
    obj = _extract_first_json_object(candidate)
    if obj is None:
        raise ToolParseError(f"未能在输出中找到 JSON 对象：{raw[:200]}")

    name = obj.get("tool_name")
    inp = obj.get("tool_input")
    if not isinstance(name, str) or not isinstance(inp, dict):
        raise ToolParseError(f"JSON 缺少 tool_name / tool_input：{obj}")
    if name not in allowed_tools:
        raise ToolParseError(f"未知 tool_name {name!r}，允许：{allowed_tools}")
    return name, inp


def _strip_fences(text: str) -> str:
    """如果整段被代码块围栏包裹，取出围栏内容；否则返回原文本。"""
    matches = list(_FENCED.finditer(text))
    if matches:
        # 取第一个围栏内容
        return matches[0].group(1)
    return text


def _extract_first_json_object(text: str) -> dict | None:
    """扫描文本，找到第一个完整、平衡的 `{...}` JSON 对象。"""
    text = text.strip()
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                snippet = text[start : i + 1]
                try:
                    obj = json.loads(snippet)
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None
    return None
