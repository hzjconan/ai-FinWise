"""Prompt 与维度配置加载。

来源文件在 backend/prompts/，随代码版本化。调 prompt 直接改 markdown/yaml 重启服务即可。
"""
from functools import lru_cache
from pathlib import Path

import yaml

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
SYSTEM_FILE = PROMPTS_DIR / "risk_assessment_system.md"
DIMENSIONS_FILE = PROMPTS_DIR / "risk_assessment_dimensions.yaml"


@lru_cache(maxsize=1)
def load_dimensions() -> list[dict]:
    """返回 5 维度的结构化定义列表。"""
    with open(DIMENSIONS_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, list) or len(data) != 5:
        raise RuntimeError(f"{DIMENSIONS_FILE} 必须是 5 个维度的列表")
    return data


def _render_dimensions(dims: list[dict]) -> str:
    lines: list[str] = []
    for d in dims:
        lines.append(f"## {d['name']} (`{d['key']}`)")
        lines.append(d["description"])
        lines.append("")
        lines.append("评分锚点：")
        for score in sorted(d["anchors"].keys()):
            lines.append(f"- **{score}** — {d['anchors'][score]}")
        lines.append("")
    return "\n".join(lines).rstrip()


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    """加载 system prompt，把 {DIMENSIONS} 占位符替换为维度渲染结果。"""
    template = SYSTEM_FILE.read_text(encoding="utf-8")
    rendered = _render_dimensions(load_dimensions())
    if "{DIMENSIONS}" not in template:
        raise RuntimeError(f"{SYSTEM_FILE} 缺少 {{DIMENSIONS}} 占位符")
    return template.replace("{DIMENSIONS}", rendered)
