from dataclasses import dataclass


@dataclass
class TextDelta:
    """content 字段的增量文本片段。"""
    text: str


@dataclass
class ToolResult:
    """模型完成的 tool 调用（流结束时产出一次）。"""
    name: str            # ask_next_question | conclude_assessment
    input: dict          # 完整参数对象（含 content、risk_preference、summary、dimensions 等）


@dataclass
class LLMError:
    """LLM 调用过程中的错误。用于让 provider 上报失败而不抛异常。"""
    message: str
    code: str = "llm_error"


LLMEvent = TextDelta | ToolResult | LLMError
