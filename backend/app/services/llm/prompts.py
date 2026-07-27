"""Prompt 与维度配置加载。

来源文件在 backend/prompts/，随代码版本化。调 prompt 直接改 markdown/yaml 重启服务即可。
"""
import os
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


def _system_file() -> Path:
    """system prompt 文件路径：优先环境变量 FINWISE_SYSTEM_PROMPT_FILE，否则用默认 SYSTEM_FILE。

    用于实验 / 多环境切换不同 prompt，而不改业务文件或代码。
    （注意 load_system_prompt 有 lru_cache——env 应在进程启动前设好；测试改 env 需 cache_clear()。）
    """
    override = os.environ.get("FINWISE_SYSTEM_PROMPT_FILE")
    return Path(override) if override else SYSTEM_FILE


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    """加载 system prompt；若含 {DIMENSIONS} 占位符则替换为维度渲染结果。

    文件路径可由环境变量 FINWISE_SYSTEM_PROMPT_FILE 覆盖（默认业务文件 SYSTEM_FILE）。
    """
    file = _system_file()
    template = file.read_text(encoding="utf-8")
    if "{DIMENSIONS}" in template:
        return template.replace("{DIMENSIONS}", _render_dimensions(load_dimensions()))
    # 默认业务 prompt 必须含 {DIMENSIONS}（防误删导致锚点丢失）；自定义覆盖 prompt 可省略。
    if file == SYSTEM_FILE:
        raise RuntimeError(f"{SYSTEM_FILE} 缺少 {{DIMENSIONS}} 占位符")
    return template
