"""验证：langchain 的 ChatAnthropic 能否走本地 bridge（纠正"bridge 撑不起 langchain"的判断）。
bridge 约束：必须带 tool、只吐 tool_use → 所以 bind_tools 后再 invoke。
代理：ChatAnthropic 不收 http_client，用 NO_PROXY 让 localhost 免本机 HTTP_PROXY 劫持。"""
import os
os.environ["NO_PROXY"] = "localhost,127.0.0.1"       # 关键：绕开本机代理对 localhost 的劫持
os.environ["ANTHROPIC_API_KEY"] = "bridge-no-key-needed"

from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool

@tool
def pick_level(risk_level: str) -> str:
    """给出客户的风险等级 C1–C5。"""
    return risk_level

llm = ChatAnthropic(
    model="claude-haiku-4-5-20251001",
    anthropic_api_url="http://localhost:8787",       # ← 指向 bridge
    max_tokens=512,
)
llm_with_tools = llm.bind_tools([pick_level])         # bridge 需要 tool

resp = llm_with_tools.invoke("客户说：我很激进，能扛大波动。给个风险等级。")
print("✅ 调用成功")
print("  tool_calls:", resp.tool_calls)
print("  content   :", repr(resp.content)[:120])
