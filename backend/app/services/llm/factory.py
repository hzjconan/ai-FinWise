from app.services.llm.base import LLMClient


def get_llm_client() -> LLMClient:
    """FastAPI 依赖注入入口。P1 阶段不提供真实实现——
    测试通过 app.dependency_overrides 注入 MockLLMClient；
    P2 接入 Anthropic SDK 后在此返回真实 client。"""
    raise NotImplementedError(
        "LLM client 尚未接入（P1 阶段）。请在测试中通过 dependency_overrides "
        "注入 MockLLMClient，或等待 P2 的 Anthropic SDK 实现。"
    )
