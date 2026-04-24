from app.config import settings
from app.services.llm.base import LLMClient


def get_llm_client() -> LLMClient:
    """FastAPI 依赖注入入口。

    - LLM_PROVIDER=mock：抛 NotImplementedError；测试通过 dependency_overrides 注入 MockLLMClient
    - LLM_PROVIDER=api：返回 AnthropicLLMClient（自动读 ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL）
    """
    provider = settings.LLM_PROVIDER.lower()
    if provider == "api":
        # 延迟导入，避免 mock 模式下强制要求 anthropic SDK
        from app.services.llm.anthropic_client import AnthropicLLMClient

        return AnthropicLLMClient(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=settings.ANTHROPIC_MAX_TOKENS,
        )
    if provider == "mock":
        raise NotImplementedError(
            "LLM_PROVIDER=mock：测试请通过 dependency_overrides 注入 MockLLMClient。"
            "接真实 LLM 请设置 FINWISE_LLM_PROVIDER=api。"
        )
    raise ValueError(f"未知 LLM_PROVIDER: {settings.LLM_PROVIDER}")
