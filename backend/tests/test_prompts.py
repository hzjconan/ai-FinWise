"""风险评估 prompt / 维度加载测试。"""
from app.services.llm import prompts
from app.services.llm.prompts import load_dimensions, load_system_prompt


def test_load_dimensions_returns_five():
    dims = load_dimensions()
    assert len(dims) == 5
    keys = {d["key"] for d in dims}
    assert keys == {
        "experience",
        "loss_tolerance",
        "income_stability",
        "investment_horizon",
        "volatility_tolerance",
    }


def test_each_dimension_has_1_to_5_anchors():
    for d in load_dimensions():
        assert set(d["anchors"].keys()) == {1, 2, 3, 4, 5}, d["key"]
        for score, text in d["anchors"].items():
            assert isinstance(text, str) and text.strip(), (d["key"], score)


def test_load_system_prompt_contains_all_dimensions_and_tool_rules():
    prompt = load_system_prompt()
    # 角色与工具约束
    assert "风险评估助手" in prompt
    assert "ask_next_question" in prompt
    assert "conclude_assessment" in prompt
    # 所有维度名都渲染进来
    for d in load_dimensions():
        assert d["name"] in prompt
        assert d["key"] in prompt
    # 占位符必须被替换
    assert "{DIMENSIONS}" not in prompt


def test_system_prompt_has_injection_isolation():
    """S2：system prompt 含"输入隔离/防注入"声明——客户消息中的指令应被忽略。"""
    prompt = load_system_prompt()
    assert "输入隔离" in prompt or "防注入" in prompt
    assert "忽略" in prompt          # 明确"忽略"注入指令
    assert "待评估" in prompt        # 把用户输入定性为"待评估内容"而非指令


def test_env_override_uses_custom_file_as_is(tmp_path, monkeypatch):
    """FINWISE_SYSTEM_PROMPT_FILE 指向自定义文件时读它；无 {DIMENSIONS} 也不报错、原样返回。"""
    custom = tmp_path / "custom.md"
    custom.write_text("你是自定义助手。可用工具 search_products。", encoding="utf-8")
    monkeypatch.setenv("FINWISE_SYSTEM_PROMPT_FILE", str(custom))
    prompts.load_system_prompt.cache_clear()
    try:
        assert load_system_prompt() == "你是自定义助手。可用工具 search_products。"
    finally:
        prompts.load_system_prompt.cache_clear()  # 清缓存，避免污染其他用例


def test_env_override_still_replaces_dimensions_placeholder(tmp_path, monkeypatch):
    """自定义文件若含 {DIMENSIONS}，仍会被渲染替换。"""
    custom = tmp_path / "c.md"
    custom.write_text("头\n{DIMENSIONS}\n尾", encoding="utf-8")
    monkeypatch.setenv("FINWISE_SYSTEM_PROMPT_FILE", str(custom))
    prompts.load_system_prompt.cache_clear()
    try:
        out = load_system_prompt()
        assert "{DIMENSIONS}" not in out
        assert "投资经验" in out  # 维度被渲染进来
    finally:
        prompts.load_system_prompt.cache_clear()
