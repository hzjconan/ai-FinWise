"""把 prompt 喂给本地 `claude -p --output-format json`，回收 result 字段。"""
from __future__ import annotations

import asyncio
import json
import os


class CLIRunError(RuntimeError):
    """claude CLI 调用失败。"""


async def run_claude_cli(prompt: str, *, timeout: float = 90.0) -> str:
    """执行 claude CLI 并返回 result 文本。"""
    cmd = [_claude_bin(), "-p", "--output-format", "json"]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(prompt.encode("utf-8")), timeout=timeout
        )
    except asyncio.TimeoutError as e:
        proc.kill()
        await proc.wait()
        raise CLIRunError(f"claude CLI 超时（{timeout}s）") from e

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace")
        raise CLIRunError(f"claude CLI 返回 {proc.returncode}：{err.strip() or '(empty stderr)'}")

    out = stdout.decode("utf-8", errors="replace").strip()
    try:
        payload = json.loads(out)
    except json.JSONDecodeError as e:
        raise CLIRunError(f"无法解析 claude CLI 输出：{out[:200]}") from e

    if payload.get("is_error") or payload.get("subtype") != "success":
        raise CLIRunError(f"claude CLI 报错：{payload}")

    result = payload.get("result")
    if not isinstance(result, str):
        raise CLIRunError(f"claude CLI 输出缺少 result 字段：{payload}")
    return result


def _claude_bin() -> str:
    return os.environ.get("CLAUDE_CLI_PATH", "claude")
